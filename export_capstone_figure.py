"""Exporta una figura de controles sintéticos, identificados como prueba técnica."""

import argparse
import json
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from capstone_demo import SCHEMA
from longitudinal_analysis import mask_overlay
from longitudinal_store import LongitudinalStore


def export_figure(root, destination):
    root, destination = Path(root), Path(destination)
    data = json.loads((root / "demo_manifest.json").read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA or data.get("synthetic") is not True:
        raise ValueError("Solo se exportan los controles sintéticos identificados.")
    if destination.exists():
        raise FileExistsError("Use otro nombre para conservar la figura anterior.")
    store = LongitudinalStore(root)
    comparisons = {row["id"]: row for row in store.comparisons(data["lesion_id"])}
    results = [comparisons[check["comparison_id"]]["result"] for check in data["checks"]]
    figure = Figure(figsize=(12, 7), facecolor="#f5f6fa")
    FigureCanvasAgg(figure)
    figure.suptitle("DermaVision-X · controles de funcionamiento", fontsize=19, fontweight="bold", y=0.97)
    figure.text(0.5, 0.905, "IMÁGENES SINTÉTICAS · Fechas ficticias · Sin pacientes ni validación clínica",
                ha="center", fontsize=11, color="#8a5215")
    titles = ["A · Referencia", "B · Mismo radio + giro de 8°", "C · Radio de 45 a 55 px", "D · Desenfoque deliberado"]
    for index, (identifier, title) in enumerate(zip(data["record_ids"], titles)):
        axis = figure.add_axes((0.035 + index * 0.243, 0.33, 0.225, 0.47))
        image, mask = store.load_images(store.record(identifier))
        axis.imshow(mask_overlay(image, mask))
        axis.set_title(title, fontsize=10, fontweight="bold", pad=10)
        axis.axis("off")
        if index == 0:
            caption = "Contorno conocido\nEntrada de referencia"
        else:
            result = results[index - 1]
            caption = (
                "Controles superados\nÁrea aparente: " + f"{result['changes']['area']:+.2f} %"
                if result["comparable"] else "Calidad insuficiente\nSin medición de cambio"
            )
        figure.text(0.147 + index * 0.243, 0.28, caption, ha="center", va="top", fontsize=11,
                    color="#202536", linespacing=1.7)
    figure.text(0.055, 0.12,
                "B, C y D se comparan con A. El contorno verde se genera por código.\n"
                "El control C tiene un cambio teórico de área de +49,38 %; la rasterización introduce diferencias.\n"
                "Estos casos verifican comportamiento con entradas conocidas; no estiman precisión en fotografías reales.",
                fontsize=10, color="#53596b", linespacing=1.6)
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(destination, dpi=160, facecolor=figure.get_facecolor())
    return destination.resolve()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(export_figure(args.store, args.output))
