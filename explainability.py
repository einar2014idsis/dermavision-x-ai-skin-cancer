"""Influencia por oclusión superpuesta. No segmenta ni localiza enfermedad."""

from __future__ import annotations
import cv2
import numpy as np
from PIL import Image

METHOD = "occlusion-overlap-v3"
# Display threshold: 0.2 percentage points in raw model output, not clinical significance.
DISPLAY_EFFECT_FLOOR = 0.002


def occlusion_explanation(model, image, predicted_label, grid=14, display="signed"):
    if display not in ("signed", "magnitude-green-yellow"):
        raise ValueError("Representación de influencia no reconocida.")
    if (
        predicted_label not in ("benign", "malignant")
        or type(grid) is not int
        or not 1 <= grid <= 28
    ):
        raise ValueError(
            "La explicación requiere una clase binaria y una cuadrícula válida."
        )
    rgb = np.asarray(
        image.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR),
        dtype="float32",
    )

    def predict(batch):
        values = np.asarray(model(batch, training=False).numpy(), dtype=float).reshape(
            -1
        )
        if (
            len(values) != len(batch)
            or not np.isfinite(values).all()
            or ((values < 0) | (values > 1)).any()
        ):
            raise ValueError("Puntuaciones de oclusión inválidas.")
        return values

    baseline = float(predict(rgb[None])[0])
    patch = min(224, max(16, round(448 / grid)))
    starts = np.unique(np.linspace(0, 224 - patch, grid, dtype=int))
    fill = np.median(rgb.reshape(-1, 3), axis=0)
    blurred = cv2.GaussianBlur(rgb, (0, 0), sigmaX=max(4, patch / 5))
    boxes = [(y, y + patch, x, x + patch) for y in starts for x in starts]
    effects = []
    # Bound inference memory; do not create or evaluate all perturbations in one giant batch.
    for offset in range(0, len(boxes), 8):
        group = boxes[offset : offset + 8]
        variants = []
        for y1, y2, x1, x2 in group:
            for replacement in (fill, blurred[y1:y2, x1:x2]):
                altered = rgb.copy()
                altered[y1:y2, x1:x2] = replacement
                variants.append(altered)
        scores = predict(np.stack(variants)).reshape(-1, 2)
        signed = (
            baseline - scores if predicted_label == "malignant" else scores - baseline
        )
        # Average two perturbations to reduce sensitivity to a flat artificial patch.
        effects.extend(signed.mean(axis=1))
    total = np.zeros((224, 224), dtype="float64")
    coverage = np.zeros_like(total)
    axis = np.linspace(-1, 1, patch)
    weights = np.exp(-2 * (axis[:, None] ** 2 + axis[None, :] ** 2))
    for value, (y1, y2, x1, x2) in zip(effects, boxes):
        total[y1:y2, x1:x2] += value * weights
        coverage[y1:y2, x1:x2] += weights
    signed = (total / np.maximum(coverage, 1e-9)).astype("float32")
    signed = cv2.GaussianBlur(signed, (5, 5), sigmaX=1)
    peak = float(np.abs(signed).max())
    magnitude = np.abs(signed)
    strength = np.clip(
        (magnitude - DISPLAY_EFFECT_FLOOR) / max(peak - DISPLAY_EFFECT_FLOOR, 1e-9),
        0,
        1,
    )
    heat = np.clip(magnitude / max(peak, DISPLAY_EFFECT_FLOOR), 0, 1)
    # Orange supports the predicted class; blue opposes it. No rainbow over unchanged pixels.
    positive = np.array([249, 126, 48], dtype="float32")
    negative = np.array([62, 116, 232], dtype="float32")
    colors = np.where((signed >= 0)[..., None], positive, negative)
    alpha = (0.65 * strength)[..., None]
    if display == "magnitude-green-yellow":
        # Unsigned intensity from the same measured occlusions, never a lesion mask.
        green = np.array([42, 186, 106], dtype="float32")
        yellow = np.array([255, 230, 0], dtype="float32")
        # Monotonic display transfer: increase yellow visibility for measured
        # intermediate effects, preserving ranking, threshold and raw heat.
        palette_strength = np.sqrt(strength)
        colors = green + (yellow - green) * palette_strength[..., None]
        alpha = (0.80 * palette_strength)[..., None]
    overlay = Image.fromarray(
        np.uint8(np.clip(rgb * (1 - alpha) + colors * alpha, 0, 255))
    )
    overlay.info["explanation_stats"] = {
        "method": METHOD,
        "display_mode": display,
        "palette_version": "yellow-emphasis-v1" if display == "magnitude-green-yellow" else "signed-v1",
        "palette_gamma": 0.5 if display == "magnitude-green-yellow" else 1.0,
        "baseline_raw_score": baseline,
        "maximum_effect": peak,
        "display_effect_floor": DISPLAY_EFFECT_FLOOR,
        "informative": bool(peak > DISPLAY_EFFECT_FLOOR),
        "patch_pixels": patch,
        "evaluations": len(boxes) * 2,
        "supports_fraction": float((signed > DISPLAY_EFFECT_FLOOR).mean()),
        "opposes_fraction": float((signed < -DISPLAY_EFFECT_FLOOR).mean()),
    }
    return overlay, heat


