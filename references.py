"""Comparación visual local con imágenes de entrenamiento, sin inferencia clínica."""

import csv
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def pixels(image):
    image = ImageOps.exif_transpose(image).convert("RGB")
    return np.asarray(
        image.resize((224, 224), Image.Resampling.BILINEAR), dtype="float32"
    )


def digest(image):
    image = ImageOps.exif_transpose(image).convert("RGB")
    return hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()


class ReferenceIndex:
    def __init__(self, manifest, extractor):
        self.manifest = Path(manifest)
        self.extractor = extractor
        self.rows = []
        self.vectors = None

    def build(self):
        with self.manifest.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        batches, pending, seen = [], [], set()
        for row in rows:
            if row["split"] != "train" or row["label"] not in ("0", "1"):
                continue
            try:
                with Image.open(row["path"]) as image:
                    fingerprint = digest(image)
                    if fingerprint in seen:
                        continue
                    array = pixels(image)
            except (OSError, ValueError):
                continue
            seen.add(fingerprint)
            self.rows.append(dict(row, fingerprint=fingerprint))
            pending.append(array)
            if len(pending) == 32:
                batches.append(
                    self.extractor(np.stack(pending), training=False).numpy()
                )
                pending = []
        if pending:
            batches.append(self.extractor(np.stack(pending), training=False).numpy())
        if not batches:
            raise ValueError(
                "No hay imágenes de entrenamiento disponibles para comparar."
            )
        vectors = np.concatenate(batches)
        if not np.isfinite(vectors).all():
            raise ValueError("Características de referencia inválidas.")
        self.vectors = vectors / np.maximum(
            np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12
        )

    def search(self, image, count=3):
        if self.vectors is None:
            self.rows = []
            self.build()
        vector = self.extractor(pixels(image)[None], training=False).numpy()[0]
        if not np.isfinite(vector).all():
            raise ValueError("Características de captura inválidas.")
        scores = self.vectors @ (vector / max(np.linalg.norm(vector), 1e-12))
        fingerprint = digest(image)
        matches = []
        for index in np.argsort(-scores, kind="stable"):
            row = self.rows[index]
            if row["fingerprint"] == fingerprint:
                continue
            try:
                with Image.open(row["path"]) as source:
                    thumbnail = ImageOps.contain(
                        ImageOps.exif_transpose(source).convert("RGB"), (90, 76)
                    )
            except (OSError, ValueError):
                continue
            matches.append(
                dict(
                    image=thumbnail,
                    similarity=float(scores[index]),
                    label="Benigna" if row["label"] == "0" else "Maligna",
                    source=f"train/{'benign' if row['label'] == '0' else 'malignant'}/{Path(row['path']).name}",
                )
            )
            if len(matches) == count:
                break
        return matches
