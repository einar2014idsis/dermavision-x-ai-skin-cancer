"""Calibración reproducible del clasificador binario sin usar el conjunto de test."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def sigmoid(value):
    value = np.clip(np.asarray(value, dtype=float), -60, 60)
    return 1.0 / (1.0 + np.exp(-value))


def logit(score):
    score = np.clip(np.asarray(score, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(score / (1 - score))


class ScoreCalibration:
    def __init__(
        self,
        slope=1.0,
        intercept=0.0,
        threshold=0.5,
        uncertain_low=None,
        uncertain_high=None,
        source="sin calibrar",
    ):
        self.slope = float(slope)
        self.intercept = float(intercept)
        self.threshold = float(threshold)
        self.uncertain_low = float(
            uncertain_low if uncertain_low is not None else threshold
        )
        self.uncertain_high = float(
            uncertain_high if uncertain_high is not None else threshold
        )
        self.source = source

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data.get("schema") != "dermavision-calibration-v1"
            or data.get("fit_split") != "validation"
        ):
            raise ValueError("Archivo de calibración incompatible o con fuga de test.")
        return cls(
            data["slope"],
            data["intercept"],
            data["threshold"],
            data["uncertain_low"],
            data["uncertain_high"],
            "validación interna",
        )

    def apply(self, raw_score):
        return float(sigmoid(self.slope * logit(raw_score) + self.intercept))

    def decision(self, calibrated_score):
        score = float(calibrated_score)
        if self.uncertain_low <= score <= self.uncertain_high:
            return "uncertain"
        return "malignant" if score >= self.threshold else "benign"
