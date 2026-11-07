"""Reportes locales y revisión técnica; no certifican validez clínica."""

from collections import Counter
from datetime import datetime

from longitudinal_insights import comparison_validity, finite, quality_guidance


def selected_followup_summary(comparisons, records, mode="reference"):
    """Summarize the same selected visit pairs as the timeline and video."""
    from longitudinal_review import visit_review_rows
    from longitudinal_insights import date_label
    rows = visit_review_rows(comparisons, records, mode)
    if not rows:
        return "No hay fotografías registradas."
    counts = {state: sum(row["state"] == state for row in rows)
              for state in ("available", "pending", "invalid", "stale")}
    text = [f"Se registraron {len(rows)} fotografías, del {date_label(rows[0]['record']['captured_at'])} al {date_label(rows[-1]['record']['captured_at'])}.",
            "Modo: " + ("referencia inicial" if mode == "reference" else "visitas consecutivas") + ".",
            f"Mediciones disponibles: {counts['available']}; pendientes: {counts['pending']}; no evaluables: {counts['invalid']}; requieren recalcular: {counts['stale']}."]
    available = []
    for row in rows[1:]:
        label = date_label(row["record"]["captured_at"])
        if row["state"] == "available":
            result = row["comparison"]["result"]
            index = result["change_index"]
            area = result.get("changes", {}).get("area")
            line = f"{label}: índice descriptivo {index:.1f} / 100"
            if finite(area):
                line += f"; área aparente {area:+.1f} %"
            text.append(line + ".")
            available.append(index)
        else:
            text.append(f"{label}: {row['title']}. {row['reason']}")
    if mode == "reference" and len(available) >= 2:
        text.append(f"Entre la primera y la última medición disponible con la referencia inicial, el índice varió {available[-1] - available[0]:+.1f} puntos.")
    elif mode == "consecutive" and available:
        text.append("Cada medición corresponde a un intervalo independiente; no se suman los valores.")
    text.append("El índice describe diferencias de imagen, no gravedad. El área es aparente y no es tamaño físico. La identidad de la lesión no se verifica automáticamente.")
    return "\n".join(text)


def report_comparison_state(row, records):
    """One decision for the summary, value, map and technical audit of a saved pair."""
    result = row.get("result", {})
    invalid = comparison_validity(row, records)
    lookup = {record["id"]: record for record in records}
    for side in ("previous", "current"):
        record = lookup.get(row.get(side + "_id"), {})
        latest = record.get("metadata", {}).get("classification") or {}
        snapshot = result.get(side + "_classification", {})
        if latest and any(latest.get(key) != snapshot.get(key)
                          for key in ("state", "raw_score", "model_sha256", "calibration")):
            invalid = "La clasificación guardada de una fotografía cambió; vuelve a comparar."
    if invalid:
        return dict(kind="outdated", label="Requiere actualizarse", value=None,
                    reason=invalid, action="Revisa las fotografías y vuelve a comparar.",
                    show_map=False)
    if result.get("mode") == "visual":
        available = bool(result.get("visual_available"))
        return dict(kind="visual" if available else "rejected",
                    label="Solo diferencias visuales" if available else "No evaluable",
                    value=None, reason=result.get("fallback_reason") or
                    next(iter(result.get("warnings", [])), "No hay medición temporal válida."),
                    action=quality_guidance(result), show_map=available)
    if result.get("comparable") and finite(result.get("change_index")):
        try:
            before = datetime.fromisoformat(lookup[row["previous_id"]]["captured_at"])
            after = datetime.fromisoformat(lookup[row["current_id"]]["captured_at"])
            chronological = after > before
        except (KeyError, TypeError, ValueError):
            chronological = False
        if chronological:
            return dict(kind="comparable", label="Comparable según controles técnicos",
                        value=result["change_index"], reason="Alineación, encuadre y color aceptados.",
                        action="Revisa la superposición y confirma que es la misma lesión; la identidad no se verifica automáticamente.",
                        show_map=True)
        return dict(kind="outdated", label="Revisar fechas", value=None,
                    reason="Las fechas no indican dos momentos sucesivos.",
                    action="Corrige la fecha de captura y vuelve a comparar.", show_map=False)
    return dict(kind="rejected", label="No evaluable", value=None,
                reason=next(iter(result.get("warnings", [])), "No hay medición temporal válida."),
                action=quality_guidance(result), show_map=False)


