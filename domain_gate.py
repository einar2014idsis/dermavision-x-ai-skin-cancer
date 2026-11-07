"""Filtro experimental lesión/objeto. No estima malignidad ni garantiza dominio."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def gate_pixels(image):
    # Igual resolución efectiva en positivos y negativos CIFAR (32x32), para
    # reducir un atajo por resolución. No se usa este resize en benign/malignant.
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = image.resize((32, 32), Image.Resampling.BILINEAR)
    return np.asarray(
        image.resize((224, 224), Image.Resampling.BILINEAR), dtype="float32"
    )


def feature_model(model):
    import tensorflow as tf

    pooled = next(
        layer
        for layer in model.layers
        if isinstance(layer, tf.keras.layers.GlobalAveragePooling2D)
    )
    return tf.keras.Model(model.inputs[0], pooled.output)


def gate_scores(features, parameters):
    features = np.asarray(features, dtype=float)
    weights = np.asarray(parameters["weights"], dtype=float)
    if (
        features.ndim != 2
        or features.shape[1] != len(weights)
        or not np.isfinite(features).all()
    ):
        raise ValueError("Características del filtro inválidas.")
    z = features @ weights + float(parameters["bias"])
    return 1 / (1 + np.exp(-np.clip(z, -60, 60)))


class DomainGate:
    def __init__(self, path, model_path, model):
        self.parameters = json.loads(Path(path).read_text(encoding="utf-8"))
        if self.parameters.get("schema") != "dermavision-domain-v1":
            raise ValueError("Formato de filtro incompatible.")
        digest = hashlib.sha256(Path(model_path).read_bytes()).hexdigest()
        if digest != self.parameters["classifier_sha256"]:
            raise ValueError("El filtro corresponde a otra versión del modelo.")
        self.threshold = float(self.parameters["threshold"])
        if not np.isfinite(self.threshold) or not 0 < self.threshold <= 1:
            raise ValueError("Umbral de dominio inválido.")
        if not self.parameters.get("validation_passed"):
            raise ValueError(
                "El filtro no cumplió sus criterios de validación exploratoria."
            )
        self.features = feature_model(model)

    def assess(self, image):
        x = self.features(gate_pixels(image)[None], training=False).numpy()
        score = float(gate_scores(x, self.parameters)[0])
        return score >= self.threshold, score
