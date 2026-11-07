"""Medición longitudinal exploratoria, sin entrenamiento temporal ni riesgo clínico."""

import hashlib
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from capture_guide import CaptureGuide

VERSION = "longitudinal-v1"
INDEX_SCALES = dict(
    area=50.0, shape=1.0, asymmetry=0.3, border=0.5, color=20.0, texture=0.5
)


def prepare_image(image):
    return ImageOps.exif_transpose(image).convert("RGB")


def suggest_mask(image):
    """Propuesta por contraste con la periferia. Siempre requiere revisión humana."""
    image = prepare_image(image)
    small = ImageOps.contain(image, (512, 512))
    rgb = np.asarray(small)
    lab = cv2.cvtColor(rgb.astype("float32") / 255, cv2.COLOR_RGB2LAB)
    h, w = lab.shape[:2]
    rim = np.ones((h, w), bool)
    rim[h // 8 : -h // 8, w // 8 : -w // 8] = False
    background = np.median(lab[rim], axis=0)
    distance = np.linalg.norm(lab - background, axis=2)
    scaled = np.uint8(np.clip(distance * 255 / max(float(distance.max()), 1), 0, 255))
    _, binary = cv2.threshold(
        cv2.GaussianBlur(scaled, (7, 7), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    valid = [c for c in contours if 25 < cv2.contourArea(c) < h * w * 0.8]
    if not valid:
        raise ValueError(
            "No se encontró un contorno útil. Dibújelo con clics alrededor de la lesión."
        )

    def ranking(contour):
        x, y, cw, ch = cv2.boundingRect(contour)
        return cv2.contourArea(contour) / (
            1 + 4 * ((x + cw / 2 - w / 2) ** 2 + (y + ch / 2 - h / 2) ** 2) / (w * h)
        )

    mask = np.zeros((h, w), "uint8")
    cv2.drawContours(mask, [max(valid, key=ranking)], -1, 255, -1)
    return Image.fromarray(mask).resize(image.size, Image.Resampling.NEAREST)


def mask_overlay(image, mask):
    rgb = np.asarray(image.convert("RGB")).copy()
    contours, _ = cv2.findContours(
        np.uint8(np.asarray(mask) > 0), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(rgb, contours, -1, (30, 245, 180), max(1, min(image.size) // 180))
    return Image.fromarray(rgb)


def normalized(image, mask):
    photo = ImageOps.contain(prepare_image(image), (640, 640))
    return (
        np.asarray(photo),
        np.asarray(mask.resize(photo.size, Image.Resampling.NEAREST)) > 0,
    )


def align(previous, current, previous_mask, current_mask):
    """Transformación de similitud estimada en piel exterior, no en el borde de lesión.

    No usa deformaciones elásticas que puedan eliminar crecimiento real.
    La aceptación es técnica/heurística; no certifica identidad ni escala física.
    """
    gray0, gray1 = [cv2.cvtColor(im, cv2.COLOR_RGB2GRAY) for im in (previous, current)]
    masks = []
    for mask in (previous_mask, current_mask):
        outside = 1 - cv2.dilate(mask.astype("uint8"), np.ones((21, 21), "uint8"))
        outside[:12] = outside[-12:] = 0
        outside[:, :12] = outside[:, -12:] = 0
        masks.append(outside * 255)
    orb = cv2.ORB_create(nfeatures=2500, fastThreshold=7, edgeThreshold=15)
    kp0, d0 = orb.detectAndCompute(gray0, masks[0])
    kp1, d1 = orb.detectAndCompute(gray1, masks[1])
    report = dict(method="ORB skin + RANSAC similarity", accepted=False, matches=0)
    if d0 is None or d1 is None or min(len(d0), len(d1)) < 8:
        return None, report
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d0, k=2)
    good = [
        pair[0]
        for pair in matches
        if len(pair) == 2 and pair[0].distance < 0.72 * pair[1].distance
    ]
    # Evitar que varias correspondencias reutilicen el mismo punto.
    unique = {}
    for match in sorted(good, key=lambda m: m.distance):
        unique.setdefault(match.trainIdx, match)
    good = list(unique.values())
    report["matches"] = len(good)
    if len(good) < 8:
        return None, report
    source = np.float32([kp1[m.queryIdx].pt for m in good])
    target = np.float32([kp0[m.trainIdx].pt for m in good])
    cv2.setRNGSeed(2026)
    matrix, inliers = cv2.estimateAffinePartial2D(
        source,
        target,
        method=cv2.RANSAC,
        ransacReprojThreshold=3,
        maxIters=3000,
        confidence=0.99,
    )
    if matrix is None or inliers is None or not np.isfinite(matrix).all():
        return None, report
    selected = inliers.ravel().astype(bool)
    projected = cv2.transform(source[None], matrix)[0]
    error = float(
        np.median(np.linalg.norm(projected[selected] - target[selected], axis=1))
    )
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    spread = cv2.contourArea(cv2.convexHull(target[selected])) / (
        previous.shape[0] * previous.shape[1]
    )
    accepted = bool(
        selected.sum() >= 8
        and selected.mean() >= 0.5
        and error <= 2.5
        and 0.5 <= scale <= 2
        and spread >= 0.06
    )
    report.update(
        inliers=int(selected.sum()),
        inlier_fraction=float(selected.mean()),
        median_error_px=error,
        scale=scale,
        skin_coverage=float(spread),
        matrix=matrix.tolist(),
        accepted=accepted,
    )
    return (matrix if accepted else None), report


def shape_mask(mask):
    y, x = np.where(mask)
    cropped = Image.fromarray(
        mask[min(y) : max(y) + 1, min(x) : max(x) + 1].astype("uint8") * 255
    )
    return (
        np.asarray(ImageOps.pad(cropped, (128, 128), method=Image.Resampling.NEAREST))
        > 0
    )


def features(rgb, mask):
    mask = mask.astype(bool)
    area = int(mask.sum())
    if area < 25:
        raise ValueError("Contorno demasiado pequeño para medir.")
    contours, _ = cv2.findContours(
        mask.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    perimeter = sum(cv2.arcLength(c, True) for c in contours)
    shape = shape_mask(mask)
    # Buscar eje de menor asimetría para reducir dependencia de orientación.
    asymmetries = []
    for angle in range(0, 180, 15):
        rotation = cv2.getRotationMatrix2D((63.5, 63.5), angle, 0.70)
        turned = (
            cv2.warpAffine(
                shape.astype("uint8"), rotation, (128, 128), flags=cv2.INTER_NEAREST
            )
            > 0
        )
        asymmetries.append(
            (
                np.logical_xor(turned, np.flipud(turned)).sum()
                + np.logical_xor(turned, np.fliplr(turned)).sum()
            )
            / max(4 * turned.sum(), 1)
        )
    lab = cv2.cvtColor(rgb.astype("float32") / 255, cv2.COLOR_RGB2LAB)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    interior = cv2.erode(mask.astype("uint8"), np.ones((3, 3), "uint8")).astype(bool)
    interior[[0, -1], :] = False
    interior[:, [0, -1]] = False
    lbp = np.zeros(gray.shape, "uint8")
    for bit, (dy, dx) in enumerate(
        [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]
    ):
        lbp |= (np.roll(np.roll(gray, dy, 0), dx, 1) >= gray).astype("uint8") << bit
    hist = np.histogram(lbp[interior], bins=16, range=(0, 256))[0].astype(float)
    hist /= max(hist.sum(), 1)
    return dict(
        area_px=area,
        asymmetry=float(min(asymmetries)),
        border_irregularity=float(perimeter**2 / (4 * np.pi * area)),
        color_lab_mean=lab[mask].mean(axis=0).astype(float).tolist(),
        color_lab_std=lab[mask].std(axis=0).astype(float).tolist(),
        texture_lbp_hist=hist.tolist(),
    )


def classify(image, model=None, gate=None, calibration=None):
    assessment = CaptureGuide().evaluate(image, static=True)
    quality = dict(
        checks=[bool(v) for v in assessment.checks[:3]],
        brightness=assessment.brightness,
        sharpness=assessment.sharpness,
        message=assessment.message,
    )
    if not all(assessment.checks[:3]):
        return dict(state="quality_failed", score=None, quality=quality)
    if model is None or gate is None:
        return dict(state="unavailable", score=None, quality=quality)
    decision = gate.assess(image)
    if decision.state != "accepted":
        return dict(
            state=decision.state,
            score=None,
            reason="domain",
            message=decision.message,
            quality=quality,
        )
    data = np.asarray(
        image.resize((224, 224), Image.Resampling.BILINEAR), dtype="float32"
    )[None]
    raw_score = float(model(data, training=False).numpy()[0, 0])
    if not np.isfinite(raw_score) or not 0 <= raw_score <= 1:
        raise ValueError("Salida del clasificador inválida.")
    score = calibration.apply(raw_score) if calibration is not None else raw_score
    label = (
        calibration.decision(score)
        if calibration is not None
        else ("malignant" if score >= 0.5 else "benign")
    )
    if label == "uncertain":
        return dict(
            state="uncertain",
            score=score,
            raw_score=raw_score,
            reason="score_uncertainty",
            message="Puntuación cercana al umbral; no se emite clase.",
            quality=quality,
        )
    return dict(
        state="accepted", score=score, raw_score=raw_score, label=label, quality=quality
    )


def classification_text(classification):
    state = classification.get("state", "unavailable")
    labels = dict(benign="benigna", malignant="maligna")
    states = dict(
        uncertain="No concluyente",
        rejected="Imagen rechazada: contenido ajeno a lesiones",
        quality_failed="Calidad insuficiente",
        unavailable="Modelo o filtro no disponible",
    )
    title = (
        "Clasificación experimental: "
        + labels.get(classification.get("label"), "sin clase")
        if state == "accepted"
        else states.get(state, state)
    )
    lines = [title]
    score = classification.get("score")
    if score is not None and state == "accepted":
        lines.append(
            f"Puntuaciones del modelo: benigna {(1-score)*100:.1f} % · maligna {score*100:.1f} %."
        )
    if state == "uncertain":
        lines.append(
            "El modelo se abstiene de asignar una clase por incertidumbre; no se muestran puntuaciones."
        )
    if classification.get("message"):
        lines.append(classification["message"])
    if classification.get("explanation_error"):
        lines.append(
            "Explicación visual no disponible: " + classification["explanation_error"]
        )
    lines.append("Resultado experimental; no constituye un diagnóstico médico.")
    return "\n".join(lines)


def classification_summary(classification):
    """Plain wording for the recorded model output, never a clinical probability."""
    state = classification.get("state", "unavailable")
    score = classification.get("score")
    if state == "accepted":
        malignant = classification.get("label") == "malignant"
        label = "maligno" if malignant else "benigno"
        body = f"El modelo clasificó esta fotografía como un patrón {label} (experimental)."
        if isinstance(score, (int, float)) and np.isfinite(score):
            body += f" Puntuación maligna: {score*100:.1f} %; puntuación benigna: {(1-score)*100:.1f} %."
    elif state == "uncertain":
        body = "El resultado no es concluyente: el modelo se abstiene de asignar una clase con los criterios del sistema."
    elif state == "quality_failed":
        body = "La fotografía no cumple los requisitos de calidad. Revisa el enfoque y la iluminación o utiliza otra foto."
    elif state == "rejected":
        body = "La fotografía no pasó la comprobación de contenido. No se ha emitido una clasificación."
    else:
        body = "Aún no hay un modelo listo para clasificar esta fotografía."
    if state == "accepted":
        body += " Estos porcentajes son puntuaciones del modelo, no la probabilidad de tener cáncer. El resultado no es un diagnóstico médico."
    elif state == "uncertain":
        body += " No se muestran puntuaciones porque podrían interpretarse como una decisión. No es un diagnóstico médico."
    return body


def classify_record(
    store,
    identifier,
    model=None,
    gate=None,
    calibration=None,
    model_path=None,
    explain=True,
):
    """Analyze a saved visit; reuse its verified snapshot if models are unavailable."""
    record = store.record(identifier)
    image, mask = store.load_images(record)
    cached = record["metadata"].get("classification")
    if (model is None or gate is None) and cached:
        if (
            cached.get("image_sha256") == record["sha256"]
            and cached.get("mask_sha256") == record["mask_sha256"]
        ):
            return cached
    classification = classify(image, model, gate, calibration)
    # Do not replace a previous completed analysis with an unavailable model.
    if classification["state"] == "unavailable":
        return classification
    classification["model_sha256"] = (
        hashlib.sha256(Path(model_path).read_bytes()).hexdigest()
        if model_path is not None and Path(model_path).is_file()
        else None
    )
    if calibration is not None:
        classification["calibration"] = dict(
            slope=calibration.slope,
            intercept=calibration.intercept,
            threshold=calibration.threshold,
            uncertain_low=calibration.uncertain_low,
            uncertain_high=calibration.uncertain_high,
            source=calibration.source,
        )
    if (
        not explain
        and cached
        and cached.get("explanation")
        and all(
            cached.get(key) == classification.get(key)
            for key in ("state", "label", "raw_score", "model_sha256", "calibration")
        )
    ):
        classification["explanation"] = cached["explanation"]
        if cached.get("explanation_diagnostics"):
            classification["explanation_diagnostics"] = cached[
                "explanation_diagnostics"
            ]
    overlay = None
    if explain and classification["state"] == "accepted":
        try:
            from explainability import occlusion_explanation, explanation_diagnostics

            overlay, heat = occlusion_explanation(
                model, image, classification["label"], display="magnitude-green-yellow"
            )
            classification["explanation_diagnostics"] = explanation_diagnostics(
                overlay, heat, mask
            )
        except Exception as exc:
            classification["explanation_error"] = str(exc)
    return store.save_record_analysis(identifier, classification, overlay)


def visual_descriptors(previous, current, m0, m1, feature_pair=None):
    f0, f1 = feature_pair or (features(previous, m0), features(current, m1))
    s0, s1 = shape_mask(m0), shape_mask(m1)
    return dict(
        area_coverage_pp=float(100 * (m1.mean() - m0.mean())),
        shape=float(1 - (s0 & s1).sum() / max((s0 | s1).sum(), 1)),
        asymmetry=float(f1["asymmetry"] - f0["asymmetry"]),
        border=float(f1["border_irregularity"] - f0["border_irregularity"]),
        color=float(
            np.linalg.norm(np.array(f1["color_lab_mean"]) - f0["color_lab_mean"])
        ),
        texture=float(
            np.abs(np.array(f1["texture_lbp_hist"]) - f0["texture_lbp_hist"]).sum() / 2
        ),
        method="independent marked-region descriptors; no spatial or color alignment",
        warning="Diferencias fotográficas sensibles al encuadre, iluminación y contorno; no demuestran evolución de la lesión.",
    )


def compare_visual_images(photo0, photo1, mask0, mask1, reviewed=True):
    if not reviewed:
        raise ValueError("Revise los contornos antes de comparar visualmente.")
    previous, m0 = normalized(photo0, mask0)
    current, m1 = normalized(photo1, mask1)
    for mask in (m0, m1):
        if mask.sum() < 25 or mask.mean() > 0.85:
            raise ValueError(
                "Seleccione un contorno válido que deje espacio alrededor de la región."
            )
    f0, f1 = features(previous, m0), features(current, m1)
    f0["area_coverage_percent"] = float(m0.mean() * 100)
    f1["area_coverage_percent"] = float(m1.mean() * 100)
    differences = visual_descriptors(previous, current, m0, m1, (f0, f1))
    # Coverage is intentionally excluded: crop and distance determine its value.
    components = {
        key: float(min(abs(differences[key]) / INDEX_SCALES[key], 1))
        for key in ("shape", "asymmetry", "border", "color", "texture")
    }
    index = float(100 * np.mean(list(components.values())))
    a, b = shape_mask(m0), shape_mask(m1)
    map_rgb = np.full((128, 128, 3), 30, dtype="uint8")
    map_rgb[a & b] = (225, 225, 225)
    map_rgb[a & ~b] = (0, 220, 220)
    map_rgb[b & ~a] = (255, 170, 0)
    overlay = Image.fromarray(map_rgb).resize((384, 384), Image.Resampling.NEAREST)
    result = dict(
        schema=VERSION,
        mode="visual",
        visual_available=True,
        comparable=False,
        change_index=None,
        change_level="Comparación visual",
        visual_index=index,
        visual_level="Baja" if index < 10 else "Moderada" if index < 30 else "Alta",
        visual_components=components,
        visual_differences=differences,
        features_previous=f0,
        features_current=f1,
        parameters=dict(
            index_scales={key: INDEX_SCALES[key] for key in components},
            index_formula="100 * mean(min(abs(descriptor difference) / scale, 1))",
            excluded="area coverage; dates; deep embeddings",
            silhouette_size=[128, 128],
        ),
        warnings=[
            differences["warning"],
            "Índice visual heurístico de 0 a 100, sin validación clínica. No expresa malignidad ni crecimiento.",
            "Mapa de siluetas normalizadas: gris=zona común, cian=solo imagen A, naranja=solo imagen B.",
        ],
        model_b_trained=False,
        analysis_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    return result, Image.fromarray(current), overlay


def compare_images(
    previous_image,
    current_image,
    previous_mask,
    current_mask,
    previous_classification=None,
    current_classification=None,
    extractor=None,
    model_sha256=None,
    reviewed=True,
):
    previous, m0 = normalized(previous_image, previous_mask)
    current, m1 = normalized(current_image, current_mask)
    result = dict(
        schema=VERSION,
        comparable=False,
        change_index=None,
        change_level="No evaluable",
        analysis_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        warnings=[],
        current_classification=current_classification
        or dict(state="unavailable", score=None),
        previous_classification=previous_classification
        or dict(state="unavailable", score=None),
        model_sha256=model_sha256,
        opencv_version=cv2.__version__,
        parameters=dict(index_scales=INDEX_SCALES, levels=[10, 30], size_limit=640),
        model_b_trained=False,
    )
    overlay = Image.fromarray(previous)
    if not reviewed:
        result["warnings"].append("Los contornos requieren revisión.")
        return result, Image.fromarray(current), overlay
    # Independiente de la clasificación: comparar también es posible sin modelo,
    # pero nunca debe omitir los controles técnicos de ambas fotografías originales.
    result["capture_quality"] = []
    for photo, label in ((previous_image, "anterior"), (current_image, "actual")):
        assessment = CaptureGuide().evaluate(prepare_image(photo), static=True)
        result["capture_quality"].append(dict(
            photo=label, accepted=bool(all(assessment.checks[:3])),
            brightness=assessment.brightness, sharpness=assessment.sharpness,
            resolution_ok=bool(assessment.checks[0]),
            lighting_ok=bool(assessment.checks[1]), focus_ok=bool(assessment.checks[2]),
            message=assessment.message,
        ))
        if not all(assessment.checks[:3]):
            result["warnings"].append(f"Foto {label}: {assessment.message}")
            return result, Image.fromarray(current), overlay
    for mask in (m0, m1):
        if (
            mask.sum() < 25
            or mask.mean() > 0.85
            or mask[0].any()
            or mask[-1].any()
            or mask[:, 0].any()
            or mask[:, -1].any()
        ):
            result["warnings"].append(
                "El contorno es insuficiente o toca el borde; incluya piel alrededor."
            )
            return result, Image.fromarray(current), overlay
    for classification in (previous_classification, current_classification):
        if classification:
            blocked = classification.get("state") in ("rejected", "quality_failed")
            blocked |= (
                classification.get("state") == "uncertain"
                and classification.get("reason") != "score_uncertainty"
            )
            if blocked:
                result["warnings"].append(
                    "Alguna foto no superó los controles de calidad o contenido."
                )
                return result, Image.fromarray(current), overlay
            if classification.get("reason") == "score_uncertainty":
                result["warnings"].append(
                    "Clasificación no concluyente: se describen cambios sin asignar una clase binaria."
                )
    result["visual_differences"] = visual_descriptors(previous, current, m0, m1)
    matrix, report = align(previous, current, m0, m1)
    result["registration"] = report
    if matrix is None:
        result["warnings"].append(
            "No se encontró suficiente correspondencia en la piel alrededor. No se cuantifica el cambio."
        )
        return result, Image.fromarray(current), overlay
    h, w = previous.shape[:2]
    aligned = cv2.warpAffine(current, matrix, (w, h))
    aligned_mask = (
        cv2.warpAffine(m1.astype("uint8"), matrix, (w, h), flags=cv2.INTER_NEAREST) > 0
    )
    valid = (
        cv2.warpAffine(
            np.ones(m1.shape, "uint8"), matrix, (w, h), flags=cv2.INTER_NEAREST
        )
        > 0
    )
    overlap = float(valid.mean())
    retained = float(aligned_mask.sum() / max(m1.sum() * report["scale"] ** 2, 1))
    result["registration"].update(overlap=overlap, lesion_retained=retained)
    skin = valid & ~(
        cv2.dilate((m0 | aligned_mask).astype("uint8"), np.ones((21, 21), "uint8")) > 0
    )
    result["registration"]["framing_accepted"] = bool(
        overlap >= 0.65
        and retained >= 0.95
        and np.mean(valid[m0]) >= 0.99
        and skin.sum() >= 1000
    )
    if not result["registration"]["framing_accepted"]:
        result["warnings"].append(
            "Solapamiento insuficiente o lesión cortada tras alinear."
        )
        return result, Image.fromarray(aligned), overlay
    lab0 = cv2.cvtColor(previous.astype("float32") / 255, cv2.COLOR_RGB2LAB)
    lab1 = cv2.cvtColor(aligned.astype("float32") / 255, cv2.COLOR_RGB2LAB)
    offset = np.median(lab0[skin] - lab1[skin], axis=0)
    residual = float(
        np.median(np.linalg.norm(lab0[skin] - (lab1[skin] + offset), axis=1))
    )
    result["color_normalization"] = dict(
        method="median LAB offset in matched surrounding skin",
        offset=offset.tolist(),
        residual_delta_e=residual,
        accepted=bool(np.linalg.norm(offset) <= 25 and residual <= 18),
    )
    if not result["color_normalization"]["accepted"]:
        result["warnings"].append(
            "Diferencias de iluminación/color demasiado grandes para comparar de forma fiable."
        )
        return result, Image.fromarray(aligned), overlay
    adjusted_lab = lab1 + offset
    adjusted_lab[:, :, 0] = np.clip(adjusted_lab[:, :, 0], 0, 100)
    # Evitar diferencias artificiales por RGB→LAB→RGB cuando no se necesita corrección.
    adjusted = (
        aligned.copy()
        if np.max(np.abs(offset)) < 1e-6
        else np.uint8(
            np.clip(
                np.rint(cv2.cvtColor(adjusted_lab, cv2.COLOR_LAB2RGB) * 255), 0, 255
            )
        )
    )
    f0, f1 = features(previous, m0), features(adjusted, aligned_mask)
    s0, s1 = shape_mask(m0), shape_mask(aligned_mask)
    raw = dict(
        area=100 * (f1["area_px"] / f0["area_px"] - 1),
        shape=float(1 - (s0 & s1).sum() / max((s0 | s1).sum(), 1)),
        asymmetry=f1["asymmetry"] - f0["asymmetry"],
        border=f1["border_irregularity"] - f0["border_irregularity"],
        color=float(
            np.linalg.norm(np.array(f1["color_lab_mean"]) - f0["color_lab_mean"])
        ),
        texture=float(
            np.abs(np.array(f1["texture_lbp_hist"]) - f0["texture_lbp_hist"]).sum() / 2
        ),
    )
    components = {
        name: float(min(abs(value) / INDEX_SCALES[name], 1))
        for name, value in raw.items()
    }
    # Mantener la misma fórmula aunque MobileNet no esté disponible.
    index = float(100 * np.mean(list(components.values())))
    result.update(
        comparable=True,
        features_previous=f0,
        features_current=f1,
        changes=raw,
        index_components=components,
        change_index=index,
        change_level="Bajo" if index < 10 else "Moderado" if index < 30 else "Alto",
        deep_cosine_distance=None,
    )
    if extractor is not None:
        try:
            arrays = np.stack(
                [
                    np.asarray(
                        Image.fromarray(im).resize(
                            (224, 224), Image.Resampling.BILINEAR
                        ),
                        dtype="float32",
                    )
                    for im in (previous, adjusted)
                ]
            )
            vectors = np.asarray(extractor(arrays, training=False).numpy(), dtype=float)
            norms = np.linalg.norm(vectors, axis=1)
            if (
                vectors.shape[0] != 2
                or not np.isfinite(vectors).all()
                or (norms <= 1e-12).any()
            ):
                raise ValueError("Vectores inválidos.")
            result["deep_cosine_distance"] = float(
                np.clip(
                    1 - np.dot(vectors[0], vectors[1]) / (norms[0] * norms[1]), 0, 2
                )
            )
            result["embeddings"] = vectors.tolist()
        except Exception as exc:
            result["warnings"].append(
                "Características MobileNet no disponibles: " + str(exc)
            )
    else:
        result["warnings"].append(
            "Comparación sin características profundas: el modelo no está cargado."
        )
    result["warnings"].append(
        "Índice descriptivo heurístico de 0 a 100; umbrales no validados. No expresa malignidad ni crecimiento en milímetros."
    )
    difference = np.linalg.norm(lab0 - adjusted_lab, axis=2)
    heat = cv2.applyColorMap(
        np.uint8(np.clip(difference / 30 * 255, 0, 255)), cv2.COLORMAP_TURBO
    )
    heat = cv2.cvtColor(heat, cv2.COLOR_BGR2RGB)
    visual = previous.copy()
    region = (m0 | aligned_mask) & valid
    visual[region] = (0.45 * previous[region] + 0.55 * heat[region]).astype("uint8")
    for mask, color in [(m0, (0, 255, 220)), (aligned_mask, (255, 170, 0))]:
        contours, _ = cv2.findContours(
            mask.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(visual, contours, -1, color, 2)
    return result, Image.fromarray(adjusted), Image.fromarray(visual)


def compare_records(
    store,
    previous_id,
    current_id,
    model=None,
    gate=None,
    extractor=None,
    model_path=None,
    calibration=None,
    mode="longitudinal",
    fallback_visual=False,
    requested_mode=None,
):
    previous, current = store.pair(previous_id, current_id, mode)
    photo0, mask0 = store.load_images(previous)
    photo1, mask1 = store.load_images(current)
    classification0 = classify_record(
        store, previous_id, model, gate, calibration, model_path, explain=False
    )
    classification1 = classify_record(
        store, current_id, model, gate, calibration, model_path
    )
    digest = classification1.get("model_sha256")
    reviewed = previous["metadata"].get("mask_reviewed") and current["metadata"].get(
        "mask_reviewed"
    )
    if mode == "visual":
        result, aligned, overlay = compare_visual_images(
            photo0, photo1, mask0, mask1, reviewed
        )
        result.update(
            previous_classification=classification0,
            current_classification=classification1,
            model_sha256=digest,
        )
        if requested_mode == "longitudinal":
            result["requested_mode"] = "longitudinal"
            result["fallback_reason"] = (
                "Las fotografías tienen la misma fecha de captura; no hay un intervalo temporal."
            )
            result["warnings"].insert(0, result["fallback_reason"])
    else:
        result, aligned, overlay = compare_images(
            photo0,
            photo1,
            mask0,
            mask1,
            classification0,
            classification1,
            extractor,
            digest,
            reviewed,
        )
        result["mode"] = "longitudinal"
        if (
            fallback_visual
            and not result["comparable"]
            and result.get("visual_differences")
        ):
            reason = next(
                iter(result.get("warnings", [])),
                "Los controles de comparación no se completaron.",
            )
            registration = result.get("registration", {})
            color_controls = result.get("color_normalization", {})
            result, aligned, overlay = compare_visual_images(
                photo0, photo1, mask0, mask1, reviewed
            )
            result.update(
                previous_classification=classification0,
                current_classification=classification1,
                model_sha256=digest,
                requested_mode="longitudinal",
                fallback_reason=reason,
            )
            result.update(registration=registration, color_normalization=color_controls)
            result["warnings"].insert(
                0,
                "La comparación temporal no superó todos los controles. Se muestran diferencias visuales: "
                + reason,
            )
            mode = "visual"
    result.update(
        previous_id=previous_id,
        current_id=current_id,
        previous_sha256=previous["sha256"],
        current_sha256=current["sha256"],
        previous_mask_sha256=previous["mask_sha256"],
        current_mask_sha256=current["mask_sha256"],
        elapsed_days=(
            datetime.fromisoformat(current["captured_at"])
            - datetime.fromisoformat(previous["captured_at"])
        ).total_seconds()
        / 86400,
        previous_date=previous["captured_at"],
        current_date=current["captured_at"],
    )
    if model_path is not None:
        run_root = model_path.parent.parent
        result["filter_artifacts_sha256"] = {
            str(relative): hashlib.sha256(
                (run_root / relative).read_bytes()
            ).hexdigest()
            for relative in ("domain-01/gate.json", "domain-02/config.json")
            if (run_root / relative).is_file()
        }
    identifier = store.save_comparison(previous_id, current_id, result, overlay)
    return dict(
        id=identifier,
        result=result,
        previous=(
            Image.fromarray(normalized(photo0, mask0)[0])
            if result["comparable"] or mode == "visual"
            else photo0
        ),
        current=aligned,
        overlay=overlay,
    )