def explanation_diagnostics(overlay, heat, mask=None):
    stats = dict(overlay.info.get("explanation_stats", {}))
    if mask is not None:
        region = (
            np.asarray(mask.convert("L").resize((224, 224), Image.Resampling.NEAREST))
            > 0
        )
        if region.any() and (~region).any():
            inside = float(heat[region].mean())
            outside = float(heat[~region].mean())
            stats.update(
                region_mean_influence=inside,
                background_mean_influence=outside,
                background_dominant=bool(
                    stats.get("informative") and outside > inside * 1.25
                ),
                region_focused=bool(
                    stats.get("informative") and inside > outside * 1.25
                ),
            )
    return stats


def with_reviewed_contour(overlay, mask):
    """Add the user-reviewed lesion boundary without changing the heat values.

    The green annotation is deliberately separate from the occlusion colours: it
    describes the region selected by the user, while yellow still describes model
    influence.  This avoids presenting an explanation as if it were a medical
    segmentation.
    """
    image = np.asarray(overlay.convert("RGB")).copy()
    if mask is None:
        return Image.fromarray(image)
    region = np.asarray(
        mask.convert("L").resize((image.shape[1], image.shape[0]), Image.Resampling.NEAREST)
    ) > 0
    if not region.any():
        return Image.fromarray(image)
    # Outline only: never add green inside the mask, since green encodes model
    # influence in the palette. An achromatic boundary cannot imply influence.
    wash = image.astype("float32")
    outline, _ = cv2.findContours(
        np.uint8(region), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(wash, outline, -1, (20, 20, 20), 3, lineType=cv2.LINE_AA)
    cv2.drawContours(wash, outline, -1, (255, 255, 255), 1, lineType=cv2.LINE_AA)
    return Image.fromarray(np.uint8(np.clip(wash, 0, 255)))


def focused_explanation_view(original, overlay, mask):
    """Show measured influence only inside the user-reviewed region.

    This is a presentation filter, not a new explanation or segmentation.  The
    stored/full map remains available so background dependence is never hidden.
    """
    base = np.asarray(original.convert("RGB").resize((224, 224))).copy()
    explained = np.asarray(overlay.convert("RGB").resize((224, 224))).copy()
    if mask is None:
        return Image.fromarray(explained)
    region = np.asarray(
        mask.convert("L").resize((224, 224), Image.Resampling.NEAREST)
    ) > 0
    if not region.any():
        return Image.fromarray(explained)
    # Desaturate the exterior so the user can distinguish a filtered view from
    # the complete model-influence map without mistaking it for segmentation.
    gray = np.uint8(
        np.clip(
            0.299 * base[..., 0] + 0.587 * base[..., 1] + 0.114 * base[..., 2],
            0,
            255,
        )
    )
    outside = np.stack([gray, gray, gray], axis=-1)
    result = outside
    result[region] = explained[region]
    contours, _ = cv2.findContours(
        np.uint8(region), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(result, contours, -1, (25, 132, 72), 2, lineType=cv2.LINE_AA)
    return Image.fromarray(result)


def influence_view(original, overlay, mask=None, opacity=1.0, contour=False):
    """Full measured map, with independent opacity and optional annotation."""
    opacity = float(opacity)
    if not np.isfinite(opacity):
        raise ValueError("La intensidad debe ser finita.")
    overlay = overlay.convert("RGB")
    base = original.convert("RGB").resize(overlay.size, Image.Resampling.BILINEAR)
    result = Image.blend(base, overlay, max(0.0, min(1.0, opacity)))
    return with_reviewed_contour(result, mask) if contour else result


def explanation_caption(stats):
    if not stats or stats.get("method") != METHOD:
        return "Explicación guardada con el método anterior. Recalcula para usar el mapa actualizado."
    if not stats.get("informative"):
        return "Sin señal suficiente para colorear: las oclusiones apenas modificaron la salida del modelo."
    if stats.get("display_mode") == "magnitude-green-yellow":
        message = (
            "Verde: menor intensidad de influencia. Amarillo: mayor intensidad de influencia. "
            "Sin color: señal insuficiente. La intensidad indica cuánto cambió la salida al ocultar una región; "
            "no distingue si apoya o contradice la clase. No mide cáncer ni delimita la lesión."
        )
        if stats.get("palette_version") == "yellow-emphasis-v1":
            message += " Escala visual realzada (no lineal) para hacer más visible la influencia intermedia; las mediciones no cambian."
    else:
        message = (
            "Naranja: región que apoya la clase mostrada. Azul: región que la contradice. "
            "Sin color: influencia pequeña. Intensidad relativa; no es probabilidad ni segmentación."
        )
    if stats.get("background_dominant"):
        message += " MAPA POCO ESPECÍFICO: la influencia media es mayor fuera del contorno. Revisa el encuadre y la respuesta del modelo a la piel o al fondo."
    elif stats.get("region_focused") is False:
        message += (
            " La influencia es dispersa: el mapa no delimita específicamente la lesión."
        )
    return message
