"""Read-only visit review states shared by timeline, history and comparison UI."""

from longitudinal_insights import comparison_validity, finite, quality_guidance


def visit_review_rows(comparisons, records, mode="reference"):
    ordered = sorted(records, key=lambda r: (r["captured_at"], r["id"]))
    latest = {}
    for row in sorted(comparisons, key=lambda r: (str(r.get("created", "")), r.get("id", ""))):
        latest[(row.get("previous_id"), row.get("current_id"))] = row
    output = []
    for i, record in enumerate(ordered):
        previous = ordered[i - 1] if i and mode == "consecutive" else (ordered[0] if i else None)
        row = latest.get((previous["id"], record["id"])) if previous else None
        state, title = "pending", "Pendiente"
        reason, action = "Aún no se ha calculado este par.", "Calcular comparación"
        if previous is None:
            state, title = "reference", "Referencia inicial"
            reason, action = "Primera fotografía por fecha; no es una medición.", "Ver fotografía"
        elif record["captured_at"] <= previous["captured_at"]:
            state, title = "invalid", "Sin intervalo temporal"
            reason, action = "Las fechas no distinguen dos momentos sucesivos.", "Revisar fechas"
        elif row:
            invalid = comparison_validity(row, ordered)
            result = row.get("result", {})
            if invalid:
                state, title = "stale", "Recalcular"
                reason, action = invalid, "Actualizar comparación"
            elif result.get("mode") == "visual" and result.get("visual_available"):
                state, title = "invalid", "Solo diferencias visuales"
                reason = result.get("fallback_reason") or quality_guidance(result)
                action = "Revisar par / repetir captura"
            elif result.get("comparable") and result.get("mode") != "visual" and finite(result.get("change_index")):
                state, title = "available", "Medición disponible"
                reason, action = "Controles técnicos aceptados; identidad no verificada automáticamente.", "Ver comparación"
            else:
                state, title = "invalid", "No evaluable"
                reason, action = quality_guidance(result), "Revisar par / repetir captura"
        output.append(dict(record=record, previous=previous, comparison=row,
                           state=state, title=title, reason=reason, action=action))
    return output


def identity_description(record):
    declaration = record.get("metadata", {}).get("lesion_identity", {})
    if declaration.get("status") == "user_declared":
        return "Misma lesión declarada por el usuario; sin verificación automática"
    if declaration.get("status") == "initial_reference":
        return "Primera foto registrada de esta lesión"
    return "Identidad de lesión sin confirmación registrada"
