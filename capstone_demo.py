"""Controles sintéticos reproducibles; no fotografías de pacientes ni evidencia clínica."""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from longitudinal_analysis import compare_records
from longitudinal_store import LongitudinalStore

SCHEMA = "dermavision-synthetic-demo-v1"


def synthetic_capture(radius=45, angle=0, blurred=False):
    """Textura fija para observar alineación; el radio cambia solo en el control de cambio."""
    rng = np.random.default_rng(5)
    texture = rng.normal(0, 13, (400, 400, 1))
    rgb = np.uint8(np.clip(np.full((400, 400, 3), (185, 145, 120)) + texture, 0, 255))
    for _ in range(150):
        point = tuple(int(v) for v in rng.integers(18, 382, 2))
        cv2.circle(rgb, point, 2, (120, 90, 65), -1)
    mask = np.zeros((400, 400), "uint8")
    cv2.circle(mask, (200, 200), radius, 255, -1)
    rgb[mask > 0] = (85, 58, 40)
    if angle:
        matrix = cv2.getRotationMatrix2D((200, 200), angle, 1.0)
        rgb = cv2.warpAffine(rgb, matrix, (400, 400), borderMode=cv2.BORDER_REFLECT)
        mask = cv2.warpAffine(mask, matrix, (400, 400), flags=cv2.INTER_NEAREST)
    if blurred:
        rgb = cv2.GaussianBlur(rgb, (51, 51), 15)
    return Image.fromarray(rgb), Image.fromarray(mask)


def prepare_demo(root):
    """Idempotente: conserva el archivo demo al reabrir y nunca abre el archivo principal."""
    root = Path(root).resolve()
    manifest = root / "demo_manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError("La carpeta contiene otra versión de demostración; use una carpeta nueva.")
        # Reabrir no duplica ni restaura registros que el usuario haya eliminado.
        return data
    if root.exists() and any(root.iterdir()):
        raise ValueError("La carpeta ya contiene archivos. Use una carpeta vacía para la demostración.")
    store = LongitudinalStore(root)
    store.create_person(
        "DEMO-001", "Caso sintético · sin paciente",
        "Control técnico generado por código. Fechas ficticias; sin evaluación clínica.",
    )
    lesion = store.create_lesion("DEMO-001", "Control sintético", "Superficie simulada")
    cases = [
        ("2026-01-01", 45, 0, False, "Referencia sintética"),
        ("2026-02-01", 45, 8, False, "Mismo radio; giro sintético de 8 grados"),
        ("2026-03-01", 55, 0, False, "Radio sintético de 45 a 55 píxeles"),
        ("2026-04-01", 45, 0, True, "Desenfoque sintético deliberado"),
    ]
    ids = []
    for date, radius, angle, blurred, note in cases:
        image, mask = synthetic_capture(radius, angle, blurred)
        ids.append(store.add_record(
            lesion, date, image, mask,
            dict(mask_reviewed=True, synthetic=True, source=SCHEMA, note=note,
                 visit_notes=dict(observation=note + ". DATOS SINTÉTICOS; fecha ficticia.")),
        ))
    checks = []
    for kind, current in zip(("repeat_rotation", "synthetic_change", "blur_rejection"), ids[1:]):
        comparison = compare_records(store, ids[0], current)
        result = comparison["result"]
        checks.append(dict(
            control=kind, comparison_id=comparison["id"],
            comparable=result["comparable"], changes=result.get("changes", {}),
            warnings=result.get("warnings", []),
        ))
    data = dict(schema=SCHEMA, synthetic=True, lesion_id=lesion, record_ids=ids, checks=checks,
                notice="Controles técnicos sintéticos. No son pacientes ni validación clínica.")
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Carpeta vacía o demostración ya creada.")
    args = parser.parse_args()
    print(json.dumps(prepare_demo(args.output), ensure_ascii=False, indent=2))
