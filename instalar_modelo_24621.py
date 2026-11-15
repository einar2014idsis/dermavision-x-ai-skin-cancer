"""Instala el modelo de 24.621 imágenes con los metadatos de Git."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from zipfile import ZipFile

from app_paths import MODEL_DIR, PROJECT_DIR


def install(package, runs=MODEL_DIR):
    published = PROJECT_DIR / "model_packages" / "dermavision-24621"
    metadata = json.loads((published / "artifact.json").read_text(encoding="utf-8"))
    runs.mkdir(parents=True, exist_ok=True)
    experiment = runs / metadata["experiment"]
    with tempfile.TemporaryDirectory(prefix=".model-install-", dir=runs) as temp:
        staging = Path(temp) / experiment.name
        staging.mkdir()
        with ZipFile(package) as archive:
            entry = archive.getinfo("model.keras")
            if entry.file_size != metadata["size_bytes"]:
                raise ValueError("El archivo Keras tiene un tamaño distinto del registrado.")
            with archive.open(entry) as source, (staging / "model.keras").open("wb") as dest:
                shutil.copyfileobj(source, dest)
        with (staging / "model.keras").open("rb") as model:
            digest = hashlib.file_digest(model, "sha256").hexdigest()
        if digest != metadata["sha256"]:
            raise ValueError("El SHA-256 del modelo no coincide con el registro de Git.")
        for name in ("config.json", "calibration.json", "metrics.json", "history.csv",
                     "manifest.csv", "test_predictions.csv", "artifact.json"):
            shutil.copyfile(published / name, staging / name)
        if experiment.exists():
            with (experiment / "model.keras").open("rb") as model:
                if hashlib.file_digest(model, "sha256").hexdigest() != digest:
                    raise FileExistsError(f"Ya existe otro modelo en {experiment}.")
            for name in ("config.json", "calibration.json", "metrics.json", "history.csv",
                         "manifest.csv", "test_predictions.csv", "artifact.json"):
                os.replace(staging / name, experiment / name)
        else:
            staging.rename(experiment)
        pointer_tmp = Path(temp) / "active_experiment.txt"
        pointer_tmp.write_text(experiment.name + "\n", encoding="ascii")
        os.replace(pointer_tmp, runs / "active_experiment.txt")
    return experiment


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="ZIP con el archivo Keras verificado")
    args = parser.parse_args()
    print("Modelo activo:", install(args.package))
