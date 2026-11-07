"""Rutas del programa independientes del directorio desde el que se ejecuta."""

from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SOURCE_DIR.parent if SOURCE_DIR.name == "src" else SOURCE_DIR
MODEL_DIR = PROJECT_DIR / ("modelos" if SOURCE_DIR.name == "src" else "runs")
DATA_DIR = PROJECT_DIR / ("datos" if SOURCE_DIR.name == "src" else "data")
