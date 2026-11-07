"""Informe legible: alcance explícito, fotos, mediciones y evolución verificable."""

from pathlib import Path
from datetime import datetime
import textwrap
from PIL import Image
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_pdf import PdfPages
from longitudinal_insights import (
    date_label,
    comparison_narrative,
    comparison_conclusion,
    measurement_rows,
    quality_rows,
    trend_series,
    trend_note,
    trend_figure,
    followup_summary,
    METRICS,
)
from longitudinal_analysis import classification_text, mask_overlay
from longitudinal_reports import report_comparison_state, report_overview, report_photo_state, selected_followup_summary


class ReportPages:
    def __init__(self):
        self.figures = []

    def page(self, title):
        self.title = title
        fig = Figure(figsize=(8.27, 11.69), facecolor="white")
        FigureCanvasAgg(fig)
        fig.text(
            0.07, 0.95, "DERMAVISION-X", fontsize=18, weight="bold", color="#123047"
        )
        fig.text(0.07, 0.915, title, fontsize=13, weight="bold", color="#635bdb")
        fig.text(
            0.07,
            0.045,
            "Informe experimental. No es diagnóstico ni mide riesgo de cáncer.",
            fontsize=8,
            color="#526581",
        )
        fig.text(0.93, 0.045, str(len(self.figures) + 1), fontsize=8, ha="right")
        self.figures.append(fig)
        self.fig = fig
        self.y = 0.875
        return fig

    def text(self, body, size=9, width=96):
        for paragraph in str(body).splitlines():
            for line in textwrap.wrap(paragraph, width) or [""]:
                if self.y < 0.10:
                    self.page(self.title + " - continuación")
                self.fig.text(0.07, self.y, line, fontsize=size, color="#273b4f")
                self.y -= 0.019 if size >= 10 else 0.017
        self.y -= 0.01

    def table(self, headers, rows, widths=None, height=0.30, fontsize=8):
        if self.y - height < 0.09:
            self.page(self.title + " - continuación")
        ax = self.fig.add_axes([0.07, self.y - height, 0.86, height])
        ax.axis("off")
        wrap_widths = widths or [30] * len(headers)
        wrapped = [
            [textwrap.fill(str(v), wrap_widths[i]) for i, v in enumerate(row)]
            for row in rows
        ]
        col_widths = [w / sum(wrap_widths) for w in wrap_widths]
        tab = ax.table(
            cellText=wrapped,
            colLabels=headers,
            colWidths=col_widths,
            cellLoc="left",
            bbox=[0, 0, 1, 1],
        )
        tab.auto_set_font_size(False)
        tab.set_fontsize(fontsize)
        for (r, c), cell in tab.get_celld().items():
            cell.set_edgecolor("#d9dfeb")
            cell.set_facecolor("#eceaf9" if r == 0 else "#f8f9fc" if r % 2 else "white")
            if r == 0:
                cell.set_text_props(weight="bold", color="#123047")
        self.y -= height + 0.025

    def images(self, items, height=0.25):
        if self.y - height < 0.10:
            self.page(self.title + " - continuación")
        count = len(items)
        slot = 0.86 / count
        for i, (image, caption) in enumerate(items):
            ax = self.fig.add_axes(
                [0.07 + i * slot, self.y - height, slot - 0.015, height - 0.03]
            )
            ax.imshow(image)
            ax.axis("off")
            ax.set_title(caption, fontsize=9, pad=6)
        self.y -= height + 0.02


