"""Conversión compartida por la inferencia y las explicaciones del clasificador."""

import numpy as np
from PIL import Image, ImageOps

INPUT_SIZE = (224, 224)


def classifier_pixels(image):
    photo = ImageOps.exif_transpose(image).convert("RGB")
    return np.asarray(photo.resize(INPUT_SIZE, Image.Resampling.BILINEAR), dtype="float32")
