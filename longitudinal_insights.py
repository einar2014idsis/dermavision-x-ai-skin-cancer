"""Interpretaciones compartidas por la interfaz y el PDF, sin inventar mediciones."""

from datetime import datetime
import math
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

METRICS = {
    "index": ("Índice descriptivo", "puntos / 100"),
    "area": ("Área aparente", "% respecto a la referencia"),
    "shape": ("Diferencia de forma", "distancia entre siluetas (0–1)"),
    "asymmetry": ("Cambio de asimetría", "diferencia del indicador"),
    "border": ("Cambio de irregularidad del borde", "diferencia del indicador"),
    "color": ("Diferencia de color", "distancia LAB (ΔE)"),
    "texture": ("Diferencia de textura", "distancia entre histogramas (0–1)"),
}


def date_label(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.strftime("%d/%m/%Y") + (
            parsed.strftime(" %H:%M:%S")
            if parsed.time().isoformat() != "00:00:00"
            else ""
        )
    except (ValueError, TypeError):
        return "Fecha no disponible"


def finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def comparison_status(row):
    result = row["result"]
    if row.get("stale_dates"):
        return "Recalcular: fecha modificada"
    if result.get("mode") == "visual":
        return "Solo diferencias visuales"
    if result.get("comparable"):
        return "Alineación y controles aceptados"
    return "No evaluable"


def measurement_rows(result):
    """Nombre, anterior, actual, diferencia y significado; guiones si no hay datos."""
    visual = result.get("mode") == "visual" or not result.get("comparable")
    changes = (
        result.get("visual_differences", {}) if visual else result.get("changes", {})
    )
    before, after = result.get("features_previous", {}), result.get(
        "features_current", {}
    )

    def value(features, key):
        raw = features.get(key)
        return f"{raw:.3f}" if finite(raw) else "—"

    def delta(key, suffix="", signed=False):
        raw = changes.get(key)
        return (
            (format(raw, "+.3f" if signed else ".3f") + suffix)
            if finite(raw)
            else "No disponible"
        )

    def color(features):
        values = features.get("color_lab_mean", [])
        return (
            " / ".join(f"{v:.1f}" for v in values)
            if len(values) == 3 and all(finite(v) for v in values)
            else "—"
        )

    def texture(features):
        hist = features.get("texture_lbp_hist", [])
        return (
            f"H={-sum(p*math.log2(p) for p in hist if p>0):.3f}"
            if hist and all(finite(p) and p >= 0 for p in hist)
            else "—"
        )

    rows = [
        (
            "Cobertura de la fotografía" if visual else "Área aparente",
            (
                value(before, "area_coverage_percent") + " %"
                if visual and finite(before.get("area_coverage_percent"))
                else (
                    "—"
                    if visual
                    else (
                        str(before["area_px"]) if finite(before.get("area_px")) else "—"
                    )
                )
            ),
            (
                value(after, "area_coverage_percent") + " %"
                if visual and finite(after.get("area_coverage_percent"))
                else (
                    "—"
                    if visual
                    else str(after["area_px"]) if finite(after.get("area_px")) else "—"
                )
            ),
            (
                delta("area_coverage_pp", " pp", True)
                if visual
                else delta("area", " %", True)
            ),
            (
                "Depende del encuadre; no mide crecimiento."
                if visual
                else "Píxeles tras alinear. Variación relativa; no equivale a mm²."
            ),
        ),
        (
            "Forma",
            "—",
            "—",
            delta("shape"),
            "Distancia entre siluetas: 0 indica coincidencia; 1, máxima diferencia.",
        ),
        (
            "Asimetría",
            value(before, "asymmetry"),
            value(after, "asymmetry"),
            delta("asymmetry", signed=True),
            "Positivo: aumenta el indicador; negativo: disminuye.",
        ),
        (
            "Borde",
            value(before, "border_irregularity"),
            value(after, "border_irregularity"),
            delta("border", signed=True),
            "Positivo: aumenta la irregularidad medida del contorno.",
        ),
        (
            "Color",
            color(before),
            color(after),
            delta("color", " ΔE"),
            "Valores medios L/a/b. ΔE mide su distancia; la iluminación puede influir.",
        ),
        (
            "Textura",
            texture(before),
            texture(after),
            delta("texture"),
            "H: entropía del histograma (bits). La diferencia usa el histograma completo (0–1).",
        ),
    ]
    return rows


def comparison_narrative(result, stale=False):
    if stale:
        return "Se modificaron las fechas después del análisis. Recalcula esta comparación antes de interpretar sus resultados."
    visual = result.get("mode") == "visual"
    if not result.get("comparable") and not result.get("visual_available"):
        return (
            "No se pudieron medir cambios. Esto no indica que las fotografías sean iguales. "
            + next(
                iter(result.get("warnings", [])),
                "Revisa los contornos y las condiciones de captura.",
            )
        )
    components = result.get("visual_components" if visual else "index_components", {})
    ranked = sorted(
        ((k, v) for k, v in components.items() if finite(v) and v >= 0.1),
        key=lambda kv: kv[1],
        reverse=True,
    )
    names = dict(
        area="área aparente",
        shape="forma",
        asymmetry="asimetría",
        border="borde",
        color="color",
        texture="textura",
    )
    prominent = ", ".join(names.get(k, k) for k, _ in ranked[:3])
    lead = (
        "Solo se describen diferencias visuales; no se confirmó una comparación longitudinal. "
        if visual
        else "Las fotografías superaron los controles de alineación y comparación. "
    )
    if not visual and finite(result.get("change_index")):
        lead += f"Índice descriptivo: {result['change_index']:.1f} de 100. Es una medida heurística de diferencia entre imágenes, no una precisión ni una probabilidad de cáncer. "
    lead += (
        "Las mayores contribuciones al índice corresponden a: " + prominent + ". "
        if prominent
        else (
            "No hay diferencias destacadas según las escalas del índice. "
            if components
            else "Consulta las mediciones disponibles en la tabla. "
        )
    )
    area = result.get("changes", {}).get("area")
    if not visual and finite(area):
        lead += f"El área aparente varió {area:+.1f} % respecto a la fotografía de referencia. "
    return (
        lead
        + "Los indicadores describen imágenes; no establecen gravedad, malignidad ni crecimiento físico."
    )


def comparison_conclusion(result):
    """Present the pair's outcome without treating model scores as clinical risk."""
    if not result:
        return "Selecciona y compara dos fotografías para obtener un resultado."
    dates = date_label(result.get("previous_date")) + " → " + date_label(result.get("current_date"))
    visual = result.get("mode") == "visual"
    if visual:
        conclusion = "Estado: solo diferencias visuales. No se obtuvo una medición longitudinal válida."
        reason = result.get("fallback_reason") or next(iter(result.get("warnings", [])), "")
        if reason:
            conclusion += "\nMotivo: " + str(reason)
    elif not result.get("comparable") or not finite(result.get("change_index")):
        reason = next(iter(result.get("warnings", [])), "")
        conclusion = "Estado: no evaluable. No se asigna un índice de cambio.\n"
        if reason:
            conclusion += "Motivo: " + str(reason) + "\n"
        conclusion += quality_guidance(result)
    else:
        conclusion = "Estado: comparación técnicamente aceptada.\n" + comparison_narrative(result)
    classifications = []
    for side, caption in (("previous", "Fotografía anterior"), ("current", "Fotografía posterior")):
        classification = result.get(side + "_classification") or {}
        state, label = classification.get("state"), classification.get("label")
        if state == "accepted" and label in ("benign", "malignant"):
            text = "patrón " + ("maligno" if label == "malignant" else "benigno") + " experimental"
            score = classification.get("score")
            if finite(score) and 0 <= score <= 1:
                text += f"; puntuación para la clase maligna: {score * 100:.1f} %"
        elif state == "uncertain":
            text = "resultado no concluyente"
        elif state in ("rejected", "quality_failed"):
            text = "sin clasificación válida por los controles de entrada"
        else:
            text = "clasificación no disponible"
        classifications.append(caption + ": " + text + ".")
    explanation = ("El modelo clasifica cada fotografía por separado. La comparación describe diferencias visuales; "
                   "un cambio de tamaño no determina malignidad ni modifica automáticamente esas clasificaciones. "
                   "La puntuación no es precisión ni probabilidad clínica.")
    return (dates + "\n\n" + conclusion + "\n\nCLASIFICACIÓN INDIVIDUAL\n" + "\n".join(classifications)
            + "\n\n" + explanation + "\n\nLa identidad de la lesión no se verifica automáticamente. No constituye un diagnóstico médico.")


def quality_guidance(result):
    """Explain which observation is limited and how to improve the next capture."""
    if result.get("comparable"):
        return "Las fotos pudieron alinearse. Para repetir el seguimiento, conserva un encuadre, distancia e iluminación similares."
    registration = result.get("registration", {})
    color = result.get("color_normalization", {})
    if registration.get("accepted") is False:
        reason = (
            "No se encontraron suficientes puntos comunes en la piel para alinear las fotos. "
            "Comprueba primero que ambas fotos correspondan a la misma lesión; el sistema no puede verificarlo automáticamente. "
            "Revisa las fechas y contornos y, si son de la misma lesión, repite la captura con encuadre y distancia similares, incluyendo piel alrededor."
        )
    elif registration.get("accepted") and not framing_accepted(result):
        reason = (
            "La alineación se obtuvo, pero parte de la lesión o del encuadre quedó fuera de la zona común. "
            "Incluye la lesión completa y más piel alrededor en ambas fotografías."
        )
    elif registration.get("accepted") and color and not color_accepted(result):
        reason = (
            "Las fotos se alinearon, pero su iluminación o color son demasiado diferentes. "
            "Las diferencias de color pueden deberse a la captura; repite las fotos con una luz similar y sin filtros."
        )
    else:
        warnings = " ".join(str(w) for w in result.get("warnings", [])).lower()
        if "contorno" in warnings:
            reason = "Revisa los contornos: deben incluir la lesión completa y dejar piel alrededor."
        elif "calidad" in warnings or "contenido" in warnings:
            reason = "Una fotografía no superó los controles de entrada. Revisa su enfoque y que corresponda a una lesión cutánea."
        else:
            reason = "Revisa que las fotos correspondan a la misma lesión, sus contornos y las condiciones de captura."
    return (
        "Se muestran diferencias visuales, pero no una medición temporal fiable. "
        if result.get("visual_available")
        else "No se pudieron medir cambios. "
    ) + reason


def comparison_readiness(result, stale=False):
    """Short user-facing decision before displaying measurements."""
    if stale:
        return (
            "RECALCULAR",
            "Las fechas cambiaron después del análisis. Vuelve a comparar estas fotografías.",
        )
    if result.get("mode") == "visual":
        reason = result.get("fallback_reason")
        if reason:
            return (
                "SOLO DIFERENCIAS VISUALES",
                reason + " " + quality_guidance(result),
            )
        return (
            "SOLO DIFERENCIAS VISUALES",
            "Estas fotografías no ofrecen una medición temporal fiable. Las diferencias dependen también de la captura.",
        )
    if result.get("comparable"):
        return (
            "COMPARABLE",
            "Alineación, encuadre y color superaron los controles del prototipo. Revisa las mediciones como diferencias de imagen.",
        )
    return ("NO EVALUABLE", quality_guidance(result))


def framing_accepted(result):
    registration = result.get("registration", {})
    if "framing_accepted" in registration:
        return registration["framing_accepted"] is True
    overlap, retained = registration.get("overlap"), registration.get("lesion_retained")
    return finite(overlap) and finite(retained) and overlap >= 0.65 and retained >= 0.95


def color_accepted(result):
    color = result.get("color_normalization", {})
    if "accepted" in color:
        return color["accepted"] is True
    offset, residual = color.get("offset"), color.get("residual_delta_e")
    return (
        isinstance(offset, (list, tuple))
        and len(offset) == 3
        and all(finite(v) for v in offset)
        and math.sqrt(sum(v * v for v in offset)) <= 25
        and finite(residual)
        and residual <= 18
    )


def quality_rows(result, records=(), stale=False):
    lookup = {r["id"]: r for r in records}
    rows = [("Resultado", comparison_status(dict(result=result, stale_dates=stale)))]
    from longitudinal_review import identity_description
    for side, name in (("previous", "anterior"), ("current", "actual")):
        record = lookup.get(result.get(side + "_id"))
        if record:
            rows.append(("Identidad · foto " + name, identity_description(record)))
    for quality in result.get("capture_quality", []):
        rows.append(("Captura · " + quality.get("label", "foto"),
                     "Calidad técnica aceptada" if quality.get("accepted") else quality.get("message", "Revisar calidad")))
    for key, title in [
        ("previous_id", "Contorno anterior"),
        ("current_id", "Contorno actual"),
    ]:
        record = lookup.get(result.get(key))
        rows.append(
            (
                title,
                (
                    "Revisado por el usuario"
                    if record and record["metadata"].get("mask_reviewed")
                    else "Sin constancia de revisión"
                ),
            )
        )
    registration = result.get("registration", {})
    rows.append(
        (
            "Alineación",
            (
                "Aceptada"
                if registration.get("accepted")
                else (
                    "No aceptada"
                    if registration.get("accepted") is False
                    else "No realizada o sin registro"
                )
            ),
        )
    )
    for key, title in [
        ("matches", "Correspondencias en la piel"),
        ("overlap", "Encuadre común"),
        ("lesion_retained", "Región conservada tras el ajuste"),
    ]:
        val = registration.get(key)
        if finite(val):
            rows.append(
                (title, str(int(val)) if key == "matches" else f"{val*100:.1f} %")
            )
    color = result.get("color_normalization", {})
    rows.append(
        (
            "Encuadre después de alinear",
            (
                "Aceptado"
                if framing_accepted(result)
                else "Insuficiente" if registration.get("accepted") else "No evaluado"
            ),
        )
    )
    rows.append(
        (
            "Iluminación y color",
            (
                "Control de color aceptado"
                if color_accepted(result)
                else (
                    "Control no aceptado: las condiciones de luz o color difieren"
                    if color
                    else "No evaluados o sin registro"
                )
            ),
        )
    )
    if finite(color.get("residual_delta_e")):
        rows.append(
            (
                "Diferencia residual en la piel de referencia",
                f'{color["residual_delta_e"]:.2f} ΔE',
            )
        )
    for warning in result.get("warnings", []):
        rows.append(("Observación", str(warning)))
    if result.get("fallback_reason"):
        rows.append(("Motivo de comparación solo visual", result["fallback_reason"]))
    return rows


def comparison_validity(row, records):
    """Reason to discard a saved measurement whose input records changed."""
    result = row.get("result", {})
    lookup = {record["id"]: record for record in records}
    if row.get("stale_dates"):
        return "las fechas de las fotografías cambiaron; vuelve a comparar"
    for side in ("previous", "current"):
        identifier = row.get(side + "_id", result.get(side + "_id"))
        record = lookup.get(identifier)
        if record is None:
            return "una fotografía ya no está incluida o disponible"
        latest = record.get("metadata", {}).get("classification") or {}
        snapshot = result.get(side + "_classification", {})
        if latest and any(latest.get(key) != snapshot.get(key) for key in ("state", "raw_score", "model_sha256", "calibration")):
            return "la clasificación guardada cambió; vuelve a comparar"
        recorded_date = result.get(side + "_date")
        if recorded_date is not None and recorded_date != record.get("captured_at"):
            return "las fechas de las fotografías cambiaron; vuelve a comparar"
        for snapshot, live in (
            (side + "_sha256", "sha256"),
            (side + "_mask_sha256", "mask_sha256"),
        ):
            if (
                result.get(snapshot) is not None
                and record.get(live) is not None
                and result[snapshot] != record[live]
            ):
                return "una fotografía o su contorno cambió; vuelve a comparar"

    def finite_tree(value):
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return True
        if isinstance(value, (int, float)):
            return finite(value)
        if isinstance(value, dict):
            return all(finite_tree(v) for v in value.values())
        if isinstance(value, (list, tuple)):
            return all(finite_tree(v) for v in value)
        return False

    for key in (
        "change_index",
        "changes",
        "index_components",
        "features_previous",
        "features_current",
        "visual_index",
        "visual_differences",
        "visual_components",
        "registration",
        "color_normalization",
    ):
        if key in result and not finite_tree(result[key]):
            return "el análisis contiene una medición inválida; vuelve a comparar"
    for key in ("change_index", "visual_index"):
        if finite(result.get(key)) and not 0 <= result[key] <= 100:
            return (
                "el análisis contiene un índice fuera de su escala; vuelve a comparar"
            )
    if result.get("comparable"):
        registration = result.get("registration", {})
        if (
            registration.get("accepted") is False
            or registration.get("framing_accepted") is False
        ):
            return "la alineación o el encuadre no superaron los controles"
        if result.get("color_normalization", {}).get("accepted") is False:
            return "la iluminación o el color no superaron los controles"
    return None


def followup_summary(comparisons, records, reference_id=None):
    """Plain, deterministic summary of included records and current measurements."""
    if not records:
        return "Todavía no hay fotografías registradas para esta lesión. Agrega una fotografía con su fecha para iniciar el seguimiento."
    ordered = sorted(records, key=lambda r: (r.get("captured_at", ""), r["id"]))
    lookup = {r["id"]: r for r in ordered}
    origin = lookup.get(reference_id) if reference_id is not None else ordered[0]
    if origin is None:
        return "La fotografía de inicio no está incluida en este seguimiento. Revisa las fotografías seleccionadas."
    lines = [
        f"Se registraron {len(ordered)} fotografía{'s' if len(ordered) != 1 else ''} de esta lesión, "
        f"del {date_label(ordered[0].get('captured_at'))} al {date_label(ordered[-1].get('captured_at'))}."
    ]
    if len(ordered) == 1:
        lines.append(
            "Hace falta otra fotografía de la misma lesión para describir cambios entre fechas."
        )
    # Latest saved result for each pair. Repeated analyses do not inflate the count.
    pairs = {}
    for row in sorted(
        comparisons, key=lambda r: (str(r.get("created", "")), r.get("id", ""))
    ):
        a, b = row.get("previous_id"), row.get("current_id")
        if a in lookup and b in lookup:
            pairs[(a, b)] = row
    measured, exclusions = [], {}
    for row in pairs.values():
        result = row.get("result", {})
        invalid = comparison_validity(row, ordered)
        if invalid:
            reason = invalid
        elif result.get("mode") == "visual":
            reason = quality_guidance(result)
        elif not result.get("comparable") or not finite(result.get("change_index")):
            reason = quality_guidance(result)
        else:
            try:
                before = datetime.fromisoformat(
                    lookup[row["previous_id"]]["captured_at"]
                )
                after = datetime.fromisoformat(lookup[row["current_id"]]["captured_at"])
                if after <= before:
                    reason = "las fechas no indican dos momentos sucesivos"
                else:
                    measured.append(row)
                    continue
            except (ValueError, TypeError):
                reason = "falta una fecha de fotografía válida"
        exclusions[reason] = exclusions.get(reason, 0) + 1
    if len(ordered) >= 2:
        lines.append(
            f"Hay {len(measured)} {'comparación vigente' if len(measured) == 1 else 'comparaciones vigentes'} "
            "con mediciones temporales válidas entre dos fotografías."
        )
    common = sorted(
        (r for r in measured if r["previous_id"] == origin["id"]),
        key=lambda r: (lookup[r["current_id"]]["captured_at"], r["current_id"]),
    )
    if common:
        latest = common[-1]
        result = latest["result"]
        lines.append(
            f"La última medición respecto a la foto de inicio ({date_label(origin['captured_at'])}) "
            f"corresponde a {date_label(lookup[latest['current_id']]['captured_at'])}: "
            f"índice descriptivo de {result['change_index']:.1f} sobre 100."
        )
        ranked = sorted(
            (
                (k, v)
                for k, v in result.get("index_components", {}).items()
                if finite(v) and v >= 0.1
            ),
            key=lambda item: (-item[1], item[0]),
        )
        names = dict(
            area="área aparente",
            shape="forma",
            asymmetry="asimetría",
            border="borde",
            color="color",
            texture="textura",
        )
        if ranked:
            lines.append(
                "Las principales diferencias de ese par corresponden a "
                + ", ".join(names.get(k, k) for k, _ in ranked[:3])
                + "."
            )
        else:
            lines.append(
                "Ese par no presenta diferencias destacadas según las escalas del índice; esto no prueba que las fotos sean idénticas."
            )
        area = result.get("changes", {}).get("area")
        if finite(area):
            lines.append(
                f"El área aparente varió {area:+.1f} %; depende de las imágenes y no equivale al tamaño físico de la lesión."
            )
        if len(common) == 1:
            lines.append(
                "Una sola comparación permite describir ese par, pero todavía no establecer una tendencia en el tiempo."
            )
    elif len(ordered) >= 2:
        lines.append(
            "No hay mediciones válidas respecto a la foto de inicio. Esto no significa que la lesión no haya cambiado."
        )
    if exclusions:
        lines.append(
            "Resultados excluidos de la medición temporal: "
            + "; ".join(
                f"{count}: {reason}" for reason, count in sorted(exclusions.items())
            )
            + "."
        )
    latest_record = ordered[-1]
    analysis = latest_record.get("metadata", {}).get("classification") or {}
    snapshot_stale = any(
        analysis.get(key) is not None
        and latest_record.get(live) is not None
        and analysis[key] != latest_record[live]
        for key, live in (("image_sha256", "sha256"), ("mask_sha256", "mask_sha256"))
    )
    state = analysis.get("state") if not snapshot_stale else "outdated"
    if state == "accepted" and analysis.get("label") in ("benign", "malignant"):
        label = "benigna" if analysis["label"] == "benign" else "maligna"
        sentence = f"Por separado, la fotografía más reciente ({date_label(latest_record['captured_at'])}) tiene clasificación experimental {label}."
        if finite(analysis.get("score")) and 0 <= analysis["score"] <= 1:
            sentence += f" Puntuación para la clase maligna: {100*analysis['score']:.1f} %; no es una probabilidad de tener cáncer."
        lines.append(sentence)
    elif state == "uncertain":
        lines.append(
            "Por separado, la clasificación de la fotografía más reciente es no concluyente; el modelo no asignó una clase con los criterios del sistema."
        )
    elif state in ("rejected", "quality_failed"):
        lines.append(
            "Por separado, la fotografía más reciente no superó los controles de clasificación; no tiene una clase binaria válida."
        )
    elif state == "outdated":
        lines.append(
            "La clasificación de la fotografía más reciente requiere recalcularse porque cambió la imagen o su contorno."
        )
    else:
        lines.append(
            "La fotografía más reciente todavía no tiene una clasificación disponible."
        )
    lines.append(
        "El seguimiento describe cambios en imágenes; no determina mejoría, empeoramiento clínico ni un diagnóstico."
    )
    return "\n\n".join(lines)


def trend_series(comparisons, records, reference_id, metric="index", mode="reference"):
    """Una sola referencia, fechas vigentes y mediciones alineadas. Sin puntos ficticios."""
    lookup = {r["id"]: r for r in records}
    points = []
    excluded = dict(visual=0, stale=0, invalid=0, other_reference=0)
    latest_pairs = {}
    ordered = sorted(records, key=lambda r: (r["captured_at"], r["id"]))
    previous_by_target = {b["id"]: a["id"] for a, b in zip(ordered, ordered[1:])}
    for row in sorted(
        comparisons, key=lambda r: (str(r.get("created", "")), r.get("id", ""))
    ):
        latest_pairs[(row["previous_id"], row["current_id"])] = row
    for row in latest_pairs.values():
        result = row["result"]
        if row.get("stale_dates"):
            excluded["stale"] += 1
            continue
        if result.get("mode") == "visual":
            excluded["visual"] += 1
            continue
        invalid = comparison_validity(row, records)
        if invalid:
            excluded["stale" if invalid.startswith("las fechas") else "invalid"] += 1
            continue
        if not result.get("comparable"):
            excluded["invalid"] += 1
            continue
        expected = previous_by_target.get(row["current_id"]) if mode == "consecutive" else reference_id
        if row["previous_id"] != expected:
            excluded["other_reference"] += 1
            continue
        val = (
            result.get("change_index")
            if metric == "index"
            else result.get("changes", {}).get(metric)
        )
        target = lookup.get(row["current_id"])
        if not finite(val) or target is None or reference_id not in lookup:
            excluded["invalid"] += 1
            continue
        try:
            date = datetime.fromisoformat(target["captured_at"])
            if date <= datetime.fromisoformat(lookup[expected]["captured_at"]):
                excluded["invalid"] += 1
                continue
        except (ValueError, TypeError):
            excluded["invalid"] += 1
            continue
        points.append(
            dict(
                value=float(val),
                date=date,
                target=target["id"],
                comparison_id=row["id"],
                previous_id=expected,
            )
        )
    # One target per date/record: retain the latest saved measurement, not duplicate bars.
    unique = {p["target"]: p for p in points}
    points = sorted(unique.values(), key=lambda p: (p["date"], p["target"]))
    reference = lookup.get(reference_id)
    captures = []
    if reference:
        for record in records:
            try:
                date = datetime.fromisoformat(record["captured_at"])
                if date >= datetime.fromisoformat(reference["captured_at"]):
                    captures.append(dict(target=record["id"], date=date))
            except (ValueError, TypeError):
                pass
    captures.sort(key=lambda p: (p["date"], p["target"]))
    return dict(
        points=points,
        excluded=excluded,
        reference=reference,
        metric=metric,
        captures=captures,
        mode=mode,
    )


def trend_note(series):
    counts = series["excluded"]
    note = ("Cada punto compara con la visita inmediatamente anterior; no es cambio acumulado. "
            if series.get("mode") == "consecutive" else
            "Cada punto medido compara una captura con la misma referencia. ")
    note += (
        "Una comparación describe diferencias; no permite establecer una tendencia. "
        if len(series["points"]) == 1
        else (
            "Sin comparaciones válidas con esta referencia. "
            if not series["points"]
            else "La línea muestra cómo cambia la diferencia visual respecto a la referencia. "
        )
    )
    return (
        note
        + f"Excluidas: {counts['visual']} solo visuales, {counts['stale']} con fechas modificadas, {counts['invalid']} sin medición válida, {counts['other_reference']} con otra referencia. No mide riesgo ni gravedad."
    )


def trend_direction(series):
    """Direction of displayed distances, never a clinical improvement label."""
    points = series["points"]
    title, unit = METRICS.get(series.get("metric", "index"), METRICS["index"])
    if series.get("mode") == "consecutive" and points:
        return f"{len(points)} intervalo(s) con {title.lower()} medido. Cada punto usa su visita anterior; los valores no se suman ni representan cambio acumulado."
    if not points:
        return f"Sin mediciones temporales válidas para {title.lower()}."
    if len(points) == 1:
        value = (
            f"{points[0]['value']:.1f} / 100"
            if series.get("metric") == "index"
            else f"{points[0]['value']:.3f} {unit}"
        )
        return f"Primera comparación de {title.lower()}: {value}. Otra captura evaluable permitirá ver la dirección del cambio."
    previous, current = points[-2:]
    delta = current["value"] - previous["value"]
    if round(current["value"], 1) == round(previous["value"], 1):
        return f"Mismo valor mostrado para {title.lower()}: {current['value']:.1f}. Esto no significa que las fotografías sean idénticas."
    direction = "Aumentó" if delta > 0 else "Disminuyó"
    suffix = "puntos" if series.get("metric") == "index" else unit
    return f"{direction} {title.lower()}: {delta:+.1f} {suffix} desde {date_label(previous['date'].isoformat())}."


def trend_figure(series, size=(8.5, 3.4)):
    from matplotlib.dates import date2num

    figure = Figure(figsize=size, facecolor="white")
    figure.subplots_adjust(left=0.12, right=0.97, top=0.78, bottom=0.30)
    FigureCanvasAgg(figure)
    ax = figure.add_subplot(111)
    title, unit = METRICS[series["metric"]]
    reference = series["reference"]
    ax.set_title(
        ("Cambios visuales en el tiempo" if series["metric"] == "index" else title)
        + ("\nVisitas consecutivas · inicio: " if series.get("mode") == "consecutive" else "\nReferencia: ")
        + (date_label(reference["captured_at"]) if reference else "sin seleccionar"),
        fontsize=11,
    )
    points = series["points"]
    figure.timeline_points = []
    captures = series.get("captures") or [
        dict(target=p["target"], date=p["date"]) for p in points
    ]
    if not points:
        # Never hide a visit merely because its measurement was not reliable.
        # This keeps the clinical chronology useful while avoiding fabricated data.
        ax.set_title("Cronología de fotografías · sin mediciones temporales válidas", fontsize=11)
        if not captures:
            ax.axis("off")
            ax.text(
                0.5, 0.45, "Aún no hay fotografías registradas.", transform=ax.transAxes,
                ha="center", va="center", fontsize=10,
            )
            return figure
        xs = [date2num(item["date"]) for item in captures]
        ax.hlines(0, min(xs), max(xs), color="#b8bfca", linewidth=2)
        for item, x in zip(captures, xs):
            marker = "o" if item["target"] == (reference or {}).get("id") else "x"
            color = "#526581" if marker == "o" else "#a66b20"
            ax.scatter([x], [0], marker=marker, color=color, s=60, zorder=3)
            ax.annotate(
                "Inicio" if marker == "o" else "Sin medición",
                (x, 0), xytext=(0, 11), textcoords="offset points",
                ha="center", fontsize=8, color=color,
            )
            figure.timeline_points.append((x, 0, item["target"]))
        ax.set_xticks(xs, [date_label(item["date"].isoformat()).replace(" ", "\n") for item in captures], fontsize=8)
        ax.set_yticks([])
        ax.set_xlabel("Fecha real de captura · pulsa un punto para abrir la fotografía", fontsize=8)
        ax.text(
            0.5, 0.10,
            "Las fotografías se conservan en la cronología aunque la comparación requiera repetir condiciones de captura.",
            transform=ax.transAxes, ha="center", va="center", fontsize=9, color="#526581",
        )
        ax.margins(x=0.12, y=0.8)
        return figure
    lookup = {p["target"]: p for p in points}
    ref_id = reference["id"] if reference else None
    # Reference origin is defined, not an additional measured comparison.
    origin = (
        date2num(datetime.fromisoformat(reference["captured_at"]))
        if reference
        else None
    )
    if origin is not None:
        ax.scatter(
            [origin], [0], s=50, facecolor="white", edgecolor="#526581", zorder=4
        )
        ax.annotate(
            "Inicio · referencia",
            (origin, 0),
            xytext=(5, 10),
            textcoords="offset points",
            fontsize=8,
            color="#526581",
        )
        figure.timeline_points.append((origin, 0, ref_id))
    last = None
    for capture in captures:
        identifier = capture["target"]
        x = date2num(capture["date"])
        if identifier == ref_id:
            last = (x, 0, True)
            continue
        point = lookup.get(identifier)
        if point is None:
            # Leave a gap, rather than interpolate across an unevaluable capture.
            missing_y = -8 if series["metric"] == "index" else min(0, min(p["value"] for p in points)) - max(0.1, max(abs(p["value"]) for p in points) * 0.15)
            ax.scatter([x], [missing_y], marker="x", color="#c26b18", s=42)
            ax.annotate(
                "Sin medición",
                (x, missing_y),
                xytext=(0, -9),
                textcoords="offset points",
                ha="center",
                fontsize=7,
                color="#a45712",
            )
            figure.timeline_points.append((x, missing_y, identifier))
            last = None
            continue
        y = point["value"]
        if last and series.get("mode") != "consecutive":
            ax.plot(
                [last[0], x],
                [last[1], y],
                color="#635bdb",
                linewidth=2,
                linestyle="--" if last[2] else "-",
            )
        ax.scatter([x], [y], color="#635bdb", s=48, zorder=4)
        ax.annotate(
            f"{y:.1f}",
            (x, y),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            fontsize=9,
        )
        figure.timeline_points.append((x, y, identifier))
        last = (x, y, False)
    dates = [date2num(p["date"]) for p in captures]
    labels = [date_label(p["date"].isoformat()).replace(" ", "\n") for p in captures]
    ax.set_xticks(
        dates,
        labels,
        rotation=35 if len(dates) > 4 else 0,
        ha="right" if len(dates) > 4 else "center",
        fontsize=8,
    )
    ax.set_xlabel(
        "Fecha real de captura · separación proporcional al tiempo", fontsize=8
    )
    ax.set_ylabel(
        (
            ("Diferencia por intervalo (0–100)" if series.get("mode") == "consecutive" else "Diferencia visual respecto al inicio (0–100)")
            if series["metric"] == "index"
            else unit
        ),
        fontsize=9,
    )
    ax.axhline(0, color="#8c95a5", linewidth=0.8)
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    ax.margins(y=0.2, x=0.08)
    if series["metric"] == "index":
        ax.set_ylim(-19, 112)
        ax.set_yticks([0, 25, 50, 75, 100])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    return figure
