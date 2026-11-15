"""Carga el clasificador y sus filtros para las interfaces de escritorio y web."""

import json
import os
from pathlib import Path

from app_paths import MODEL_DIR
from calibration import ScoreCalibration
from domain_gate import DomainGate
from semantic_gate import CombinedGate, SemanticGate

DEFAULT_EXPERIMENT = MODEL_DIR / "combined01"
LEGACY_EXPERIMENT = MODEL_DIR / "functional-02"
PORTABLE_EXPERIMENT = MODEL_DIR / "dermavision-24621"


def default_experiment():
    override = os.environ.get("DERMAVISION_EXPERIMENT")
    if override:
        if override not in {PORTABLE_EXPERIMENT.name, LEGACY_EXPERIMENT.name}:
            raise ValueError("DERMAVISION_EXPERIMENT debe ser dermavision-24621 o functional-02.")
        experiment = MODEL_DIR / override
        if not (experiment / "model.keras").is_file():
            raise FileNotFoundError(f"Modelo solicitado no instalado: {override}")
        return experiment
    pointer = MODEL_DIR / "active_experiment.txt"
    if pointer.is_file():
        name = pointer.read_text(encoding="utf-8").strip()
        if Path(name).name == name and (
            name.startswith("candidate-") or name in {PORTABLE_EXPERIMENT.name, LEGACY_EXPERIMENT.name}
        ):
            experiment = MODEL_DIR / name
            if (experiment / "model.keras").is_file():
                return experiment
    if (PORTABLE_EXPERIMENT / "model.keras").is_file():
        return PORTABLE_EXPERIMENT
    if (DEFAULT_EXPERIMENT / "model.keras").is_file():
        return DEFAULT_EXPERIMENT
    return LEGACY_EXPERIMENT


def load_classifier(path):
    import tensorflow as tf

    config = json.loads(
        Path(path).with_name("config.json").read_text(encoding="utf-8")
    )
    if (
        config.get("class_mapping") != {"benign": 0, "malignant": 1}
        or config.get("image_size") != 224
        or not isinstance(config.get("threshold"), (int, float))
        or not 0 < config["threshold"] < 1
    ):
        raise ValueError(
            "Configuración incompatible: requiere el modelo del pipeline DermaVision-X."
        )
    model = tf.keras.models.load_model(path, compile=False, safe_mode=True)
    if model.input_shape != (None, 224, 224, 3) or model.output_shape != (
        None,
        1,
    ):
        raise ValueError("Arquitectura de entrada/salida incompatible.")
    calibration = ScoreCalibration.load(
        Path(path).with_name("calibration.json")
    )
    calibration_path = Path(path).with_name("calibration.json")
    if config["threshold"] != 0.5 and (
        not calibration_path.is_file()
        or calibration.threshold != config["threshold"]
    ):
        raise ValueError("El umbral del modelo no coincide con su calibración.")
    gate_path = MODEL_DIR / "domain-02" / "config.json"
    reference_path = MODEL_DIR / "domain-01" / "gate.json"
    reference_model_path = path
    reference_model = model
    if config.get("domain_reference") == "functional-02":
        reference_model_path = LEGACY_EXPERIMENT / "model.keras"
        reference_model = tf.keras.models.load_model(
            reference_model_path, compile=False, safe_mode=True
        )
    gate = (
        CombinedGate(
            SemanticGate(MODEL_DIR / "clip-vit-base-patch32", gate_path),
            DomainGate(reference_path, reference_model_path, reference_model),
        )
        if gate_path.exists() and reference_path.exists()
        else None
    )
    return model, gate, calibration