def report_overview(comparisons, records):
    """Count the latest result of each included pair, not repeated attempts."""
    selected = {record["id"] for record in records}
    latest = {}
    attempts = 0
    for row in sorted(comparisons, key=lambda r: (str(r.get("created", "")), r.get("id", ""))):
        pair = (row.get("previous_id"), row.get("current_id"))
        if set(pair).issubset(selected):
            latest[pair] = row
            attempts += 1
    states = [(row, report_comparison_state(row, records)) for row in latest.values()]
    counts = Counter(state["kind"] for _, state in states)
    reasons = Counter(state["reason"] for _, state in states if state["kind"] != "comparable")
    return dict(attempts=attempts, pairs=len(latest), states=states,
                counts=dict(counts), reasons=dict(reasons))


def report_photo_state(record):
    """Suppress an old classification/map if its photograph or contour changed."""
    analysis = record.get("metadata", {}).get("classification") or {}
    stale = any(analysis.get(snapshot) is not None and record.get(live) is not None
                and analysis[snapshot] != record[live]
                for snapshot, live in (("image_sha256", "sha256"), ("mask_sha256", "mask_sha256")))
    if stale:
        return "Requiere actualizarse", "La fotografía o su contorno cambió. Vuelve a analizar esta visita.", False
    state = analysis.get("state")
    if state == "accepted" and analysis.get("label") in ("benign", "malignant"):
        label = "benigna" if analysis["label"] == "benign" else "maligna"
        return "Clasificación experimental: " + label, "Resultado del modelo; no confirma ni descarta cáncer.", True
    if state == "uncertain":
        return "No concluyente", "El modelo se abstiene de asignar una clase. Revisa las condiciones de captura.", False
    if state in ("rejected", "quality_failed"):
        return "Imagen rechazada" if state == "rejected" else "Calidad insuficiente", analysis.get("message") or "Repite la captura incluyendo la lesión completa, con luz uniforme y buen enfoque.", False
    return "Clasificación pendiente", "Analiza esta fotografía cuando el modelo y los filtros estén disponibles.", False


def audit_lesion(store, lesion_id):
    records = store.records(lesion_id)
    comparisons = store.comparisons(lesion_id)
    lines = [
        f"Fotografías activas: {len(records)}",
        f"Comparaciones activas: {len(comparisons)}",
    ]
    errors = []
    for record in records:
        try:
            store.load_images(record)
            if not record["metadata"].get("mask_reviewed"):
                errors.append("Contorno sin confirmar: " + record["captured_at"])
            analysis = record["metadata"].get("classification", {})
            if analysis.get("explanation"):
                store.load_explanation(record["id"])
        except Exception as exc:
            errors.append(record["captured_at"] + ": " + str(exc))
    for comparison in comparisons:
        if not store.path(comparison["overlay"]).is_file():
            errors.append("Mapa ausente: " + comparison["id"])
    dates = [r["captured_at"] for r in records]
    lines.append("Fechas repetidas: " + str(len(dates) - len(set(dates))))
    declared = sum(r.get("metadata", {}).get("lesion_identity", {}).get("status") == "user_declared" for r in records)
    lines.append(f"Visitas con declaración humana de misma lesión: {declared}. No equivale a identidad verificada clínicamente.")
    overview = report_overview(comparisons, records)
    counts = overview["counts"]
    lines.append(f"Pares distintos (último resultado de cada par): {overview['pairs']}")
    lines.append(f"Comparaciones longitudinales alineadas y vigentes: {counts.get('comparable', 0)}")
    lines.append(
        f"Pares que requieren actualizarse o revisar fechas: {counts.get('outdated', 0)}"
    )
    lines.append(
        f"Pares solo visuales: {counts.get('visual', 0)} | No evaluables: {counts.get('rejected', 0)}"
    )
    for reason, count in sorted(overview["reasons"].items()):
        lines.append(f"Motivo ({count} par/es): {reason}")
    lines += [
        "Integridad: "
        + ("sin errores detectados" if not errors else "requiere revisión"),
        *errors,
        "",
        "Verificación pendiente por el usuario:",
        "1. Confirmar que las fotografías longitudinales son de la misma lesión.",
        "2. Revisar contornos, encuadre, iluminación y alineación superpuesta.",
        "3. Usar fechas de captura reales y documentar casos rechazados.",
        "4. Contrastar cambios observados con una referencia independiente.",
        "Esta revisión comprueba datos y controles técnicos; no valida un diagnóstico.",
    ]
    return "\n".join(lines)


def export_lesion_pdf(
    store,
    lesion_id,
    destination,
    comparison_id=None,
    preview_dir=None,
    record_ids=None,
    include_explanations=True,
    detailed=False,
    include_followup=True,
    reference_id=None,
    metric="index",
    trend_mode="reference",
):
    from longitudinal_pdf import export_readable_pdf

    return export_readable_pdf(
        store,
        lesion_id,
        destination,
        comparison_id,
        preview_dir,
        record_ids,
        include_explanations,
        detailed,
        include_followup,
        reference_id,
        metric,
        trend_mode,
    )
