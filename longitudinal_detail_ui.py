"""Mapa por fotografía, tablero temporal y ventana de interpretación."""

import tkinter as tk
import threading
from tkinter import ttk
from PIL import Image, ImageOps, ImageTk
from longitudinal_insights import (
    date_label,
    measurement_rows,
    comparison_narrative,
    quality_rows,
    trend_series,
    trend_figure,
    trend_direction,
    followup_summary,
    comparison_validity,
)
from longitudinal_dashboard import card, text, action
from ui_theme import SURFACE, INK, MUTED, BACKGROUND


class DetailMixin:
    def build_photo_analysis(self, parent):
        self.photo_analysis_card = card(
            parent, "Influencia por oclusión de la fotografía"
        )
        self.photo_analysis_card.pack(fill="x", padx=18, pady=10)
        controls = tk.Frame(self.photo_analysis_card, bg=SURFACE)
        controls.pack(fill="x", padx=12, pady=8)
        self.heatmap_choice = ttk.Combobox(controls, state="readonly", width=36)
        self.heatmap_choice.pack(side="left", fill="x", expand=True)
        self.heatmap_choice.bind(
            "<<ComboboxSelected>>", lambda e: self.render_photo_analysis()
        )
        self.heatmap_button = action(
            controls, "Generar explicación visual", self.generate_photo_explanation
        )
        self.heatmap_button.pack(side="left", padx=8)
        action(controls, "Abrir mapa de influencia", self.open_photo_explanation).pack(
            side="right"
        )
        self.heatmap_overlay = tk.BooleanVar(master=self.window, value=True)
        # Original remains beside the map; a second show/hide control is redundant.
        view_row = tk.Frame(self.photo_analysis_card, bg=SURFACE)
        view_row.pack(fill="x", padx=12, pady=(4, 0))
        text(view_row, "Vista:", 9, MUTED).pack(side="left", padx=(0, 6))
        self.heatmap_view = ttk.Combobox(
            view_row,
            state="readonly",
            width=42,
            values=(
                "Influencia completa del modelo",
                "Influencia dentro del contorno revisado",
            ),
        )
        self.heatmap_view.current(0)
        text(view_row, "Mapa completo", 9, MUTED).pack(side="left")
        self.heatmap_contour = tk.BooleanVar(master=self.window, value=False)
        tk.Checkbutton(view_row, text="Mostrar contorno revisado", variable=self.heatmap_contour,
                       command=self.render_photo_analysis, bg=SURFACE).pack(side="left", padx=10)
        self.heatmap_opacity = ttk.Scale(view_row, from_=0, to=1, value=1,
                                        command=lambda value: self.render_photo_analysis())
        text(view_row, "Intensidad:", 9, MUTED).pack(side="left")
        self.heatmap_opacity.pack(side="left", fill="x", expand=True)
        self.heatmap_view.bind(
            "<<ComboboxSelected>>", lambda e: self.render_photo_analysis()
        )
        legend = tk.Frame(self.photo_analysis_card, bg=SURFACE)
        legend.pack(fill="x", padx=12, pady=(6, 0))
        for color, label in [
            ("#ffffff", "Contorno revisado (blanco)"),
            ("#2aba6a", "Menor influencia"),
            ("#ffdd30", "Mayor influencia del modelo"),
        ]:
            item = tk.Frame(legend, bg=SURFACE)
            item.pack(side="left", padx=(0, 14))
            tk.Label(item, bg=color, width=2, height=1).pack(side="left", padx=(0, 5))
            text(item, label, 9, MUTED).pack(side="left")
        self.heatmap_text = text(
            self.photo_analysis_card,
            "",
            10,
            MUTED,
            justify="left",
            anchor="w",
            wraplength=750,
        )
        self.heatmap_text.pack(fill="x", padx=12, pady=8)
        self.photo_analysis_card.bind(
            "<Configure>",
            lambda e: self.heatmap_text.configure(wraplength=max(200, e.width - 30)),
        )
        pictures = tk.Frame(self.photo_analysis_card, bg=SURFACE)
        pictures.pack(fill="x", padx=12, pady=8)
        self.heatmap_pictures = []
        self.heatmap_captions = []
        for i, caption in enumerate(
            ("Fotografía original", "Mapa de influencia por oclusión")
        ):
            pictures.columnconfigure(i, weight=1, uniform="heat")
            frame = tk.Frame(pictures, bg=SURFACE, height=300, width=1)
            frame.grid(row=0, column=i, sticky="ew")
            frame.pack_propagate(False)
            label = text(frame, caption, 10, INK, True)
            label.pack()
            self.heatmap_captions.append(label)
            image = tk.Label(frame, bg=SURFACE)
            image.pack(expand=True)
            self.heatmap_pictures.append(image)
        self.heatmap_ids = []
        self.photo_analysis_card.pack_forget()

    def sync_photo_analysis(self):
        ids = [
            i
            for i in self.selected_photo_ids
            if any(r["id"] == i for r in self.records)
        ]
        if not ids and self.current_result:
            ids = [
                self.current_result["previous_id"],
                self.current_result["current_id"],
            ]
        active = []
        for identifier in ids:
            try:
                if self.store.record(identifier)["lesion_id"] == self.lesion_id:
                    active.append(identifier)
            except ValueError:
                pass
        ids = active
        if not ids:
            self.photo_analysis_card.pack_forget()
            return
        old = (
            self.heatmap_ids[self.heatmap_choice.current()]
            if 0 <= self.heatmap_choice.current() < len(self.heatmap_ids)
            else None
        )
        self.heatmap_ids = sorted(
            ids, key=lambda i: self.store.record(i)["captured_at"]
        )
        self.heatmap_choice["values"] = [
            (
                "Foto anterior · "
                if n == 0 and len(self.heatmap_ids) == 2
                else "Foto posterior · " if len(self.heatmap_ids) == 2 else ""
            )
            + date_label(self.store.record(i)["captured_at"])
            for n, i in enumerate(self.heatmap_ids)
        ]
        self.heatmap_choice.current(
            self.heatmap_ids.index(old)
            if old in self.heatmap_ids
            else len(self.heatmap_ids) - 1
        )
        self.photo_analysis_card.pack(fill="x", padx=18, pady=10)
        self.render_photo_analysis()
        self.refresh_workspace_layout()

    def heatmap_record_id(self):
        n = self.heatmap_choice.current()
        return self.heatmap_ids[n] if 0 <= n < len(self.heatmap_ids) else None

    def render_photo_analysis(self):
        identifier = self.heatmap_record_id()
        if not identifier:
            return
        record = self.store.record(identifier)
        analysis = record["metadata"].get("classification", {})
        from longitudinal_analysis import classification_text
        from explainability import explanation_caption

        self.heatmap_sources = []
        try:
            original, mask = self.store.load_images(record)
            self.heatmap_sources.append(original)
            if analysis.get("explanation"):
                from explainability import influence_view

                saved_overlay = self.store.load_explanation(identifier)
                self.heatmap_sources.append(
                    influence_view(original, saved_overlay, mask,
                                   opacity=self.heatmap_opacity.get(),
                                   contour=self.heatmap_contour.get())
                )
                message = explanation_caption(analysis.get("explanation_diagnostics"))
                stats = analysis.get("explanation_diagnostics", {})
                status = ("Influencia predominante fuera de la región." if stats.get("background_dominant")
                          else "Influencia concentrada en la región marcada." if stats.get("region_focused")
                          else "Influencia dispersa." if stats.get("informative")
                          else "Concentración no determinada.")
                message = status + " " + message
                if (
                    analysis.get("explanation_diagnostics", {}).get("display_mode")
                    != "magnitude-green-yellow"
                ):
                    message += " Este mapa guardado conserva su leyenda original. Recalcular explicación genera la nueva vista verde y amarilla."
            else:
                message = (
                    "La clasificación está disponible, pero falta su mapa. Puedes generarlo de nuevo."
                    if analysis.get("state") == "accepted"
                    else "No hay mapa. Primero usa Analizar fotografía; el mapa solo se genera si el modelo emite una clase."
                )
                if analysis.get("explanation_error"):
                    message += " Motivo: " + analysis["explanation_error"]
            self.heatmap_text.configure(text=message)
        except (ValueError, OSError) as exc:
            self.heatmap_text.configure(
                text="No se pudo abrir la explicación: " + str(exc)
            )
        self.heatmap_button.configure(
            text=(
                "Recalcular explicación"
                if analysis.get("explanation")
                else "Generar explicación visual"
            )
        )
        self.heatmap_refs = []
        self.heatmap_captions[1].configure(
            text=(
                "Mapa de influencia por oclusión"
                if self.heatmap_overlay.get()
                else "Original · superposición desactivada"
            )
        )
        for i, widget in enumerate(self.heatmap_pictures):
            widget.configure(image="", text="Mapa aún no generado" if i == 1 else "")
            if i < len(self.heatmap_sources):
                width = max(250, min(500, (self.window.winfo_width() - 290) // 2))
                source = (
                    self.heatmap_sources[0]
                    if i == 1 and not self.heatmap_overlay.get()
                    else self.heatmap_sources[i]
                )
                photo = ImageTk.PhotoImage(
                    ImageOps.contain(source, (width, 270)), master=self.window
                )
                self.heatmap_refs.append(photo)
                widget.configure(image=photo, text="")

    def generate_photo_explanation(self):
        identifier = self.heatmap_record_id()
        if identifier:
            # The dedicated choice must take priority over the comparison's current photo.
            self.classify_visit(identifier)

    def open_photo_explanation(self):
        identifier = self.heatmap_record_id()
        if identifier:
            self.show_visit_explanation(identifier)

    def build_evolution_controls(self, parent):
        self.trend_mode = ttk.Combobox(parent, state="readonly", width=56,
            values=("Referencia fija: primera foto → cada visita", "Intervalos: cada visita → la siguiente"))
        self.trend_mode.current(0)
        self.trend_mode.pack(anchor="w", padx=12, pady=(8, 0))
        self.trend_mode.bind("<<ComboboxSelected>>", lambda e: self.change_trend_mode())
        self.trend_origin = text(
            parent, "", 10, INK, True, justify="left", anchor="w", wraplength=750
        )
        self.trend_origin.pack(fill="x", padx=12, pady=8)
        self.followup_update = action(
            parent, "Calcular seguimiento", self.compare_reference_followup, True
        )
        self.followup_update.pack(anchor="w", padx=12, pady=8)
        visits_shell = tk.Frame(parent, bg=SURFACE)
        visits_shell.pack(fill="x", padx=12, pady=(0, 10))
        self.timeline_visits_canvas = tk.Canvas(visits_shell, height=252, bg=SURFACE, highlightthickness=0)
        self.timeline_visits_canvas.pack(fill="x")
        visit_scroll = ttk.Scrollbar(visits_shell, orient="horizontal", command=self.timeline_visits_canvas.xview)
        visit_scroll.pack(fill="x")
        self.timeline_visits_canvas.configure(xscrollcommand=visit_scroll.set)
        self.timeline_visits = tk.Frame(self.timeline_visits_canvas, bg=SURFACE)
        self.timeline_visits_canvas.create_window(0, 0, window=self.timeline_visits, anchor="nw")
        self.timeline_visits.bind("<Configure>", lambda e: self.timeline_visits_canvas.configure(scrollregion=self.timeline_visits_canvas.bbox("all")))
        self.timeline_review_note = text(parent, "", 10, MUTED, justify="left", wraplength=750)
        self.timeline_review_note.pack(fill="x", padx=12, pady=4)
        self.evolution_playing = False
        self.evolution_job = None
        self.evolution_position = 0
        playback = tk.Frame(parent, bg=SURFACE)
        playback.pack(fill="x", padx=12, pady=(0, 8))
        self.evolution_previous = action(playback, "◀ Anterior", lambda: self.step_evolution(-1))
        self.evolution_previous.pack(side="left")
        self.evolution_play = action(
            playback, "▶ Reproducir", self.toggle_evolution_playback
        )
        self.evolution_play.pack(side="left", padx=6)
        self.evolution_next = action(playback, "Siguiente ▶", lambda: self.step_evolution(1))
        self.evolution_next.pack(side="left")
        self.evolution_restart = action(playback, "↺ Reiniciar", self.restart_evolution)
        self.evolution_restart.pack(side="left", padx=6)
        text(playback, "Velocidad:", 9, MUTED).pack(side="left", padx=(14, 4))
        self.evolution_speed = ttk.Combobox(
            playback, state="readonly", width=8, values=("0.5 s", "1.0 s", "1.5 s", "2.0 s")
        )
        self.evolution_speed.set("1.0 s")
        self.evolution_speed.pack(side="left")
        self.playback_originals = tk.BooleanVar(master=self.window, value=True)
        tk.Checkbutton(parent, text="Reproducir originales (desmarcar: alinear con la referencia cuando sea válido)",
                       variable=self.playback_originals, bg=SURFACE,
                       command=lambda: self.step_evolution(0)).pack(anchor="w", padx=12)
        video_row = tk.Frame(parent, bg=SURFACE)
        video_row.pack(fill="x", padx=12, pady=5)
        self.video_button = action(video_row, "Exportar video de evolución (MP4)", self.export_evolution_video)
        self.video_button.pack(side="left")
        self.video_progress = ttk.Progressbar(video_row, maximum=100, length=180)
        self.video_progress.pack(side="left", padx=10)
        metric_row = tk.Frame(parent, bg=SURFACE)
        metric_row.pack(fill="x", padx=12, pady=(0, 8))
        text(metric_row, "Indicador de la línea:", 9, MUTED).pack(side="left", padx=(0, 6))
        self.trend_metric = ttk.Combobox(
            metric_row,
            state="readonly",
            width=34,
            values=tuple(label for label, key in self.trend_metric_options()),
        )
        self.trend_metric.current(0)
        self.trend_metric.pack(side="left")
        self.trend_metric.bind("<<ComboboxSelected>>", lambda e: self.change_trend_metric())
        self.build_professional_tools(parent)
        self.auto_compare_job = None
        self.followup_hint = text(
            parent, "", 10, MUTED, justify="left", anchor="w", wraplength=750
        )
        self.followup_hint.pack(fill="x", padx=12, pady=8)
        self.trend_status = text(
            parent, "", 11, INK, True, justify="left", anchor="w", wraplength=750
        )
        self.trend_status.pack(fill="x", padx=12, pady=8)
        self.followup_graph = tk.Label(parent, bg=SURFACE)
        self.followup_graph_expanded = False
        self.followup_graph_button = action(parent, "Ver gráficos detallados", self.toggle_followup_graph)
        self.followup_graph_button.pack(anchor="w", padx=12, pady=4)
        self.followup_graph_note = text(parent, "Índice: diferencia visual, no precisión ni gravedad. Área: cambio aparente en píxeles, no tamaño físico. Las barras ausentes indican que no hay medición válida.", 9, MUTED, justify="left", wraplength=750)
        parent.bind(
            "<Configure>",
            lambda e: self.trend_status.configure(wraplength=max(200, e.width - 30)),
            add="+",
        )
        parent.bind(
            "<Configure>",
            lambda e: self.followup_hint.configure(wraplength=max(200, e.width - 30)),
            add="+",
        )
        self.evolution_canvas = None

    def selected_trend_mode(self):
        return "consecutive" if hasattr(self, "trend_mode") and self.trend_mode.current() == 1 else "reference"

    def toggle_followup_graph(self):
        self.followup_graph_expanded = not self.followup_graph_expanded
        self.followup_graph_button.configure(text="Ocultar gráficos detallados" if self.followup_graph_expanded else "Ver gráficos detallados")
        if self.followup_graph_expanded:
            if not self.chart_toggle.get():
                self.chart_toggle.set(True)
                self.toggle_chart()
            self.followup_graph.pack(fill="x", padx=12, pady=8, after=self.followup_graph_button)
            self.followup_graph_note.pack(fill="x", padx=12, after=self.followup_graph)
        else:
            self.followup_graph.pack_forget()
            self.followup_graph_note.pack_forget()
        self._evolution_render_key = None
        self.draw_evolution_board()

    def change_trend_mode(self):
        self.stop_evolution_playback()
        self._evolution_render_key = None
        self.draw_evolution_board()
        self.schedule_followup_calculation()

    def cancel_followup_calculation(self):
        job = getattr(self, "automatic_followup_job", None)
        if job:
            try:
                self.window.after_cancel(job)
            except tk.TclError:
                pass
        self.automatic_followup_job = None

    def schedule_followup_calculation(self):
        """Calculate missing pairs when entering evolution, without repeating failures."""
        from longitudinal_review import visit_review_rows
        self.cancel_followup_calculation()
        if self.closed or self.workspace_mode != "followup":
            return
        rows = visit_review_rows(self.saved_comparisons, self.followup_records(), self.selected_trend_mode())
        if not any(row["state"] in ("pending", "stale") for row in rows):
            return
        lesion, mode = self.lesion_id, self.selected_trend_mode()
        self.followup_hint.configure(text="Hay comparaciones pendientes. Se calcularán automáticamente; puedes pulsar «Calcular seguimiento» para reintentarlas.")
        def start():
            self.automatic_followup_job = None
            if self.closed or self.workspace_mode != "followup" or self.lesion_id != lesion or self.selected_trend_mode() != mode:
                return
            if self.running or self.app.busy:
                self.automatic_followup_job = self.window.after(500, start)
                return
            self.compare_reference_followup(consecutive=(mode == "consecutive"))
        self.automatic_followup_job = self.window.after(500, start)

    def refresh_timeline_visits(self):
        from longitudinal_review import visit_review_rows
        rows = visit_review_rows(self.saved_comparisons, self.followup_records(), self.selected_trend_mode())
        key = tuple((r["record"]["id"], r["record"]["captured_at"], r["state"], r["reason"],
                     r["previous"]["id"] if r["previous"] else None,
                     r["record"].get("sha256")) for r in rows)
        if key == getattr(self, "_timeline_visits_key", None):
            return
        self._timeline_visits_key = key
        for child in self.timeline_visits.winfo_children():
            child.destroy()
        self.timeline_visit_photos = []
        colors = dict(reference="#526581", available="#237355", pending="#526581", stale="#9b631c", invalid="#a43b36")
        for entry in rows:
            record = entry["record"]
            frame = tk.Frame(self.timeline_visits, bg=SURFACE, width=212, height=246,
                             highlightthickness=1, highlightbackground=colors[entry["state"]])
            frame.pack(side="left", padx=(0, 10), pady=2)
            frame.pack_propagate(False)
            text(frame, date_label(record["captured_at"]), 10, INK, True).pack(pady=(6, 2))
            try:
                original, _ = self.store.load_images(record)
                photo = ImageTk.PhotoImage(ImageOps.contain(original, (190, 104)), master=self.window)
                self.timeline_visit_photos.append(photo)
                tk.Button(frame, image=photo, relief="flat", bg=SURFACE, cursor="hand2",
                          command=lambda identifier=record["id"]: self.show_visit(identifier)).pack()
            except (OSError, ValueError):
                text(frame, "Foto no disponible", 10).pack(pady=30)
            text(frame, entry["title"], 10, colors[entry["state"]], True).pack(pady=4)
            text(frame, record["label"] + (" · frente a " + entry["previous"]["label"] if entry["previous"] else ""), 9, MUTED).pack()
            action(frame, "Revisar visita", lambda identifier=record["id"]: self.review_timeline_visit(identifier)).pack(pady=5)
        if not rows:
            text(self.timeline_visits, "Agrega la primera fotografía para iniciar la cronología.", 11).pack(padx=8, pady=25)

    def review_timeline_visit(self, identifier):
        from longitudinal_review import visit_review_rows
        if self.running or self.app.busy:
            return
        entry = next((r for r in visit_review_rows(self.saved_comparisons, self.records, self.selected_trend_mode())
                      if r["record"]["id"] == identifier), None)
        if not entry:
            return
        self.timeline_review_note.configure(text=entry["title"] + " · " + entry["reason"] + "\nSiguiente paso: " + entry["action"])
        self.status.set(entry["reason"])
        if entry["previous"] is None:
            self.show_visit(identifier)
        else:
            self.choose_comparison_photo(0, entry["previous"]["id"])
            self.choose_comparison_photo(1, identifier)

    def toggle_evolution_playback(self):
        if self.running or self.app.busy:
            self.status.set("Espera a que termine el análisis para reproducir las visitas.")
            return
        records = sorted(
            self.followup_records(), key=lambda r: (r["captured_at"], r["id"])
        )
        if not records:
            self.status.set("Agrega fotografías para reproducir la evolución.")
            return
        if self.evolution_playing:
            self.stop_evolution_playback()
            return
        self.evolution_playing = True
        self.evolution_play.configure(text="■ Detener evolución")
        current = self.photo_selection_id
        self.evolution_position = next(
            (i for i, record in enumerate(records) if record["id"] == current), -1
        )
        self._play_next_evolution_frame()

    def _play_next_evolution_frame(self):
        if not self.evolution_playing or self.closed:
            return
        if self.running or self.app.busy:
            self.stop_evolution_playback()
            return
        records = sorted(
            self.followup_records(), key=lambda r: (r["captured_at"], r["id"])
        )
        if not records:
            self.stop_evolution_playback()
            return
        self.evolution_position = (self.evolution_position + 1) % len(records)
        record = records[self.evolution_position]
        self.show_playback_frame(record)
        self.status.set(
            "Reproduciendo evolución: "
            + date_label(record["captured_at"])
            + f" · imagen {self.evolution_position + 1} de {len(records)}"
        )
        self.evolution_job = self.window.after(
            self.evolution_delay_ms(), self._play_next_evolution_frame
        )

    @staticmethod
    def trend_metric_options():
        return (
            ("Índice descriptivo", "index"),
            ("Área aparente", "area"),
            ("Forma", "shape"),
            ("Asimetría", "asymmetry"),
            ("Borde", "border"),
            ("Color", "color"),
            ("Textura", "texture"),
        )

    def selected_trend_metric(self):
        current = self.trend_metric.current() if hasattr(self, "trend_metric") else 0
        options = self.trend_metric_options()
        return options[current][1] if 0 <= current < len(options) else "index"

    def change_trend_metric(self):
        self._evolution_render_key = None
        self.draw_evolution_board()

    def evolution_delay_ms(self):
        try:
            return max(250, int(float(self.evolution_speed.get().split()[0]) * 1000))
        except (AttributeError, ValueError, IndexError):
            return 1000

    def step_evolution(self, direction):
        if self.running or self.app.busy:
            return
        self.stop_evolution_playback()
        records = sorted(self.followup_records(), key=lambda r: (r["captured_at"], r["id"]))
        if not records:
            self.status.set("Agrega fotografías para revisar la evolución.")
            return
        self.evolution_position = (self.evolution_position + direction) % len(records)
        self.show_playback_frame(records[self.evolution_position])

    def restart_evolution(self):
        if self.running or self.app.busy:
            return
        self.stop_evolution_playback()
        records = sorted(self.followup_records(), key=lambda r: (r["captured_at"], r["id"]))
        if not records:
            self.status.set("Agrega fotografías para revisar la evolución.")
            return
        self.evolution_position = 0
        self.show_playback_frame(records[0])
        self.status.set("Reproducción reiniciada en la primera visita registrada.")

    def stop_evolution_playback(self):
        self.evolution_playing = False
        if self.evolution_job:
            self.window.after_cancel(self.evolution_job)
            self.evolution_job = None
        if hasattr(self, "evolution_play"):
            self.evolution_play.configure(text="▶ Reproducir evolución")

    def followup_records(self):
        return list(self.records)

    def refresh_trend_reference(self):
        records = sorted(
            self.followup_records(),
            key=lambda r: (r["captured_at"], r.get("created", ""), r["id"]),
        )
        self.automatic_reference = records[0]["id"] if records else None
        self.trend_origin.configure(
            text=(
                "Foto de inicio: "
                + date_label(records[0]["captured_at"])
                + " · se elige automáticamente por fecha."
                if records
                else "Carga la primera fotografía para iniciar el seguimiento."
            )
        )

    def automatic_reference_id(self):
        self.refresh_trend_reference()
        return self.automatic_reference

    def selected_trend_series(self):
        reference = self.automatic_reference_id()
        return trend_series(
            self.saved_comparisons,
            self.followup_records(),
            reference,
            self.selected_trend_metric(),
            self.selected_trend_mode(),
        )

    def draw_evolution_board(self):
        if self.closed or not hasattr(self, "trend_origin"):
            return
        self.refresh_comparison_table()
        self.trend_hit_regions = []
        series = self.selected_trend_series()
        self.refresh_timeline_visits()
        self.refresh_period_summary(series)
        self.trend_status.configure(text=trend_direction(series))
        total = len(series.get("captures", []))
        measured = len(series.get("points", []))
        self.followup_hint.configure(
            text=f"{total} visita(s) registradas · {measured} medición(es) comparables · {max(0, total - measured - (1 if series.get('reference') else 0))} por revisar o repetir. " + ("Cada punto compara con la visita anterior." if self.selected_trend_mode() == "consecutive" else "Cada visita posterior se compara con la foto inicial.")
        )
        self.chart_note.configure(
            text="Pulsa un punto o su fecha para abrir la fotografía. La referencia inicial vale 0 por definición, no es una medición. No equivale a mejoría o empeoramiento clínico. " + ("Los puntos muestran intervalos independientes; no se unen ni se suman." if self.selected_trend_mode() == "consecutive" else "La línea se interrumpe si falta una medición válida. El eje representa tiempo real, no cantidad de visitas.")
        )
        self.chart_heading.configure(
            text=(
                "Resultado de una comparación"
                if len(series["points"]) == 1
                else "Línea de tiempo de cambios visuales"
            )
        )
        if not self.chart_toggle.get():
            return
        width = max(
            400,
            (
                self.chart.winfo_width()
                if self.chart.winfo_width() > 10
                else self.window.winfo_width() - 290
            ),
        )
        key = (
            width,
            series["metric"],
            series.get("mode"),
            series["reference"]["id"] if series["reference"] else None,
            tuple((p["target"], p["value"], p["date"]) for p in series["points"]),
            tuple((p["target"], p["date"]) for p in series["captures"]),
            tuple(series["excluded"].items()),
        )
        if (
            getattr(self, "_evolution_render_key", None) == key
            and self.chart.find_all()
        ):
            self.trend_hit_regions = getattr(self, "_saved_trend_hit_regions", [])
            return
        self._evolution_render_key = key
        if self.followup_graph_expanded:
            from followup_charts import followup_figure
            dashboard = followup_figure(self.saved_comparisons, self.followup_records(),
                                        series["reference"]["id"] if series["reference"] else None,
                                        self.selected_trend_mode(), size=(max(6, width / 110), 5))
            dashboard.canvas.draw()
            chart_image = Image.frombytes("RGBA", dashboard.canvas.get_width_height(), bytes(dashboard.canvas.buffer_rgba()))
            self.followup_graph_photo = ImageTk.PhotoImage(chart_image, master=self.window)
            self.followup_graph.configure(image=self.followup_graph_photo)
        fig = trend_figure(series, size=(width / 100, 3.2))
        fig.canvas.draw()
        # Point and date hit regions use the coordinates of the rendered timeline.
        ax = fig.axes[0]
        height = fig.canvas.get_width_height()[1]
        self.trend_hit_regions = []
        for x, y, identifier in fig.timeline_points:
            px, py = ax.transData.transform((x, y))
            py = height - py
            self.trend_hit_regions.extend(
                [
                    (px - 12, px + 12, py - 12, py + 12, identifier),
                    (px - 18, px + 18, height - ax.bbox.y0, height, identifier),
                ]
            )
        self._saved_trend_hit_regions = self.trend_hit_regions
        self.chart.configure(cursor="hand2" if self.trend_hit_regions else "")
        image = Image.frombytes(
            "RGBA", fig.canvas.get_width_height(), bytes(fig.canvas.buffer_rgba())
        )
        self.evolution_photo = ImageTk.PhotoImage(image, master=self.window)
        self.chart.configure(height=image.height)
        self.chart.delete("all")
        self.chart.create_image(0, 0, anchor="nw", image=self.evolution_photo)

    def open_trend_capture(self, event):
        if self.running or self.app.busy:
            self.status.set("Espera a que termine el análisis.")
            return
        for left, right, top, bottom, identifier in getattr(
            self, "trend_hit_regions", []
        ):
            if left <= event.x <= right and top <= event.y <= bottom:
                self.show_visit(identifier)
                self.window.after_idle(self.focus_photo_analysis)
                return

    def focus_photo_analysis(self):
        self.window.update_idletasks()
        if not self.photo_analysis_card.winfo_ismapped():
            return
        offset = self.photo_analysis_card.winfo_rooty() - self.dashboard.winfo_rooty()
        self.dashboard_canvas.yview_moveto(
            max(0, (offset - 12) / max(self.dashboard.winfo_height(), 1))
        )

    def build_period_summary(self, parent):
        text(
            parent, "Resumen del periodo y resultados por fotografía", 11, INK, True
        ).pack(anchor="w", padx=12, pady=(12, 4))
        self.period_summary = text(
            parent, "", 10, INK, justify="left", anchor="w", wraplength=750
        )
        self.period_summary.pack(fill="x", padx=12, pady=8)
        parent.bind(
            "<Configure>",
            lambda e: self.period_summary.configure(wraplength=max(200, e.width - 30)),
            add="+",
        )
        shell = tk.Frame(parent, bg=SURFACE)
        shell.pack(fill="x", padx=12, pady=(0, 12))
        self.capture_summary = ttk.Treeview(
            shell,
            columns=("date", "class", "measurement"),
            show="headings",
            height=3,
            style="Evo.Treeview",
        )
        for key, title, width in [
            ("date", "Fecha de la foto", 200),
            ("class", "Clasificación", 250),
            ("measurement", "Seguimiento", 260),
        ]:
            self.capture_summary.heading(key, text=title)
            self.capture_summary.column(key, width=width, minwidth=100)
        scrollbar = ttk.Scrollbar(shell, command=self.capture_summary.yview)
        scrollbar.pack(side="right", fill="y")
        self.capture_summary.configure(yscrollcommand=scrollbar.set)
        self.capture_summary.pack(fill="x", expand=True)
        self.capture_summary.bind("<Double-1>", self.open_summary_capture)

    def open_summary_capture(self, event):
        identifier = self.capture_summary.identify_row(event.y)
        if identifier and not self.running and not self.app.busy:
            self.show_visit(identifier)
            self.window.after_idle(self.focus_photo_analysis)

    def refresh_period_summary(self, series):
        if not hasattr(self, "period_summary"):
            return
        self.refresh_professional_summary()
        from longitudinal_analysis import classification_text

        records = sorted(
            self.followup_records(), key=lambda r: (r["captured_at"], r["id"])
        )
        self.capture_summary.delete(*self.capture_summary.get_children())
        measured = {point["target"] for point in series["points"]} if series else set()
        reference = (
            series["reference"]["id"]
            if series and series["reference"]
            else (records[0]["id"] if records else None)
        )
        from longitudinal_review import visit_review_rows
        review_rows = visit_review_rows(self.saved_comparisons, records, self.selected_trend_mode())
        for entry in review_rows:
            record = entry["record"]
            analysis = record["metadata"].get("classification")
            measurement = entry["title"]
            if entry["state"] in ("invalid", "stale"):
                measurement += ": " + entry["reason"]
            self.capture_summary.insert(
                "",
                "end",
                iid=record["id"],
                values=(
                    date_label(record["captured_at"]),
                    (
                        classification_text(analysis).splitlines()[0]
                        if analysis
                        else "Pendiente de analizar"
                    ),
                    measurement,
                ),
            )
        from longitudinal_reports import selected_followup_summary
        self.period_summary.configure(text=selected_followup_summary(self.saved_comparisons, records, self.selected_trend_mode()))

    def compare_reference_followup(self, consecutive=None):
        self.cancel_followup_calculation()
        if consecutive is None:
            consecutive = self.selected_trend_mode() == "consecutive"
        if self.running or self.app.busy:
            self.status.set("Espera a que termine el análisis.")
            return
        identifier = self.automatic_reference_id()
        if identifier is None:
            return
        self.cancel_auto_comparison()
        reference = self.store.record(identifier)
        targets = [
            r
            for r in self.followup_records()
            if r["captured_at"] > reference["captured_at"]
        ]
        if not targets:
            self.status.set(
                "No hay capturas posteriores a esta referencia. Revisa sus fechas."
            )
            return
        lesion_id = self.lesion_id
        pairs = [(reference["id"], r["id"]) for r in targets]
        if consecutive:
            visits = sorted(self.followup_records(), key=lambda r: (r["captured_at"], r["id"]))
            pairs = [(a["id"], b["id"]) for a, b in zip(visits, visits[1:]) if b["captured_at"] > a["captured_at"]]
        cached = {}
        for pair in pairs:
            try:
                row = self.cached_followup(*pair)
                if row and comparison_validity(row, self.records) is None:
                    cached[pair] = row
            except (ValueError, OSError):
                pass
        missing = [pair for pair in pairs if pair not in cached]
        model, gate = self.app.model, self.app.domain_gate
        extractor = getattr(self.app.reference_index, "extractor", None)
        model_path = self.app.experiment_folder / "model.keras"
        calibration = self.app.calibration
        self.running = True
        self.app.busy = True
        self.app.refresh_actions()
        self.refresh_thumbnails()
        self.status.set(
            "Actualizando seguimiento: "
            + str(len(missing))
            + " comparaciones nuevas; "
            + str(len(cached))
            + " resultados vigentes reutilizados…"
        )

        def run():
            from longitudinal_analysis import compare_records

            count = len(cached)
            failures = []
            for a, b in missing:
                try:
                    compare_records(
                        self.store,
                        a,
                        b,
                        model,
                        gate,
                        extractor,
                        model_path,
                        calibration,
                        mode="longitudinal",
                        fallback_visual=True,
                    )
                    count += 1
                except Exception as exc:
                    failures.append(dict(record_id=b, reason=str(exc)))
            self.queue.put(
                (
                    "followup_done",
                    dict(lesion_id=lesion_id, count=count, failures=failures),
                )
            )

        threading.Thread(target=run, daemon=True).start()

    def run_next_followup(self):
        # Retained for compatibility with old callbacks; follow-up owns its worker.
        return

    def open_analysis_detail(self):
        result = self.current_result
        if not result:
            self.status.set(
                "Compara dos fotografías para abrir sus mediciones y controles."
            )
            return
        dialog = tk.Toplevel(self.window)
        dialog.title("DermaVision-X · Análisis detallado")
        dialog.geometry("1050x700")
        dialog.configure(bg=BACKGROUND)
        ttk.Label(
            dialog,
            text=date_label(result.get("previous_date"))
            + " → "
            + date_label(result.get("current_date")),
            padding=12,
        ).pack(anchor="w")
        tabs = ttk.Notebook(dialog)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        summary = ttk.Frame(tabs)
        measurements = ttk.Frame(tabs)
        quality = ttk.Frame(tabs)
        tabs.add(summary, text="Resumen")
        tabs.add(measurements, text="Mediciones y diferencias")
        tabs.add(quality, text="Calidad de la comparación")
        ttk.Label(
            summary,
            text=comparison_narrative(result),
            wraplength=920,
            justify="left",
            padding=20,
            font=("Segoe UI", 12),
        ).pack(fill="x")
        ttk.Label(
            summary,
            text="El mapa de diferencias localiza diferencias entre dos imágenes.\nEl mapa de influencia explica la salida del clasificador de una fotografía.\n\nPuedes consultar ambos en Fotografías de la lesión.",
            wraplength=920,
            justify="left",
            padding=20,
        ).pack(fill="x")
        columns = ("name", "previous", "current", "difference")
        tree = ttk.Treeview(
            measurements,
            columns=columns,
            show="headings",
            height=6,
            style="Evo.Treeview",
        )
        for key, title, width in zip(
            columns,
            ("Característica", "Anterior", "Actual", "Diferencia"),
            (260, 140, 140, 220),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width)
        tree.pack(fill="x", padx=15, pady=15)
        rows = measurement_rows(result)
        for row in rows:
            tree.insert("", "end", values=row[:4])
        box = tk.Text(
            measurements,
            wrap="word",
            height=12,
            font=("Segoe UI", 11),
            padx=15,
            pady=15,
        )
        box.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        box.insert("1.0", "\n\n".join(r[0] + ": " + r[4] for r in rows))
        box.configure(state="disabled")
        content = tk.Text(quality, wrap="word", font=("Segoe UI", 11), padx=18, pady=18)
        scroll = ttk.Scrollbar(quality, command=content.yview)
        scroll.pack(side="right", fill="y")
        content.configure(yscrollcommand=scroll.set)
        content.pack(fill="both", expand=True)
        lines = [
            name + ": " + value for name, value in quality_rows(result, self.records)
        ]
        lines += [
            "",
            "Para mejorar una comparación: verifica que sea la misma lesión, revisa sus contornos y utiliza encuadre, distancia e iluminación similares.",
            "Detalle técnico MobileNet: "
            + str(
                result.get("deep_cosine_distance")
                if result.get("deep_cosine_distance") is not None
                else "no disponible"
            ),
        ]
        content.insert("1.0", "\n\n".join(lines))
        content.configure(state="disabled")
        self.analysis_dialog = dialog