def export_readable_pdf(
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
    lesion = next((l for l in store.lesions() if l["id"] == lesion_id), None)
    if lesion is None:
        raise ValueError("Seleccione una lesión.")
    all_records = store.records(lesion_id)
    selected = (
        set(record_ids) if record_ids is not None else {r["id"] for r in all_records}
    )
    if not selected or not selected.issubset({r["id"] for r in all_records}):
        raise ValueError(
            "Seleccione fotografías activas de esta lesión para el informe."
        )
    records = sorted(
        (r for r in all_records if r["id"] in selected),
        key=lambda r: (r["captured_at"], r["id"]),
    )
    comparisons = store.comparisons(lesion_id)
    chosen = next((c for c in comparisons if c["id"] == comparison_id), None)
    if comparison_id and chosen is None:
        raise ValueError("La comparación seleccionada no está activa.")
    if chosen and not {chosen["previous_id"], chosen["current_id"]}.issubset(selected):
        raise ValueError(
            "Incluye las dos fotografías de la comparación elegida en el alcance del PDF."
        )
    comparisons = [
        c for c in comparisons if {c["previous_id"], c["current_id"]}.issubset(selected)
    ]
    chosen_state = report_comparison_state(chosen, records) if chosen else None
    chosen_invalid = chosen_state["reason"] if chosen_state and chosen_state["kind"] == "outdated" else None
    if metric not in METRICS:
        raise ValueError("Medición temporal no reconocida.")
    if trend_mode not in ("reference", "consecutive"):
        raise ValueError("Modo temporal no reconocido.")
    reference_id = reference_id or records[0]["id"]
    if reference_id not in selected:
        raise ValueError("La referencia del gráfico debe estar incluida en el informe.")
    series = trend_series(comparisons, records, reference_id, metric, mode=trend_mode)
    overview = report_overview(comparisons, records)
    report = ReportPages()
    report.page("Resumen del seguimiento de la lesión")
    report.text(
        f'Código de lesión: {lesion["id"][:12]} | Zona: {lesion["site"] or "No indicada"}\n'
        f"Generado: {datetime.now():%d/%m/%Y %H:%M}\n"
        f'Capturas incluidas: {len(records)} | Periodo: {date_label(records[0]["captured_at"])} a {date_label(records[-1]["captured_at"])}\n'
        f"Comparaciones incluidas en el seguimiento: {len(comparisons) if include_followup else 0}",
        size=10,
        width=83,
    )
    report.text("Qué permite conocer este informe", size=11)
    if include_followup:
        counts = overview["counts"]
        report.text(
            f"Pares distintos: {overview['pairs']} | Comparables: {counts.get('comparable', 0)} | "
            f"Solo visuales: {counts.get('visual', 0)} | No evaluables: {counts.get('rejected', 0)} | "
            f"Por actualizar: {counts.get('outdated', 0)}.\n"
            "Cada par se cuenta una vez, usando su último resultado guardado. No evaluable no significa sin cambio."
        )
        # The common summary also includes the latest individual score. Keep this
        # technical score in the appendix instead of the main reading path.
        summary_records = [
            dict(record, metadata=dict(record.get("metadata", {}), classification={
                k: v for k, v in (record.get("metadata", {}).get("classification") or {}).items()
                if k != "score"
            })) for record in records
        ]
        report.text(selected_followup_summary(comparisons, summary_records, trend_mode)
                    if reference_id == records[0]["id"] or trend_mode == "consecutive"
                    else followup_summary(comparisons, summary_records, reference_id).replace("\n\n", "\n"))
    else:
        report.text(
            "Este informe incluye únicamente las fotografías seleccionadas y sus resultados individuales."
            + (" También incluye el resultado del par elegido." if chosen else "")
            + " No incluye una conclusión del seguimiento completo de la lesión."
        )
    report.text("Cómo interpretar los resultados", size=11)
    report.text(
        "La clasificación es experimental y puede ser benigna, maligna o no concluyente. Sus puntuaciones son salidas del modelo, no probabilidades clínicas.\n"
        "El índice descriptivo resume diferencias entre imágenes en una escala heurística de 0 a 100. No mide gravedad, curación ni riesgo de cáncer.\n"
        "El área es aparente: se mide sobre píxeles después de alinear. No representa tamaño en mm² sin una referencia física de escala.\n"
        "Las comparaciones solo visuales y las fechas modificadas se identifican en la tabla, pero no se usan como evidencia de evolución."
    )
    first_table_height = 0.045 * (min(len(records), 8) + 1)
    if report.y - first_table_height - 0.06 < 0.09:
        report.page("Fotografías y análisis disponibles")
    report.text("Fotografías y análisis disponibles", size=11)
    summary = []
    for record in records:
        photo_state, _, _ = report_photo_state(record)
        summary.append(
            [
                date_label(record["captured_at"]),
                photo_state,
            ]
        )
    # Paginate arbitrary histories rather than shrinking the whole report.
    for offset in range(0, len(summary), 8):
        chunk = summary[offset : offset + 8]
        report.table(
            ["Fecha de captura", "Resultado guardado"],
            chunk,
            [24, 58],
            height=0.045 * (len(chunk) + 1),
            fontsize=8,
        )
    for offset in range(0, len(records), 2):
        report.page("Fotografías y resultados experimentales")
        if include_explanations:
            report.text(
                "Verde/amarillo: menor/mayor intensidad de influencia. Naranja/azul: apoyo/oposición a la clase en mapas guardados anteriores. Sin color: señal pequeña. No delimitan tejido maligno.",
                size=8,
                width=107,
            )
        for record in records[offset : offset + 2]:
            photo, mask = store.load_images(record)
            analysis = record["metadata"].get("classification", {})
            # Keep each photo with its date and result even when notes require an extra page.
            if report.y < 0.43:
                report.page("Fotografías y resultados experimentales - continuación")
            report.text("Captura: " + date_label(record["captured_at"]), size=10)
            photo_state, photo_action, photo_current = report_photo_state(record)
            report.text(photo_state + "\n" + photo_action)
            identity = record.get("metadata", {}).get("lesion_identity", {})
            report.text(
                "Identidad: misma lesión declarada por el usuario; no verificada automáticamente."
                if identity.get("status") == "user_declared" else
                "Identidad: primera fotografía registrada de esta lesión."
                if identity.get("status") == "initial_reference" else
                "Identidad: no hay constancia de confirmación de la misma lesión.",
                size=8, width=107,
            )
            secondary = mask_overlay(photo, mask)
            caption = "Región marcada por el usuario"
            if include_explanations and photo_current and analysis.get("explanation"):
                # Integrity failures abort export instead of silently publishing a damaged artifact.
                secondary = store.load_explanation(record["id"])
                caption = "Mapa de influencia del clasificador"
                from explainability import METHOD

                stats = analysis.get("explanation_diagnostics", {})
                caption = (
                    "Influencia · verde / amarillo"
                    if stats.get("display_mode") == "magnitude-green-yellow"
                    else "Influencia · naranja / azul"
                )
                if stats.get("method") != METHOD:
                    report.text(
                        "Mapa guardado con método anterior: recalcular para aplicar la leyenda actual.",
                        size=8,
                        width=107,
                    )
                elif not stats.get("informative"):
                    report.text(
                        "Sin señal suficiente: las oclusiones apenas cambiaron la salida del modelo.",
                        size=8,
                        width=107,
                    )
                elif stats.get("background_dominant"):
                    report.text(
                        "Mayor influencia media fuera del contorno: revisar encuadre y respuesta al fondo.",
                        size=8,
                        width=107,
                    )
            elif include_explanations:
                report.text(
                    "Mapa de influencia no disponible: "
                    + (
                        ("repite el análisis para obtener un resultado vigente." if not photo_current and analysis.get("explanation") else None)
                        or analysis.get("explanation_error")
                        or "no hay explicación guardada; se genera al obtener una clase válida."
                    ),
                    size=8,
                    width=107,
                )
            if record["metadata"].get("note"):
                report.text(
                    "Observación: " + str(record["metadata"]["note"])[:350],
                    size=8,
                    width=107,
                )
            notes = record["metadata"].get("visit_notes", {})
            if notes:
                titles = dict(itch="Picazón", bleeding="Sangrado", pain="Dolor", evolution="Evolución percibida", sun="Exposición solar", observation="Observación profesional", tags="Etiquetas", author="Autor declarado")
                report.text("Notas de la visita:\n" + "\n".join(titles[key] + ": " + value for key, value in notes.items() if key in titles and value), size=8, width=107)
            report.images(
                [(photo, "Original · " + date_label(record["captured_at"])),
                 (secondary, caption + "\n" + date_label(record["captured_at"]))]
                if include_explanations else
                [(photo, "Fotografía original · " + date_label(record["captured_at"]))], height=0.22
            )
    if chosen:
        result = chosen["result"]
        report.page("Comparación seleccionada: mediciones y mapa")
        report.text(
            date_label(chosen["live_previous_date"])
            + " → "
            + date_label(chosen["live_current_date"])
            + "\nEstado: "
            + chosen_state["label"],
            size=10,
        )
        report.text(
            chosen_state["reason"] + "\nSiguiente paso: " + chosen_state["action"]
        )
        if chosen_state["kind"] in ("comparable", "visual"):
            report.text(comparison_conclusion(result))
            report.table(
                ["Característica", "Anterior", "Actual", "Diferencia", "Interpretación"],
                measurement_rows(result),
                [16, 14, 14, 15, 33],
                height=0.30,
                fontsize=8,
            )
        else:
            report.text("Mediciones omitidas: no existe una comparación vigente y evaluable. No se asigna cero ni se reutilizan valores históricos.")
        available = chosen_state["show_map"]
        if available:
            with Image.open(store.path(chosen["overlay"])) as source:
                overlay = source.convert("RGB")
            if (
                result.get("comparable")
                and result.get("registration", {}).get("matrix") is not None
            ):
                from longitudinal_analysis import normalized
                from longitudinal_views import aligned_detail

                a = store.record(chosen["previous_id"])
                b = store.record(chosen["current_id"])
                photo_a, mask_a = store.load_images(a)
                photo_b, mask_b = store.load_images(b)
                _, mask_a = normalized(photo_a, mask_a)
                _, mask_b = normalized(photo_b, mask_b)
                overlay = aligned_detail(
                    overlay,
                    Image.fromarray(mask_a.astype("uint8") * 255),
                    Image.fromarray(mask_b.astype("uint8") * 255),
                    result["registration"]["matrix"],
                )
            report.images(
                [
                    (
                        overlay,
                        (
                            "Diferencias de imágenes alineadas\n" + date_label(chosen["live_previous_date"]) + " → " + date_label(chosen["live_current_date"])
                            if result.get("comparable")
                            else "Diferencias entre siluetas normalizadas"
                        ),
                    )
                ],
                height=0.27,
            )
            report.text(
                (
                    "Cian: contorno anterior. Naranja: actual. Colores cálidos: mayor diferencia de color entre imágenes alineadas."
                    if result.get("comparable")
                    else "Gris: silueta común. Cian: solo la imagen A. Naranja: solo la imagen B. No representa crecimiento."
                ),
                size=8,
                width=107,
            )
        else:
            report.text(
                "Mapa no incluido: "
                + (
                    chosen_invalid + "."
                    if chosen_invalid
                    else "comparación no evaluable. "
                    + next(iter(result.get("warnings", [])), "")
                )
            )
    if include_followup and comparisons:
        report.page("Tablero de evolución de las fotografías")
        index_series = series if metric == "index" else trend_series(comparisons, records, reference_id, "index", mode=trend_mode)
        report.text(
            "Modo: " + ("cada visita respecto a la primera fotografía incluida" if trend_mode == "reference" else "intervalos entre visitas consecutivas")
            + "\nMedición: índice descriptivo\n" + trend_note(index_series), size=9
        )
        if len(index_series["points"]) >= 2:
            chart = trend_figure(index_series, size=(7.2, 3.2))
            chart.canvas.draw()
            image = Image.frombytes(
                "RGBA", chart.canvas.get_width_height(), bytes(chart.canvas.buffer_rgba())
            )
            report.images(
                [(image, "Línea de tiempo respecto a una misma referencia" if trend_mode == "reference" else "Comparaciones entre visitas consecutivas")], height=0.30
            )
        else:
            report.text("Gráfico omitido: hay menos de dos mediciones válidas. Las fotografías y los motivos de comparación no evaluable aparecen en el informe.")
        report.text(
            ("Mayor índice: mayor diferencia visual respecto " + ("al inicio" if trend_mode == "reference" else "a la visita anterior") + ". Menor índice: menor diferencia. ")
            + "No implica mejoría o empeoramiento clínico. "
            + ("Inicio: 0 por definición, no una medición adicional." if trend_mode == "reference" else "Cada intervalo se interpreta por separado; no es una distancia acumulada desde el inicio."),
            size=8,
            width=107,
        )
        points = index_series["points"]
        if points:
            values = [p["value"] for p in points]
            report.text(
                f"Mediciones válidas: {len(points)} | Mínimo: {min(values):.3f} | Máximo: {max(values):.3f}\nUnidad: {METRICS['index'][1]}.\n"
                "Estos valores resumen las comparaciones disponibles; no son estadísticas de precisión clínica.",
                size=9,
            )
        rows = []
        for c, state in overview["states"]:
            value = state["value"]
            rows.append(
                [
                    date_label(c["live_previous_date"])
                    + " → "
                    + date_label(c["live_current_date"]),
                    (
                        "—" if value is None else f"{value:.2f}"
                    ),
                    (
                        state["label"]
                    ),
                ]
            )
        for offset in range(0, len(rows), 8):
            chunk = rows[offset : offset + 8]
            report.table(
                ["Fechas comparadas", "Índice temporal / 100", "Estado"],
                chunk,
                [40, 14, 32],
                height=0.05 * (len(chunk) + 1),
                fontsize=8,
            )
        if overview["reasons"]:
            report.text("Motivos para no reportar cambio temporal (último resultado por par):", size=10)
            for reason, count in sorted(overview["reasons"].items()):
                report.text(f"{count} par/es: {reason}")
    if detailed:
        from longitudinal_reports import audit_lesion

        if include_followup and comparisons:
            from followup_charts import followup_figure
            report.page("Anexo: gráficos del seguimiento")
            report.text("Los gráficos muestran únicamente mediciones vigentes. Área aparente en imágenes, no tamaño físico. El índice no mide gravedad ni riesgo clínico.")
            dashboard = followup_figure(comparisons, records, reference_id, trend_mode, size=(8, 6))
            dashboard.canvas.draw()
            graph = Image.frombytes("RGBA", dashboard.canvas.get_width_height(), bytes(dashboard.canvas.buffer_rgba()))
            report.images([(graph, "Referencia inicial" if trend_mode == "reference" else "Intervalos consecutivos")], height=0.57)

        report.page("Anexo: controles técnicos y revisión de datos")
        report.text(
            "Este anexo revisa toda la lesión, incluso registros fuera del alcance de las fotografías seleccionadas.\n"
            + audit_lesion(store, lesion_id)
        )
        report.page("Anexo: trazabilidad de fotografías incluidas")
        report.text("Las puntuaciones son salidas experimentales del modelo; no representan probabilidades clínicas. Los identificadores permiten localizar el resultado original sin recalcularlo.")
        for record in records:
            analysis = record.get("metadata", {}).get("classification") or {}
            state, action, current = report_photo_state(record)
            report.text(f"Captura: {date_label(record['captured_at'])} | ID: {record['id']}\nEstado: {state}")
            if current:
                report.text(classification_text(analysis))
            else:
                report.text(action)
            if record.get("sha256"):
                report.text("SHA-256 fotografía: " + record["sha256"], size=8, width=107)
            if record.get("mask_sha256"):
                report.text("SHA-256 contorno: " + record["mask_sha256"], size=8, width=107)
            for key, label in (("model_sha256", "Modelo SHA-256"), ("analyzed_at", "Fecha de análisis")):
                if analysis.get(key):
                    report.text(label + ": " + str(analysis[key]), size=8, width=107)
        if chosen:
            report.page("Anexo: calidad de la comparación")
            report.text(
                "\n\n".join(
                    k + ": " + v
                    for k, v in quality_rows(
                        chosen["result"], all_records, chosen.get("stale_dates", False)
                    )
                )
            )
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name(destination.name + ".tmp")
    try:
        with PdfPages(temp) as pdf:
            for fig in report.figures:
                pdf.savefig(fig)
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    if preview_dir:
        preview_dir = Path(preview_dir)
        preview_dir.mkdir(parents=True, exist_ok=True)
        for i, fig in enumerate(report.figures):
            fig.savefig(preview_dir / f"pagina-{i+1}.png", dpi=110)
    return len(report.figures)
