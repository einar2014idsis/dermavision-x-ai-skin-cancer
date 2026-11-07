"""Preparación de vistas: comparaciones reales y detalle de contornos alineados."""

from datetime import datetime
import math
import numpy as np
from PIL import Image


def comparison_summary(saved, records):
    labels = {r["id"]: r["label"] for r in records}
    points = []
    visual = stale = invalid = 0
    for row in saved:
        result = row["result"]
        if row.get("stale_dates"):
            stale += 1
            continue
        if result.get("mode") == "visual":
            visual += 1
            continue
        index = result.get("change_index")
        if not result.get("comparable") or index is None or not math.isfinite(index):
            invalid += 1
            continue
        try:
            a = datetime.fromisoformat(result["previous_date"])
            b = datetime.fromisoformat(result["current_date"])
        except (KeyError, ValueError):
            invalid += 1
            continue
        points.append(
            dict(
                value=index,
                date=b,
                previous_date=a,
                reference=result.get("previous_id"),
                target=result.get("current_id"),
                pair=labels.get(result.get("previous_id"), "A")
                + " → "
                + labels.get(result.get("current_id"), "B"),
            )
        )
    points.sort(key=lambda item: (item["date"], item["pair"]))
    return dict(
        points=points,
        visual=visual,
        stale=stale,
        invalid=invalid,
        common_reference=len({p["reference"] for p in points}) == 1,
    )


def aligned_detail(overlay, previous_mask, current_mask, matrix, margin=0.3):
    import cv2

    a = np.asarray(previous_mask.resize(overlay.size, Image.Resampling.NEAREST)) > 0
    b = (
        cv2.warpAffine(
            np.asarray(current_mask, dtype="uint8"),
            np.asarray(matrix, dtype=float),
            overlay.size,
            flags=cv2.INTER_NEAREST,
        )
        > 0
    )
    y, x = np.where(a | b)
    if not len(x):
        return overlay
    pad = max(16, int(max(x.max() - x.min() + 1, y.max() - y.min() + 1) * margin))
    box = (
        max(0, int(x.min()) - pad),
        max(0, int(y.min()) - pad),
        min(overlay.width, int(x.max()) + pad + 1),
        min(overlay.height, int(y.max()) + pad + 1),
    )
    return overlay.crop(box)
