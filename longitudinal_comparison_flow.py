"""Selecciones independientes para una foto, un par explícito y el seguimiento."""

from datetime import datetime
import tkinter as tk
from tkinter import ttk
from PIL import ImageOps, ImageTk
from longitudinal_insights import date_label
from ui_theme import SURFACE, INK, MUTED


class ComparisonFlowMixin:
    def reset_selection_context(self):
        if hasattr(self, "evolution_playing"):
            self.stop_evolution_playback()
        self.photo_selection_id = None
        self.comparison_pair = [None, None]
        self.comparison_result_id = None
        self._selection_lesion_id = self.lesion_id
        self.selected_photo_ids = []
        self.cancel_auto_comparison()

    def active_photo_ids(self):
        if self.workspace_mode == "compare":
            return [i for i in self.comparison_pair if i]
        if self.workspace_mode == "photos":
            return [self.photo_selection_id] if self.photo_selection_id else []
        return []

    def comparison_workflow_mode(self):
        row = next(
            (r for r in self.saved_comparisons if r["id"] == self.comparison_result_id),
            None,
        )
        result = row["result"] if row else self.current_result or {}
        return result.get("requested_mode", result.get("mode", "longitudinal"))

    def comparison_records(self):
        if self.comparison_workflow_mode() != "visual":
            return self.records
        # Explicit visual tests may compare lesions of the same person.
        return [
            r
            for lesion in self.store.lesions()
            if lesion["patient"] == self.patient_choice.get()
            for r in self.store.records(lesion["id"])
        ]

    def refresh_history(self):
        if self._selection_lesion_id != self.lesion_id:
            self.reset_selection_context()
            self.reset_dashboard_result()
        valid = {r["id"] for r in self.store.records(self.lesion_id)}
        if self.photo_selection_id not in valid:
            self.photo_selection_id = None
        pair_valid = (
            {r["id"] for r in self.comparison_records()}
            if self.comparison_workflow_mode() == "visual"
            else valid
        )
        self.comparison_pair = [
            i if i in pair_valid else None for i in self.comparison_pair
        ]
        if all(self.comparison_pair) and self.comparison_workflow_mode() != "visual":
            self.comparison_pair.sort(
                key=lambda i: (self.store.record(i)["captured_at"], i)
            )
        self.selected_photo_ids = self.active_photo_ids()
        self._refresh_history()
        if self.comparison_result_id not in {c["id"] for c in self.saved_comparisons}:
            self.comparison_result_id = None
        self.refresh_comparison_slots()

    def select_lesion(self, event=None):
        index = self.lesion_choice.current()
        if index < 0:
            return
        changed = self._selection_lesion_id != self.visible_lesions[index]["id"]
        self.lesion_id = self.visible_lesions[index]["id"]
        self.refresh_history()
        if changed:
            self.clear_output()
            if self.workspace_mode == "compare":
                self.refresh_comparison_slots(preview=True)

    def refresh_pair_choices(self):
        # The hidden processing selectors follow explicit IDs; they never fill
        # an empty space with a third or recently registered photograph.
        self._refresh_pair_choices()
        if self.comparison_mode_key() == "longitudinal":
            for widget, identifier in zip(
                (self.previous, self.current), self.comparison_pair
            ):
                index = next(
                    (
                        n
                        for n, r in enumerate(self.pair_records)
                        if r["id"] == identifier
                    ),
                    None,
                )
                if index is None:
                    widget.set("")
                else:
                    widget.current(index)

    def show_visit(self, identifier):
        if self.store.record(identifier)["lesion_id"] != self.lesion_id:
            return
        self.photo_selection_id = identifier
        self._show_visit(identifier)

    def set_workspace_mode(self, mode):
        if mode not in ("photos", "compare", "followup"):
            return
        if mode != "followup" and hasattr(self, "evolution_playing"):
            self.stop_evolution_playback()
            self.cancel_followup_calculation()
        if self.running or self.app.busy:
            self.status.set(
                "Espera a que termine el análisis antes de cambiar de pestaña."
            )
            return
        self.cancel_auto_comparison()
        self.workspace_mode = mode
        self.selected_photo_ids = self.active_photo_ids()
        if mode != "followup":
            self.clear_output()
        if mode == "photos" and self.photo_selection_id:
            self.show_visit(self.photo_selection_id)
        elif mode == "compare":
            visual = self.comparison_workflow_mode() == "visual"
            self.comparison_mode.current(1 if visual else 0)
            self.refresh_pair_choices()
            self.refresh_comparison_slots(preview=True)
            row = (
                next(
                    (
                        r
                        for r in self.saved_comparisons
                        if r["id"] == self.comparison_result_id
                    ),
                    None,
                )
                if visual
                else (
                    self.cached_followup(*self.comparison_pair)
                    if all(self.comparison_pair)
                    else None
                )
            )
            if row:
                self.display_auto_comparison(row["id"], tuple(self.comparison_pair))
            else:
                self.request_auto_comparison()
        self.refresh_thumbnails()
        self.refresh_workspace_layout()
        self.dashboard_canvas.yview_moveto(0)
        if mode == "followup":
            self.draw_timeline()
            self.schedule_followup_calculation()

    def select_photo(self, identifier):
        if self.running or self.app.busy:
            self.status.set(
                "Espera a que termine el análisis antes de cambiar las fotografías."
            )
            return
        if self.workspace_mode == "photos":
            self.cancel_auto_comparison()
            self.show_visit(identifier)
        elif self.workspace_mode == "compare":
            if identifier in self.comparison_pair:
                return
            if None in self.comparison_pair:
                self.choose_comparison_photo(
                    self.comparison_pair.index(None), identifier
                )
            else:
                self.status.set(
                    "Para cambiar una foto, pulsa Cambiar foto en su espacio. El par actual se conserva."
                )

    def compare_with_previous(self):
        """Start the normal comparison flow from the selected visit."""
        if self.running or self.app.busy or not self.photo_selection_id:
            return
        visits = sorted(self.records, key=lambda row: (row["captured_at"], row["id"]))
        position = next(
            (i for i, row in enumerate(visits) if row["id"] == self.photo_selection_id),
            -1,
        )
        if position < 1:
            self.status.set(
                "Esta fotografía no tiene una visita anterior de la misma lesión."
            )
            return
        self.comparison_pair = [visits[position - 1]["id"], self.photo_selection_id]
        self.comparison_result_id = None
        self.comparison_mode.current(0)
        self.set_workspace_mode("compare")

    def choose_comparison_photo(self, side, identifier):
        if side not in (0, 1) or self.running or self.app.busy:
            return False
        row = self.store.record(identifier)
        if row["lesion_id"] != self.lesion_id:
            self.status.set("Elige una fotografía registrada en esta misma lesión.")
            return False
        if self.comparison_pair[1 - side] == identifier:
            self.status.set(
                "Esa foto ya está en el otro espacio. Elige dos fotografías diferentes."
            )
            return False
        self.cancel_auto_comparison()
        self.comparison_pair[side] = identifier
        if all(self.comparison_pair):
            # Display the ordering immediately, before analysis starts.
            self.comparison_pair.sort(
                key=lambda i: (self.store.record(i)["captured_at"], i)
            )
        self.comparison_result_id = None
        self.workspace_mode = "compare"
        self.comparison_mode.current(0)
        self.selected_photo_ids = self.active_photo_ids()
        self.clear_output()
        self.refresh_pair_choices()
        self.refresh_comparison_slots(preview=True)
        self.refresh_thumbnails()
        self.refresh_workspace_layout()
        self.status.set(
            "Preparando comparación de estas dos fotos…"
            if all(self.comparison_pair)
            else "Elige la fotografía del otro espacio para comparar automáticamente."
        )
        self.request_auto_comparison()
        return True

    def open_comparison_picker(self, side):
        if self.running or self.app.busy:
            return
        dialog = tk.Toplevel(self.window)
        dialog.title("Elegir foto A" if side == 0 else "Elegir foto B")
        dialog.geometry("660x500")
        dialog.transient(self.window)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text="Elige una fotografía de esta lesión. La comparación empieza al completar ambos espacios.",
            wraplength=590,
            padding=12,
        ).pack(fill="x")
        body = tk.Canvas(dialog, highlightthickness=0, bg=SURFACE)
        scroll = ttk.Scrollbar(dialog, command=body.yview)
        scroll.pack(side="right", fill="y")
        body.configure(yscrollcommand=scroll.set)
        body.pack(fill="both", expand=True)
        inner = tk.Frame(body, bg=SURFACE)
        body.create_window(0, 0, window=inner, anchor="nw")
        inner.bind(
            "<Configure>", lambda e: body.configure(scrollregion=body.bbox("all"))
        )
        photos = []

        def pick(identifier):
            if self.choose_comparison_photo(side, identifier):
                dialog.destroy()

        for row in self.records:
            line = tk.Frame(inner, bg=SURFACE)
            line.pack(fill="x", padx=10, pady=4)
            try:
                image, _ = self.store.load_images(row)
                photo = ImageTk.PhotoImage(
                    ImageOps.contain(image, (100, 70)), master=dialog
                )
                photos.append(photo)
            except (OSError, ValueError):
                photo = None
            other = row["id"] == self.comparison_pair[1 - side]
            tk.Button(
                line,
                image=photo,
                text=date_label(row["captured_at"])
                + " · "
                + row["label"]
                + (" · elegida en el otro espacio" if other else ""),
                compound="left",
                anchor="w",
                command=lambda i=row["id"]: pick(i),
                state="disabled" if other else "normal",
                bg=SURFACE,
                fg=INK,
                relief="flat",
                padx=12,
                pady=7,
            ).pack(fill="x")
        if not self.records:
            ttk.Label(
                inner,
                text="Primero carga fotografías en la pestaña Fotografías.",
                padding=20,
            ).pack()
        dialog.photos = photos

    def refresh_comparison_slots(self, preview=False):
        if not hasattr(self, "slot_buttons"):
            return
        key = (
            self.workspace_mode,
            tuple(self.comparison_pair),
            self.running,
            self.app.busy,
            id(self.current_result),
            tuple((r["id"], r["captured_at"]) for r in self.records),
        )
        if not preview and getattr(self, "_comparison_slots_key", None) == key:
            return
        self._comparison_slots_key = key
        titles = []
        images = []
        same_date = (
            all(self.comparison_pair)
            and len({self.store.record(i)["captured_at"] for i in self.comparison_pair})
            == 1
        )
        for side, identifier in enumerate(self.comparison_pair):
            row = next(
                (r for r in self.comparison_records() if r["id"] == identifier), None
            )
            title = (
                ("Foto A" if side == 0 else "Foto B")
                if same_date
                else ("Foto A · anterior" if side == 0 else "Foto B · posterior")
            )
            title += " · " + date_label(row["captured_at"]) if row else " · sin elegir"
            self.slot_buttons[side].configure(
                text="Cambiar foto" if row else "Elegir foto",
                state="disabled" if self.running or self.app.busy else "normal",
            )
            titles.append(title)
            if preview:
                try:
                    images.append(self.store.load_images(row)[0] if row else None)
                except (OSError, ValueError):
                    images.append(None)
        if self.workspace_mode == "compare":
            if preview and not self.current_result:
                self.display_images(images, titles)
                for side, (_, picture) in enumerate(self.picture_widgets[:2]):
                    picture.configure(
                        text="Elige una fotografía" if images[side] is None else "",
                        fg=MUTED,
                    )
            elif self.current_result:
                self.image_titles[:2] = titles
                self.render_images()
            self.update_pair_summary()

    def update_pair_summary(self):
        if self.comparison_mode_key() == "visual":
            return super().update_pair_summary()
        if not all(self.comparison_pair):
            self.pair_summary.configure(
                text="1. Elige foto A y foto B.  2. Lee el resultado automático y los mapas de este par."
            )
            return
        a, b = (self.store.record(i) for i in self.comparison_pair)
        days = (
            datetime.fromisoformat(b["captured_at"])
            - datetime.fromisoformat(a["captured_at"])
        ).total_seconds() / 86400
        self.pair_summary.configure(
            text=f"Dos fotos seleccionadas · {abs(days):.1f} días entre capturas. "
            + (
                "A es anterior y B es posterior."
                if days > 0
                else (
                    "B es anterior y A es posterior."
                    if days < 0
                    else "Misma fecha: se pueden describir diferencias visuales, sin evolución temporal."
                )
            )
        )

    def show_result(self, result):
        self.comparison_pair = [result["previous_id"], result["current_id"]]
        self.comparison_result_id = next(
            (
                row["id"]
                for row in reversed(self.saved_comparisons)
                if row["result"] == result
            ),
            None,
        )
        self._show_result(result)
        self.refresh_comparison_slots()

    def display_auto_comparison(self, identifier, selection):
        self.comparison_pair = list(selection)
        self.comparison_result_id = identifier
        super().display_auto_comparison(identifier, selection)
        self.refresh_comparison_slots()
        self.status.set(
            "Resultado de estas dos fotografías. Para reemplazar una, pulsa Cambiar foto en su espacio."
        )

    def clear_photo_selection(self):
        if self.running or self.app.busy:
            return
        if self.workspace_mode == "compare":
            self.comparison_pair = [None, None]
            self.comparison_result_id = None
        elif self.workspace_mode == "photos":
            self.photo_selection_id = None
        super().clear_photo_selection()
        self.refresh_comparison_slots(preview=True)

    def after_data_change(self):
        mode = self.workspace_mode
        self.clear_output()
        self.refresh_lesions()
        self.refresh_history()
        self.workspace_mode = mode
        self.selected_photo_ids = self.active_photo_ids()
        if mode == "photos" and self.photo_selection_id:
            self.show_visit(self.photo_selection_id)
        elif mode == "compare":
            self.refresh_comparison_slots(preview=True)
            row = next(
                (
                    r
                    for r in self.saved_comparisons
                    if r["id"] == self.comparison_result_id
                ),
                None,
            )
            if row and not row.get("stale_dates"):
                self.display_auto_comparison(row["id"], tuple(self.comparison_pair))
        self.refresh_thumbnails()
        self.refresh_workspace_layout()
        self.draw_timeline()
        self.status.set(
            "Datos actualizados. Se conservan las fotografías seleccionadas que todavía existen."
        )
