"""Verificación semántica experimental a resolución 224, sin diagnóstico.

Taxonomía fija en inglés para CLIP. Las similitudes no son probabilidades.
La evaluación local no valida piel sana, otros trastornos ni cámara real.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

PROMPTS = {
    "lesion": [
        "a close-up clinical photograph of a pigmented skin lesion",
        "a dermoscopic photograph of a mole on human skin",
        "a close-up photograph of an irregular dark mole on skin",
        "a clinical photograph of a skin tumor",
        "a close-up photograph of a red skin lesion",
    ],
    "skin": [
        "a close-up photograph of normal human skin without a lesion",
        "a photograph of a hand and fingers",
        "a photograph of a human face",
        "a photograph of a person",
        "a photograph of an arm or leg without a skin lesion",
    ],
    "other": [
        "a photograph of a bottle or a drinking glass",
        "a photograph of a phone or a computer",
        "a screenshot of a computer application with text and buttons",
        "a photograph of furniture in a room",
        "a photograph of food or fruit",
        "a photograph of an animal or an insect",
        "a photograph of a plant or a flower",
        "a photograph of a landscape or a building",
        "a photograph of a vehicle",
        "a photograph of clothing or fabric",
        "a photograph of a rock or a piece of wood",
        "a photograph of a coin, a tool or a household object",
        "a drawing or a diagram with text",
        "a blurry photograph with no recognizable subject",
    ],
}
TAXONOMY_HASH = hashlib.sha256(json.dumps(PROMPTS, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class DomainDecision:
    state: str  # accepted / rejected / uncertain
    message: str
    margin: float


def decide(similarities, accept_margin, reject_margin):
    s = np.asarray(similarities, dtype=float)
    if s.shape != (3,) or not np.isfinite(s).all():
        raise ValueError("Respuesta inválida del verificador visual.")
    lesion, skin, other = s
    margin = float(lesion - max(skin, other))
    if margin >= accept_margin:
        return DomainDecision(
            "accepted", "Imagen compatible con una posible lesión cutánea.", margin
        )
    if other > skin and margin <= reject_margin:
        return DomainDecision(
            "rejected",
            "Se reconoce contenido ajeno al análisis de lesiones cutáneas.",
            margin,
        )
    return DomainDecision(
        "uncertain",
        "No se distingue una lesión con suficiente claridad. Ajuste el recorte o use otra foto.",
        margin,
    )


class SemanticEncoder:
    def __init__(self, folder):
        import torch

        os.environ.setdefault("USE_TF", "0")
        from transformers import CLIPModel, CLIPProcessor

        torch.set_num_threads(4)
        self.torch = torch
        self.processor = CLIPProcessor.from_pretrained(
            folder, local_files_only=True, use_fast=False
        )
        self.model = CLIPModel.from_pretrained(folder, local_files_only=True).eval()
        text = [prompt for prompts in PROMPTS.values() for prompt in prompts]
        tokens = self.processor(text=text, return_tensors="pt", padding=True)
        with torch.inference_mode():
            vectors = self.model.get_text_features(**tokens)
            self.text_vectors = vectors / vectors.norm(dim=-1, keepdim=True)

    def similarities(self, images):
        # Contain+pad preserves the selected region. CLIP's default center crop
        # would silently remove an off-centre lesion from a rectangular photo.
        prepared = [
            ImageOps.pad(
                ImageOps.exif_transpose(im).convert("RGB"),
                (224, 224),
                method=Image.Resampling.BICUBIC,
                color=(123, 117, 104),
            )
            for im in images
        ]
        inputs = self.processor(images=prepared, return_tensors="pt")
        with self.torch.inference_mode():
            vectors = self.model.get_image_features(**inputs)
            vectors = vectors / vectors.norm(dim=-1, keepdim=True)
            similarities = (vectors @ self.text_vectors.T).cpu().numpy()
        groups, start = [], 0
        for prompts in PROMPTS.values():
            groups.append(similarities[:, start : start + len(prompts)].max(axis=1))
            start += len(prompts)
        return np.stack(groups, axis=1)


class SemanticGate:
    def __init__(self, folder, config_path):
        config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        if (
            config.get("schema") != "dermavision-semantic-v1"
            or config.get("taxonomy_sha256") != TAXONOMY_HASH
            or config.get("validation_passed") is not True
            or config.get("combined_validation_passed") is not True
        ):
            raise ValueError(
                "El verificador visual no cuenta con una evaluación compatible."
            )
        self.accept_margin = float(config["accept_margin"])
        self.reject_margin = float(config["reject_margin"])
        if not (-2 < self.reject_margin < 0 < self.accept_margin < 2):
            raise ValueError("Umbrales del verificador inválidos.")
        self.encoder = SemanticEncoder(folder)

    def assess(self, image):
        return decide(
            self.encoder.similarities([image])[0],
            self.accept_margin,
            self.reject_margin,
        )


def combine_decisions(decision, reference_accepted):
    """Both verifiers must agree before the malignancy model may run."""
    if decision.state == "accepted" and not reference_accepted:
        return DomainDecision(
            "uncertain",
            "Los verificadores no coinciden. Use una foto más cercana y clara de la lesión.",
            decision.margin,
        )
    return decision


class CombinedGate:
    def __init__(self, semantic, reference):
        self.semantic = semantic
        self.reference = reference

    def assess(self, image):
        decision = self.semantic.assess(image)
        if decision.state != "accepted":
            return decision
        accepted, _ = self.reference.assess(image)
        return combine_decisions(decision, accepted)
