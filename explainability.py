"""Influencia por oclusión superpuesta. No segmenta ni localiza enfermedad."""

from __future__ import annotations
import cv2
import numpy as np
from PIL import Image
from classifier_input import INPUT_SIZE, classifier_pixels

METHOD = "occlusion-overlap-v3"
# Display threshold: 0.2 percentage points in raw model output, not clinical significance.
DISPLAY_EFFECT_FLOOR = 0.002


def field_statistics(values):
    quantiles = np.percentile(values, [5, 25, 50, 75, 95])
    return dict(min=float(values.min()), max=float(values.max()),
                mean=float(values.mean()), percentiles=quantiles.tolist())


def render_field(values, photo_size, *, signed=False):
    ratio = min(1, 768 / max(photo_size))
    size = tuple(max(1, round(side * ratio)) for side in photo_size)
    field = np.asarray(Image.fromarray(values.astype("float32")).resize(size, Image.Resampling.BILINEAR))
    if signed:
        neutral = np.array([240, 243, 246])
        colors = np.where(field[..., None] < 0, [38, 105, 190], [207, 60, 28])
        rgb = neutral + np.abs(field[..., None]) * (colors - neutral)
    else:
        colored = cv2.applyColorMap(np.uint8(np.clip(field, 0, 1) * 255), cv2.COLORMAP_TURBO)
        rgb = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
    return Image.fromarray(np.uint8(rgb))


def occlusion_explanation(model, image, predicted_label, grid=14, display="signed"):
    if display not in ("signed", "magnitude-green-yellow", "magnitude-turbo"):
        raise ValueError("Representación de influencia no reconocida.")
    if (
        predicted_label not in ("benign", "malignant")
        or type(grid) is not int
        or not 1 <= grid <= 28
    ):
        raise ValueError(
            "La explicación requiere una clase binaria y una cuadrícula válida."
        )
    rgb = classifier_pixels(image)

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
    absolute_effects = []
    occluded_scores = []
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
        occluded_scores.extend(scores.ravel())
        signed = (
            baseline - scores if predicted_label == "malignant" else scores - baseline
        )
        # Average two perturbations to reduce sensitivity to a flat artificial patch.
        effects.extend(signed.mean(axis=1))
        absolute_effects.extend(np.abs(signed).mean(axis=1))
    total = np.zeros((224, 224), dtype="float64")
    coverage = np.zeros_like(total)
    magnitude_sum = np.zeros_like(total)
    axis = np.linspace(-1, 1, patch)
    weights = np.exp(-2 * (axis[:, None] ** 2 + axis[None, :] ** 2))
    for value, absolute, (y1, y2, x1, x2) in zip(effects, absolute_effects, boxes):
        total[y1:y2, x1:x2] += value * weights
        magnitude_sum[y1:y2, x1:x2] += absolute * weights
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
    if display == "magnitude-turbo":
        # Accumulate magnitude independently so opposite signs cannot make dark seams.
        magnitude = (magnitude_sum / coverage).astype("float32")
        magnitude = cv2.GaussianBlur(magnitude, (5, 5), sigmaX=1)
        peak = float(magnitude.max())
        scale = max(peak, DISPLAY_EFFECT_FLOOR)
        heat = magnitude / scale
        overlay = render_field(heat, image.size)
        overlay.info["signed_map"] = render_field(signed / scale, image.size, signed=True)
    else:
        overlay = Image.fromarray(np.uint8(np.clip(rgb * (1 - alpha) + colors * alpha, 0, 255)))
    palettes = {
        "signed": ("signed-v1", 1.0),
        "magnitude-green-yellow": ("yellow-emphasis-v1", 0.5),
        "magnitude-turbo": ("turbo-v1", 1.0),
    }
    palette_version, palette_gamma = palettes[display]
    overlay.info["explanation_stats"] = {
        "method": METHOD,
        "display_mode": display,
        "palette_version": palette_version,
        "palette_gamma": palette_gamma,
        "baseline_raw_score": baseline,
        "maximum_effect": peak,
        "display_effect_floor": DISPLAY_EFFECT_FLOOR,
        "informative": bool(peak > DISPLAY_EFFECT_FLOOR),
        "patch_pixels": patch,
        "evaluations": len(boxes) * 2,
        "supports_fraction": float((signed > DISPLAY_EFFECT_FLOOR).mean()),
        "opposes_fraction": float((signed < -DISPLAY_EFFECT_FLOOR).mean()),
        "target_class": predicted_label,
        "target_baseline": baseline if predicted_label == "malignant" else 1 - baseline,
        "occluded_target_scores": field_statistics(
            np.asarray(occluded_scores) if predicted_label == "malignant" else 1 - np.asarray(occluded_scores)
        ),
        "window_effects": field_statistics(np.asarray(effects)),
        "signed_field": field_statistics(signed),
        "magnitude_field": field_statistics(magnitude),
        "stride_pixels": np.diff(starts).tolist(),
    }
    return overlay, heat


def gradcam_explanation(model, image, predicted_label):
    import tensorflow as tf

    pool = next((layer for layer in model.layers
                 if isinstance(layer, tf.keras.layers.GlobalAveragePooling2D)), None)
    if pool is None or len(pool.input.shape) != 4:
        return None
    probe = tf.keras.Model(model.inputs, [pool.input, model.output])
    batch = tf.convert_to_tensor(classifier_pixels(image)[None])
    with tf.GradientTape() as tape:
        tape.watch(batch)
        spatial, score = probe([batch], training=False)
        target = score[0, 0] if predicted_label == "malignant" else 1 - score[0, 0]
    gradients = tape.gradient(target, spatial)
    if gradients is None:
        return None
    weights = tf.reduce_mean(gradients, axis=(1, 2))
    field = tf.reduce_sum(spatial * weights[:, None, None, :], axis=-1)[0].numpy()
    positive = np.maximum(field, 0)
    peak = float(positive.max())
    if not np.isfinite(field).all() or peak <= 0:
        return None
    # Render once from the native convolutional grid to the original framing.
    return render_field(positive / peak, image.size), {
        "target_class": predicted_label, "target_baseline": float(target.numpy()),
        "grid": list(field.shape), "field": field_statistics(field),
    }


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
    if stats.get("display_mode") == "magnitude-turbo":
        message = "Colores fríos: menor influencia. Colores cálidos: mayor influencia al ocultar zonas de la foto."
    elif stats.get("display_mode") == "magnitude-green-yellow":
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
