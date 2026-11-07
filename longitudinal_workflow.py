"""Acciones de usuario sobre la ficha y la selección explícita de fotografías."""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from ui_theme import BACKGROUND, INK


class WorkflowMixin:
    def apply_history_filters(self):
        from longitudinal_insights import date_label
        from longitudinal_reports import report_comparison_state, report_photo_state
        def parsed(value):
            if not value.strip():
                return None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(value.strip(), fmt).date()
                except ValueError:
                    continue
            raise ValueError("Escribe las fechas como DD/MM/AAAA.")
        try:
            start, end = parsed(self.history_from.get()), parsed(self.history_to.get())
            if start and end and start > end:
                raise ValueError("La fecha inicial debe ser anterior o igual a la final.")
        except ValueError as exc:
            self.status.set(str(exc))
            return
        state, kind = self.history_state.get(), self.history_type.get()
        def within(value):
            day = datetime.fromisoformat(value).date()
            return (start is None or day >= start) and (end is None or day <= end)
        self.history.delete(*self.history.get_children())
        self.comparisons.delete(*self.comparisons.get_children())
        for record in self.records:
            analysis = record.get("metadata", {}).get("classification", {})
            title, _, _ = report_photo_state(record)
            category = {"accepted": "Aceptada", "uncertain": "No concluyente", "rejected": "Rechazada", "quality_failed": "Rechazada"}.get(analysis.get("state"), "Pendiente")
            if title == "Requiere actualizarse":
                category = "Recalcular"
            if kind != "Comparaciones" and within(record["captured_at"]) and state in ("Todos los estados", category):
                self.history.insert("", "end", iid=record["id"], values=(record["label"], date_label(record["captured_at"]), title))
        for row in self.saved_comparisons:
            result = report_comparison_state(row, self.records)
            category = {"comparable": "Comparable", "outdated": "Recalcular", "visual": "Solo visual", "rejected": "No evaluable"}[result["kind"]]
            previous = row.get("live_previous_date", row["result"].get("previous_date"))
            current = row.get("live_current_date", row["result"].get("current_date"))
            if kind != "Fotografías" and current and within(current) and state in ("Todos los estados", category):
                self.comparisons.insert("", "end", iid=row["id"], values=(date_label(previous) + " → " + date_label(current), "—" if result["value"] is None else f"{result['value']:.1f}", result["label"]))
        self.select_comparison()

    def return_to_person(self):
        self.navigate(2)
        self.open_person()

    def edit_history_date(self):
        selected = self.history.selection()
        if selected:
            self.edit_visit_date(selected[0])

    def toggle_chart(self):
        if self.chart_toggle.get():
            self.chart_heading.pack(anchor="w", padx=12, pady=(8, 0))
            self.chart.pack(fill="x", padx=8)
            self.chart_note.pack(anchor="w", padx=12, pady=8)
            self.draw_timeline()
        else:
            self.chart.pack_forget()
            self.chart_heading.pack_forget()
            self.chart_note.pack_forget()
            self.draw_timeline()

    def refresh_comparison_table(self):
        from longitudinal_reports import report_comparison_state
        if not hasattr(self, "timeline_table"):
            return
        self.timeline_table.configure(
            height=max(1, min(5, len(self.saved_comparisons)))
        )
        self.timeline_table.delete(*self.timeline_table.get_children())
        for row in self.saved_comparisons:
            result = row["result"]
            display = report_comparison_state(row, self.records)
            visual = result.get("mode") == "visual"
            value = result.get("visual_index") if visual else result.get("change_index")
            state = (
                "Recalcular fecha"
                if row.get("stale_dates")
                else (
                    "Solo visual"
                    if visual
                    else (
                        "Ajuste aceptado"
                        if result.get("comparable")
                        else "No evaluable"
                    )
                )
            )
            try:
                dates = (
                    datetime.fromisoformat(
                        row.get("live_previous_date", result.get("previous_date", ""))
                    ).strftime("%d/%m/%Y %H:%M")
                    + " → "
                    + datetime.fromisoformat(
                        row.get("live_current_date", result.get("current_date", ""))
                    ).strftime("%d/%m/%Y %H:%M")
                )
            except ValueError:
                dates = "Fechas no disponibles"
            self.timeline_table.insert(
                "",
                "end",
                values=(
                    dates,
                    "—" if display["value"] is None else f"{display['value']:.1f}",
                    display["label"],
                ),
            )

    def update_context(self):
        person = next(
            (p for p in self.person_rows if p["code"] == self.patient_choice.get()),
            None,
        )
        lesion = next((l for l in self.lesions if l["id"] == self.lesion_id), None)
        name = (
            (person["name"] or person["code"]) if person else "Selecciona una persona"
        )
        self.context_label.configure(
            text=(
                f"{name}  ›  {lesion['name']} · {lesion['site'] or 'Zona no indicada'}"
                if lesion
                else name
            )
        )
        self.history_context.configure(text=self.context_label.cget("text"))
        if hasattr(self, "lesion_overview"):
            from longitudinal_review import visit_review_rows
            rows = visit_review_rows(self.saved_comparisons, self.records, self.selected_trend_mode())
            available = sum(r["state"] == "available" for r in rows)
            review = sum(r["state"] in ("invalid", "stale", "pending") for r in rows)
            from longitudinal_insights import date_label
            dates = sorted(r["captured_at"] for r in self.records)
            self.lesion_overview.configure(text=(
                f"{person['code'] if person else ''} · {lesion['name'] if lesion else 'Sin lesión seleccionada'} · {lesion['site'] or 'Zona no indicada' if lesion else ''}\n"
                + (f"{len(dates)} fotografías · {available} pares disponibles · {review} por revisar\nPrimera: {date_label(dates[0])} · Última: {date_label(dates[-1])}" if dates else "Registra la primera fotografía para iniciar el seguimiento.")))

    def filter_people(self, *_):
        if not hasattr(self, "person_rows"):
            return
        query = self.person_search.get().strip().casefold()
        self.person_list.delete(*self.person_list.get_children())
        for row in self.person_rows:
            if query and query not in (row["code"] + " " + row["name"]).casefold():
                continue
            self.person_list.insert(
                "",
                "end",
                iid=row["id"],
                values=(row["code"], row["name"], row["lesion_count"], row["notes"]),
            )
        selected = next(
            (p for p in self.person_rows if p["code"] == self.patient_choice.get()),
            None,
        )
        if selected and self.person_list.exists(selected["id"]):
            self.person_list.selection_set(selected["id"])

    def open_person(self):
        if self.running or self.app.busy:
            self.status.set(
                "Espera a que termine el análisis antes de abrir otra ficha."
            )
            return
        selected = self.person_list.selection()
        if not selected:
            self.status.set("Selecciona una persona para abrir su ficha.")
            return
        self.select_person()
        row = self.store.person(selected[0])
        self.person_heading.configure(
            text="Lesiones de " + (row["name"] or row["code"])
        )
        self.person_panel.pack_forget()
        self.lesion_panel.pack(fill="both", expand=True, padx=18, pady=10)

    def back_to_people(self):
        self.lesion_panel.pack_forget()
        self.person_panel.pack(fill="both", expand=True, padx=18, pady=10)

    def edit_current_person(self):
        if not self.idle_for_management():
            return
        row = next(
            (p for p in self.person_rows if p["code"] == self.patient_choice.get()),
            None,
        )
        if row:
            self.person_dialog(row["id"])

    def cancel_auto_comparison(self):
        job = getattr(self, "auto_compare_job", None)
        if job:
            try:
                self.window.after_cancel(job)
            except tk.TclError:
                pass
            self.auto_compare_job = None

    def request_auto_comparison(self, force=False):
        self.cancel_auto_comparison()
        if (
            self.closed
            or self.workspace_mode != "compare"
            or self.comparison_mode_key() != "longitudinal"
            or len(self.selected_photo_ids) != 2
        ):
            return
        selection = tuple(self.selected_photo_ids)
        lesion_id = self.lesion_id

        def start():
            self.auto_compare_job = None
            if (
                self.closed
                or lesion_id != self.lesion_id
                or selection != tuple(self.selected_photo_ids)
            ):
                return
            if self.running or getattr(self, "followup_pending", []):
                return
            if self.app.busy:
                self.auto_compare_job = self.window.after(500, start)
                return
            self.run_auto_comparison(selection, force)

        # Let consecutive clicks finish before starting a background analysis.
        self.auto_compare_job = self.window.after(350, start)

    def cached_followup(self, a, b):
        previous, current = self.store.record(a), self.store.record(b)
        model_ready = self.app.model is not None and self.app.domain_gate is not None
        expected_model = None
        expected_calibration = None
        if model_ready:
            import hashlib

            path = self.app.experiment_folder / "model.keras"
            if path.is_file():
                signature = (str(path), path.stat().st_size, path.stat().st_mtime_ns)
                if getattr(self, "_automatic_model_signature", None) != signature:
                    self._automatic_model_hash = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
                    self._automatic_model_signature = signature
                expected_model = self._automatic_model_hash
            calibration = self.app.calibration
            if calibration is not None:
                expected_calibration = {
                    key: getattr(calibration, key)
                    for key in (
                        "slope",
                        "intercept",
                        "threshold",
                        "uncertain_low",
                        "uncertain_high",
                        "source",
                    )
                }
        for row in reversed(self.store.comparisons(self.lesion_id)):
            result = row["result"]
            if row["previous_id"] != a or row["current_id"] != b:
                continue
            from longitudinal_store import readable_comparison_map

            if not readable_comparison_map(self.store.path(row["overlay"])):
                continue
            from longitudinal_insights import comparison_validity

            if comparison_validity(row, (previous, current)) is not None:
                continue
            if result.get(
                "requested_mode", result.get("mode")
            ) != "longitudinal" and not (
                previous["captured_at"] == current["captured_at"]
                and result.get("mode") == "visual"
            ):
                continue
            if model_ready and result.get("model_sha256") != expected_model:
                continue
            if any(
                result.get(key) != value
                for key, value in (
                    ("previous_date", previous["captured_at"]),
                    ("current_date", current["captured_at"]),
                    ("previous_sha256", previous["sha256"]),
                    ("current_sha256", current["sha256"]),
                    ("previous_mask_sha256", previous["mask_sha256"]),
                    ("current_mask_sha256", current["mask_sha256"]),
                )
            ):
                continue
            usable = True
            for record, key in (
                (previous, "previous_classification"),
                (current, "current_classification"),
            ):
                saved = result.get(key, {})
                latest = record["metadata"].get("classification")
                if model_ready and saved.get("state") == "unavailable":
                    usable = False
                if (
                    model_ready
                    and saved.get("state") in ("accepted", "uncertain")
                    and saved.get("calibration") != expected_calibration
                ):
                    usable = False
                if latest and any(
                    saved.get(field) != latest.get(field)
                    for field in ("state", "raw_score", "model_sha256", "calibration")
                ):
                    usable = False
            if usable:
                return row
        return None

    def run_auto_comparison(self, selection, force=False):
        import threading
        from longitudinal_analysis import compare_records

        records = {r["id"]: r for r in self.records}
        if len(selection) != 2:
            return
        if any(i not in records for i in selection):
            return
        ordered = sorted(selection, key=lambda i: (records[i]["captured_at"], i))
        final = (ordered[0], ordered[1])
        if final[0] == final[1]:
            return
        same_date = records[final[0]]["captured_at"] == records[final[1]]["captured_at"]
        # A pair comparison never analyzes a third, unselected photograph.
        pairs = [final]
        cached = {pair: self.cached_followup(*pair) for pair in pairs}
        missing = [pair for pair in pairs if force or cached[pair] is None]
        if not missing:
            self.display_auto_comparison(cached[final]["id"], selection)
            return
        self.running = True
        self.app.busy = True
        self.active_lesion_id = self.lesion_id
        self.status.set(
            "Analizando únicamente estas dos fotografías y preparando su mapa de diferencias…"
        )
        self.compare_button.configure(state="disabled")
        self.refresh_thumbnails()
        model, gate = self.app.model, self.app.domain_gate
        extractor = getattr(self.app.reference_index, "extractor", None)
        model_path = self.app.experiment_folder / "model.keras"
        calibration = self.app.calibration
        lesion_id = self.lesion_id

        def run():
            try:
                identifiers = {pair: row["id"] for pair, row in cached.items() if row}
                for pair in missing:
                    identifiers[pair] = compare_records(
                        self.store,
                        *pair,
                        model,
                        gate,
                        extractor,
                        model_path,
                        calibration,
                        mode="visual" if same_date else "longitudinal",
                        fallback_visual=True,
                        requested_mode="longitudinal",
                    )["id"]
                self.queue.put(
                    (
                        "auto_followup",
                        dict(
                            comparison_id=identifiers[final],
                            selection=selection,
                            lesion_id=lesion_id,
                        ),
                    )
                )
            except Exception as exc:
                self.queue.put(("auto_followup_error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def display_auto_comparison(self, identifier, selection):
        self.refresh_history()
        self.comparisons.selection_set(identifier)
        self.restore_comparison()
        self.selected_photo_ids = list(selection)
        self.refresh_thumbnails()
        self.draw_timeline()
        self.refresh_workspace_layout()
        self.status.set(
            "Comparación automática lista. Puedes seleccionar otra fotografía para continuar el seguimiento."
        )

    def clear_photo_selection(self):
        if self.running or self.app.busy:
            return
        self.cancel_auto_comparison()
        self.selected_photo_ids = []
        self.clear_output()
        self.refresh_thumbnails()
        self.status.set(
            "Selección borrada. Puedes elegir otras fotografías de esta lesión."
        )

    def selected_photo_action(self, action):
        if len(self.selected_photo_ids) != 1:
            self.status.set("Selecciona una sola fotografía para esta acción.")
            return
        identifier = self.selected_photo_ids[0]
        if action == "view":
            self.show_visit(identifier)
        elif action == "notes":
            self.edit_visit_notes()
        elif action == "date":
            self.edit_visit_date(identifier)
        elif action == "delete":
            self.delete_photo(identifier)
        elif action == "classify":
            self.displayed_record_id = identifier
            self.classify_visit()

    def compare_selected(self):
        self.cancel_auto_comparison()
        if len(self.selected_photo_ids) != 2:
            self.status.set("Selecciona dos fotografías de esta lesión para comparar.")
            return
        self.comparison_mode.current(0)
        self.refresh_pair_choices()
        ordered = sorted(
            self.selected_photo_ids, key=lambda i: self.store.record(i)["captured_at"]
        )
        for widget, identifier in zip((self.previous, self.current), ordered):
            widget.current(
                next(
                    n for n, r in enumerate(self.pair_records) if r["id"] == identifier
                )
            )
        self.compare()

    def select_comparison(self, event=None):
        selected = self.comparisons.selection()
        state = "normal" if selected else "disabled"
        self.view_comparison_button.configure(state=state)
        self.remove_comparison_button.configure(state=state)
        if selected and self.tabs.index("current") == 1:
            self.status.set(
                "Comparación seleccionada. Pulsa Ver resultado para abrirla o Eliminar para retirarla."
            )

    def open_comparison_tools(self):
        dialog = tk.Toplevel(self.window)
        dialog.title("Comparación visual de prueba")
        dialog.transient(self.window)
        dialog.grab_set()
        tk.Label(
            dialog,
            text="Compara imágenes de las lesiones de la persona seleccionada.\nEste modo describe diferencias visuales; no representa evolución.",
            bg=BACKGROUND,
            fg=INK,
            justify="left",
            padx=18,
            pady=15,
        ).pack(fill="x")
        choices = []
        rows = []
        for lesion in self.store.lesions():
            if lesion["patient"] == self.patient_choice.get():
                for record in self.store.records(lesion["id"]):
                    rows.append(record)
                    choices.append(
                        lesion["name"]
                        + " · "
                        + datetime.fromisoformat(record["captured_at"]).strftime(
                            "%d/%m/%Y %H:%M"
                        )
                    )
        fields = []
        for title in ("Primera fotografía", "Segunda fotografía"):
            ttk.Label(dialog, text=title).pack(anchor="w", padx=18)
            field = ttk.Combobox(dialog, values=choices, state="readonly", width=55)
            field.pack(fill="x", padx=18, pady=(0, 12))
            fields.append(field)

        def run():
            a, b = (field.current() for field in fields)
            if min(a, b) < 0 or a == b:
                messagebox.showinfo(
                    "Selección", "Elige dos fotografías diferentes.", parent=dialog
                )
                return
            self.comparison_mode.current(1)
            self.refresh_pair_choices()
            for widget, identifier in zip(
                (self.previous, self.current), (rows[a]["id"], rows[b]["id"])
            ):
                widget.current(
                    next(
                        n
                        for n, r in enumerate(self.pair_records)
                        if r["id"] == identifier
                    )
                )
            dialog.destroy()
            self.navigate(0)
            self.on_pair_selected()
            self.compare()

        ttk.Button(dialog, text="Comparar imágenes", command=run).pack(padx=18, pady=12)

    def capture_in_lesion(self):
        self.start_photo_registration(source="camera")
