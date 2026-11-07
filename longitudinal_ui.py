"""Pantalla independiente de seguimiento; no sustituye el análisis individual."""

import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageOps, ImageTk, ImageDraw

from longitudinal_actions import ManagementMixin
from professional_tools import ProfessionalMixin
from longitudinal_workflow import WorkflowMixin
from longitudinal_dashboard import DashboardMixin, action
from longitudinal_detail_ui import DetailMixin
from longitudinal_comparison_flow import ComparisonFlowMixin
from longitudinal_store import LongitudinalStore
from longitudinal_analysis import (
    suggest_mask,
    mask_overlay,
    compare_records,
    classify_record,
    classification_text,
)
from capture_guide import CaptureGuide
from app_paths import DATA_DIR
from ui_lifecycle import cancel_window_tasks

from ui_theme import (
    BACKGROUND as BG,
    SURFACE as PANEL,
    INK as TEXT,
    ACCENT,
    SUCCESS,
    WARNING,
)

DEFAULT_STORE = DATA_DIR / "longitudinal"


def button(parent, title, command):
    return action(parent, title, command)


def label(parent, text, **kwargs):
    return tk.Label(parent, text=text, **dict(dict(bg=BG, fg=TEXT), **kwargs))


def display_capture_date(value):
    return datetime.fromisoformat(value).strftime("%d/%m/%Y · %H:%M:%S")


class DateTimeFields(tk.Frame):
    def __init__(self, parent, value):
        super().__init__(parent, bg=BG)
        parsed = datetime.fromisoformat(value)
        self.values = {}
        fields = [
            ("day", "Día", parsed.day, 1, 31),
            ("month", "Mes", parsed.month, 1, 12),
            ("year", "Año", parsed.year, 1900, 2100),
            ("hour", "Hora", parsed.hour, 0, 23),
            ("minute", "Minuto", parsed.minute, 0, 59),
            ("second", "Segundo", parsed.second, 0, 59),
        ]
        for i, (key, title, initial, minimum, maximum) in enumerate(fields):
            variable = tk.StringVar(
                value=f"{initial:04d}" if key == "year" else f"{initial:02d}"
            )
            self.values[key] = variable
        self.date_text = tk.StringVar(value=parsed.strftime("%d/%m/%Y"))
        self.syncing = False
        ttk.Entry(self, textvariable=self.date_text, width=14).grid(
            row=0, column=0, sticky="w"
        )
        label(self, "día/mes/año").grid(row=0, column=1, padx=8, sticky="w")
        self.time_visible = tk.BooleanVar(
            value=bool(parsed.hour or parsed.minute or parsed.second)
        )
        self.time_frame = tk.Frame(self, bg=BG)
        for i, key in enumerate(("hour", "minute", "second")):
            label(
                self.time_frame,
                dict(hour="Hora", minute="Minuto", second="Segundo")[key],
            ).grid(row=0, column=i, padx=3)
            ttk.Spinbox(
                self.time_frame,
                from_=0,
                to=23 if key == "hour" else 59,
                textvariable=self.values[key],
                width=4,
                format="%02.0f",
            ).grid(row=1, column=i, padx=3)

        def toggle():
            if self.time_visible.get():
                self.time_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=6)
            else:
                self.time_frame.grid_remove()
                for key in ("hour", "minute", "second"):
                    self.values[key].set("00")

        tk.Checkbutton(
            self,
            text="Añadir hora de captura (opcional)",
            variable=self.time_visible,
            command=toggle,
            bg=BG,
            fg=TEXT,
            selectcolor=PANEL,
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        toggle()

        def components_changed(*_):
            if self.syncing:
                return
            self.syncing = True
            self.date_text.set(
                "/".join(self.values[key].get() for key in ("day", "month", "year"))
            )
            self.syncing = False

        def date_changed(*_):
            if self.syncing:
                return
            pieces = self.date_text.get().split("/")
            if len(pieces) != 3:
                return
            self.syncing = True
            for key, value in zip(("day", "month", "year"), pieces):
                self.values[key].set(value)
            self.syncing = False

        self.date_text.trace_add("write", date_changed)
        for key in ("day", "month", "year"):
            self.values[key].trace_add("write", components_changed)

    def get(self):
        try:
            if len(self.date_text.get().split("/")) != 3:
                raise ValueError("Fecha incompleta")
            values = {key: int(value.get()) for key, value in self.values.items()}
            result = datetime(
                values["year"],
                values["month"],
                values["day"],
                values["hour"],
                values["minute"],
                values["second"],
            )
        except (ValueError, OverflowError) as exc:
            raise ValueError(
                "Revise día, mes, año y hora: la fecha debe existir y la hora estar entre 00:00:00 y 23:59:59."
            ) from exc
        return result.isoformat(timespec="seconds")


class RecordEditor:
    def __init__(self, parent, image, save, initial_date=None, content_verified=False, identity_reference=None):
        self.image = ImageOps.exif_transpose(image).convert("RGB")
        self.save_callback = save
        self.mask = None
        self.points = []
        self.mask_method = "manual_polygon"
        self.capture_assessment = CaptureGuide().evaluate(self.image, static=True)
        self.window = tk.Toplevel(parent)
        self.window.title("Nuevo registro · revisar contorno y fecha")
        self.window.geometry("880x730")
        self.window.minsize(680, 600)
        self.window.configure(bg=BG)
        self.window.transient(parent)
        self.window.grab_set()
        self.date = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.note = tk.StringVar()
        self.reviewed = tk.BooleanVar(value=False)
        self.identity_reference = identity_reference
        self.identity_confirmed = tk.BooleanVar(value=False)
        form = tk.Frame(self.window, bg=BG)
        form.pack(fill="x", padx=15, pady=8)
        label(form, "1 Foto aceptada  →  2 Revisar contorno  →  3 Confirmar y guardar", fg=ACCENT).grid(row=3, column=0, columnspan=2, pady=6, sticky="w")
        label(form, "Fecha de la foto:").grid(row=0, column=0, sticky="w")
        self.date_fields = DateTimeFields(
            form, initial_date or datetime.now().date().isoformat()
        )
        self.date_fields.grid(row=0, column=1, sticky="w")
        label(
            form,
            "Día / mes / año · hora local. Puede ser anterior a la fecha de carga.",
            wraplength=530,
        ).grid(row=2, column=1, sticky="w")
        label(form, "Nota / condiciones de captura:").grid(
            row=1, column=0, sticky="w", pady=8
        )
        ttk.Entry(form, textvariable=self.note, width=48).grid(row=1, column=1)
        label(
            self.window,
            "Comprueba que es la misma lesión. Conserva piel alrededor para alinear las visitas.\n"
            "El contorno sugerido es aproximado: puedes reemplazarlo dibujando puntos alrededor de la lesión.",
            wraplength=790,
            justify="left",
        ).pack(padx=15, pady=5)
        quality_message = (
            "Calidad técnica suficiente. "
            if self.capture_assessment.ready
            else "Revisa la calidad antes de guardar. "
            + self.capture_assessment.message
            + " "
        )
        label(
            self.window,
            quality_message
            + "La calidad técnica no verifica si el contenido es una lesión.",
            wraplength=790,
            justify="left",
            fg=SUCCESS if self.capture_assessment.ready else WARNING,
        ).pack(fill="x", padx=15, pady=(0, 8))
        if content_verified:
            label(
                self.window,
                "Filtro de contenido experimental superado. Confirma que la foto corresponde a esta misma lesión.",
                fg=SUCCESS,
                wraplength=790,
                justify="left",
            ).pack(fill="x", padx=15, pady=(0, 8))
        controls = tk.Frame(self.window, bg=BG)
        controls.pack(fill="x", padx=15)
        for text, action in [
            ("Sugerir contorno", self.suggest),
            ("Dibujar de nuevo", self.clear),
            ("Cerrar contorno", self.finish),
            ("Quitar último punto", self.undo),
        ]:
            button(controls, text, action).pack(side="left", padx=3)
        footer = tk.Frame(self.window, bg=BG)
        footer.pack(side="bottom", fill="x", padx=15, pady=12)
        if identity_reference:
            tk.Checkbutton(footer, text="Confirmo que es la misma lesión de la foto de referencia " + display_capture_date(identity_reference["captured_at"]),
                           variable=self.identity_confirmed, bg=BG, fg=TEXT, selectcolor=PANEL).pack(anchor="w")
            label(footer, "Esta declaración es humana; el sistema no verifica la identidad de la lesión.", wraplength=800).pack(anchor="w")
        tk.Checkbutton(
            footer,
            text="He revisado el contorno y la fecha de esta foto",
            variable=self.reviewed,
            bg=BG,
            fg=TEXT,
            selectcolor=PANEL,
        ).pack(anchor="w")
        label(
            footer,
            "Guardar conserva una copia local de la imagen, el contorno y la fecha. No se envía por Internet.",
            wraplength=800,
        ).pack(anchor="w", pady=5)
        button(footer, "Guardar registro en esta lesión", self.commit).pack(anchor="e")
        self.border_notice = label(footer, "", fg=WARNING, wraplength=800)
        self.border_notice.pack(anchor="w")
        self.canvas = tk.Canvas(self.window, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=15, pady=10)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<Button-1>", self.point)
        self.window.update_idletasks()
        try:
            self.mask = suggest_mask(self.image)
            self.mask_method = "contrast_suggestion_reviewed"
        except ValueError:
            pass
        self.render()

    def render(self):
        canvas = self.canvas
        source = (
            mask_overlay(self.image, self.mask) if self.mask is not None else self.image
        )
        fit = ImageOps.contain(
            source, (max(canvas.winfo_width(), 1), max(canvas.winfo_height(), 1))
        )
        self.scale = fit.width / self.image.width
        self.offset = (
            (canvas.winfo_width() - fit.width) / 2,
            (canvas.winfo_height() - fit.height) / 2,
        )
        self.photo = ImageTk.PhotoImage(fit)
        canvas.delete("all")
        canvas.create_image(*self.offset, anchor="nw", image=self.photo)
        points = [
            (x * self.scale + self.offset[0], y * self.scale + self.offset[1])
            for x, y in self.points
        ]
        if len(points) > 1:
            canvas.create_line(
                *[v for point in points for v in point], fill=ACCENT, width=2
            )
        for x, y in points:
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=ACCENT)
        touches = False
        if self.mask is not None:
            bounds = self.mask.getbbox()
            touches = bool(bounds and (bounds[0] == 0 or bounds[1] == 0 or bounds[2] == self.mask.width or bounds[3] == self.mask.height))
        self.border_notice.configure(text="El contorno toca el borde. Repite el encuadre con piel alrededor; este recorte puede impedir la comparación." if touches else "")

    def point(self, event):
        x, y = (event.x - self.offset[0]) / self.scale, (
            event.y - self.offset[1]
        ) / self.scale
        if 0 <= x < self.image.width and 0 <= y < self.image.height:
            self.mask = None
            self.mask_method = "manual_polygon"
            self.reviewed.set(False)
            self.points.append((int(x), int(y)))
            self.render()

    def clear(self):
        self.points = []
        self.mask = None
        self.reviewed.set(False)
        self.render()

    def undo(self):
        if self.points:
            self.points.pop()
            self.mask = None
            self.reviewed.set(False)
            self.render()

    def finish(self):
        if len(self.points) < 3:
            messagebox.showinfo(
                "Contorno",
                "Marca al menos tres puntos alrededor de la lesión.",
                parent=self.window,
            )
            return
        self.mask = Image.new("L", self.image.size)
        ImageDraw.Draw(self.mask).polygon(self.points, fill=255)
        self.reviewed.set(False)
        self.render()

    def suggest(self):
        try:
            self.mask = suggest_mask(self.image)
            self.points = []
            self.mask_method = "contrast_suggestion_reviewed"
            self.reviewed.set(False)
            self.render()
        except ValueError as exc:
            messagebox.showinfo("Contorno", str(exc), parent=self.window)

    def commit(self):
        try:
            if self.identity_reference and not self.identity_confirmed.get():
                raise ValueError("Confirma que es la misma lesión. Si corresponde a otra lesión, regístrala en una ficha distinta.")
            if self.mask is None or not self.reviewed.get():
                raise ValueError(
                    "Cierra el contorno y marca que has revisado el contorno y la fecha."
                )
            self.date.set(self.date_fields.get())
            self.save_callback(
                self.date.get(),
                self.image,
                self.mask,
                dict(
                    mask_reviewed=True,
                    mask_method=self.mask_method,
                    note=self.note.get(),
                    acquisition_timezone="local_unspecified",
                    reference_diagnosis=None,
                    lesion_identity=dict(status="user_declared" if self.identity_reference else "initial_reference",
                        reference_id=self.identity_reference["id"] if self.identity_reference else None,
                        method="human_confirmation" if self.identity_reference else "initial_registration"),
                    capture_quality=dict(
                        checks=[bool(v) for v in self.capture_assessment.checks[:3]],
                        brightness=self.capture_assessment.brightness,
                        sharpness=self.capture_assessment.sharpness,
                        message=self.capture_assessment.message,
                    ),
                ),
            )
            self.window.destroy()
        except Exception as exc:
            messagebox.showerror("No se pudo guardar", str(exc), parent=self.window)


class EvolutionWindow(
    ProfessionalMixin, ComparisonFlowMixin, DetailMixin, WorkflowMixin, ManagementMixin, DashboardMixin
):
    def __init__(self, app, store=None):
        self.app = app
        self.store = store or LongitudinalStore(getattr(app, "store_root", None) or DEFAULT_STORE)
        self.window = tk.Toplevel(app.root)
        self.window.title("DermaVision-X · Personas y fotografías")
        if getattr(app, "demo", False):
            self.window.title("DermaVision-X · DEMOSTRACIÓN SINTÉTICA · Capstone")
        self.window.geometry("1180x800")
        self.window.minsize(950, 660)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.running = False
        self.closed = False
        self.queue = queue.Queue()
        self.lesion_id = None
        self.records = []
        self.saved_comparisons = []
        self.selected_photo_ids = []
        self.photo_selection_id = None
        self.comparison_pair = [None, None]
        self.comparison_result_id = None
        self._selection_lesion_id = None
        self.displayed_record_id = None
        self.photos = []
        self.image_sources = []
        self.image_titles = []
        self.status = tk.StringVar(
            value="Registra una persona y agrega su lesión, o selecciona una existente. Las fotos se guardan solo cuando pulsas Guardar registro."
        )
        self.build_dashboard()
        self.refresh_lesions()
        self.poll_job = self.window.after(100, self.poll)

    def refresh_lesions(self):
        self.lesions = self.store.lesions()
        self.person_rows = self.store.persons()
        chosen_code = self.patient_choice.get()
        current = next((r for r in self.lesions if r["id"] == self.lesion_id), None)
        if current:
            chosen_code = current["patient"]
        codes = [r["code"] for r in self.person_rows]
        self.patient_choice["values"] = codes
        self.patient_choice.set(
            chosen_code if chosen_code in codes else (codes[0] if codes else "")
        )
        self.filter_people()
        selected = next(
            (r for r in self.person_rows if r["code"] == self.patient_choice.get()),
            None,
        )
        if selected and self.person_list.exists(selected["id"]):
            self.person_list.selection_set(selected["id"])
        self.filter_patient()

    def select_person(self, event=None):
        selected = self.person_list.selection()
        if not selected:
            return
        row = self.store.person(selected[0])
        if self.patient_choice.get() != row["code"]:
            if self.running or self.app.busy:
                old = next(
                    (
                        p
                        for p in self.person_rows
                        if p["code"] == self.patient_choice.get()
                    ),
                    None,
                )
                if old and self.person_list.exists(old["id"]):
                    self.person_list.selection_set(old["id"])
                self.status.set(
                    "Espera a que termine el análisis antes de seleccionar otra persona."
                )
                return
            self.lesion_id = None
            self.selected_photo_ids = []
            self.comparison_mode.current(0)
            self.patient_choice.set(row["code"])
            self.filter_patient()

    def edit_person(self):
        selected = self.person_list.selection()
        if not selected:
            messagebox.showinfo(
                "Personas", "Seleccione una persona para editar.", parent=self.window
            )
            return
        self.person_dialog(selected[0])

    def create_person(self):
        if not self.idle_for_management():
            return
        self.person_dialog()

    def person_dialog(self, identifier=None):
        row = (
            self.store.person(identifier)
            if identifier
            else dict(code="", name="", notes="")
        )
        dialog = tk.Toplevel(self.window)
        dialog.title("Editar persona" if identifier else "Registrar persona")
        dialog.configure(bg=BG)
        dialog.transient(self.window)
        dialog.grab_set()
        fields = []
        for i, (title, key) in enumerate(
            [
                ("Código de persona", "code"),
                ("Nombres (opcional)", "name"),
                ("Observaciones (opcional)", "notes"),
            ]
        ):
            label(dialog, title).grid(row=i, column=0, padx=12, pady=8, sticky="w")
            entry = ttk.Entry(dialog, width=48)
            entry.insert(0, row[key])
            entry.grid(row=i, column=1, padx=12, pady=8)
            fields.append(entry)

        def save():
            try:
                values = [entry.get() for entry in fields]
                if identifier:
                    self.store.update_person(identifier, *values)
                else:
                    self.store.create_person(*values)
                    self.lesion_id = None
                self.patient_choice.set(values[0].strip())
                self.person_search.set("")
                self.refresh_lesions()
                self.status.set(
                    "Persona guardada en la base local. Puede agregar sus lesiones."
                )
                dialog.destroy()
                self.navigate(2)
                self.open_person()
            except Exception as exc:
                messagebox.showerror(
                    "No se pudo guardar la persona", str(exc), parent=dialog
                )

        button(dialog, "Guardar persona", save).grid(
            row=3, column=1, padx=12, pady=12, sticky="e"
        )
        fields[0].focus_set()

    def clear_output(self):
        self.displayed_record_id = None
        self.reset_dashboard_result()
        self.result_explanation.configure(
            text="Selecciona una fotografía para verla o dos para mostrar su comparación automáticamente."
        )
        self.show_text(
            "Selecciona una fotografía para verla o analizarla. Selecciona dos para comparar.\n"
            "Usa fechas reales de captura y confirma que pertenecen a la misma lesión."
        )
        self.details_card.pack_forget()
        for caption, picture in self.picture_widgets:
            picture.configure(image="")
        self.photos = []
        self.image_sources = []
        self.sync_photo_analysis()
        self.draw_timeline()

    def _refresh_history(self):
        self.records = self.store.records(self.lesion_id)
        self.history.delete(*self.history.get_children())
        for r in self.records:
            self.history.insert(
                "",
                "end",
                iid=r["id"],
                values=(
                    r["label"],
                    display_capture_date(r["captured_at"]),
                    (
                        classification_text(
                            r["metadata"]["classification"]
                        ).splitlines()[0]
                        if r["metadata"].get("classification")
                        else "Pendiente"
                    ),
                ),
            )
        self.refresh_pair_choices()
        self.saved_comparisons = self.store.comparisons(self.lesion_id)
        self.comparisons.delete(*self.comparisons.get_children())
        for c in self.saved_comparisons:
            r = c["result"]
            index = (
                r.get("visual_index")
                if r.get("mode") == "visual"
                else r.get("change_index")
            )
            self.comparisons.insert(
                "",
                "end",
                iid=c["id"],
                values=(
                    display_capture_date(c["live_previous_date"])
                    + " → "
                    + display_capture_date(c["live_current_date"]),
                    (
                        "Recalcular"
                        if c.get("stale_dates")
                        else ("—" if index is None else f"{index:.1f}")
                    ),
                    "Fecha modificada" if c.get("stale_dates") else r["change_level"],
                ),
            )
        self.apply_history_filters()
        self.draw_timeline()
        self.refresh_thumbnails()
        self.update_context()
        for control in self.history_buttons.values():
            control.configure(state="disabled")
        self.select_comparison()

    def _refresh_pair_choices(self):
        old = getattr(self, "pair_records", [])
        selected = []
        for widget in (self.previous, self.current):
            index = widget.current()
            selected.append(old[index]["id"] if 0 <= index < len(old) else None)
        self.pair_records = list(self.records)
        if self.comparison_mode_key() == "visual":
            self.pair_records = []
            for lesion in self.store.lesions():
                if lesion["patient"] == self.patient_choice.get():
                    for record in self.store.records(lesion["id"]):
                        record["comparison_label"] = lesion["name"]
                        self.pair_records.append(record)
        self.pair_records.sort(key=lambda r: (r["captured_at"], r["created"], r["id"]))
        options = [
            display_capture_date(r["captured_at"])
            + " | "
            + r.get("comparison_label", r["label"])
            for r in self.pair_records
        ]
        for n, widget in enumerate((self.previous, self.current)):
            widget["values"] = options
            if not options:
                widget.set("")
                continue
            default = max(0, len(options) - 2) if n == 0 else len(options) - 1
            index = next(
                (i for i, r in enumerate(self.pair_records) if r["id"] == selected[n]),
                default,
            )
            widget.current(index)
        if (
            len(self.pair_records) > 1
            and self.previous.current() == self.current.current()
        ):
            first = self.previous.current()
            self.current.current(
                first + 1 if first + 1 < len(self.pair_records) else first - 1
            )
        self.update_pair_summary()

    def create_lesion(self):
        if not self.idle_for_management():
            return
        selected = next(
            (r for r in self.person_rows if r["code"] == self.patient_choice.get()),
            None,
        )
        if selected is None:
            messagebox.showinfo(
                "Lesiones",
                "Primero registre y seleccione una persona.",
                parent=self.window,
            )
            return
        person_id = selected["id"]
        dialog = tk.Toplevel(self.window)
        dialog.title("Registrar lesión")
        dialog.configure(bg=BG)
        dialog.transient(self.window)
        dialog.grab_set()
        label(dialog, "Persona: " + selected["code"]).grid(
            row=0, column=0, columnspan=2, padx=12, pady=10
        )
        fields = []
        for i, title in enumerate(
            ["Código/nombre de lesión", "Zona del cuerpo (opcional)"], 1
        ):
            label(dialog, title).grid(row=i, column=0, padx=12, pady=8, sticky="w")
            entry = ttk.Entry(dialog, width=28)
            entry.grid(row=i, column=1, padx=12, pady=8)
            fields.append(entry)

        def save():
            try:
                self.lesion_id = self.store.create_lesion_for_person(
                    person_id, *(entry.get() for entry in fields)
                )
                self.refresh_lesions()
                self.status.set("Lesión guardada y asociada a la persona seleccionada.")
                dialog.destroy()
                self.selected_photo_ids = []
                self.comparison_mode.current(0)
                self.refresh_history()
                self.navigate(0)
            except Exception as exc:
                messagebox.showerror("Registro", str(exc), parent=dialog)

        button(dialog, "Guardar lesión", save).grid(
            row=3, column=1, padx=12, pady=10, sticky="e"
        )
        fields[0].focus_set()

    def editor(self, image, source_metadata=None):
        self.cancel_auto_comparison()
        if self.lesion_id is None:
            messagebox.showinfo(
                "Seguimiento",
                "Primero registra o selecciona una lesión.",
                parent=self.window,
            )
            return
        review = getattr(self, "capture_review", None)
        if review is None or not review.matches(image):
            self.start_photo_registration(image=image, metadata=source_metadata)
            return
        lesion_id = self.lesion_id

        def save(date, image, mask, metadata):
            if self.lesion_id != lesion_id or not review.matches(image):
                raise ValueError(
                    "La captura cambió o no superó la revisión. Vuelve a analizarla antes de guardar."
                )
            snapshot = review.snapshot(image)
            metadata.update(source_metadata or {})
            metadata["domain_verified"] = True
            identifier = self.store.add_record(
                lesion_id,
                date,
                image,
                mask,
                metadata,
                analysis=snapshot[0] if snapshot else None,
                explanation=snapshot[1] if snapshot else None,
            )
            self.photo_selection_id = identifier
            self.workspace_mode = "photos"
            self.selected_photo_ids = [identifier]
            self.refresh_history()
            index = next(
                i for i, r in enumerate(self.pair_records) if r["id"] == identifier
            )
            self.current.current(index)
            if self.previous.current() == index and len(self.pair_records) > 1:
                self.previous.current(index - 1 if index > 0 else 1)
            self.clear_output()
            self.displayed_record_id = identifier
            self.refresh_thumbnails()
            self.navigate(0)
            self.show_visit(identifier)
            self.status.set(
                "Fotografía verificada y guardada. Puedes analizarla aquí o elegirla en Comparar dos fotos."
            )
            review.clear()

        RecordEditor(
            self.window,
            image,
            save,
            initial_date=(source_metadata or {}).get("source_captured_at"),
            content_verified=True,
            identity_reference=min(self.records, key=lambda r: (r["captured_at"], r["id"])) if self.records else None,
        )

    def import_photo(self):
        if self.lesion_id is None:
            self.status.set(
                "Abre una persona y una lesión antes de cargar fotografías."
            )
            self.navigate(2)
            return
        if self.running or self.app.busy:
            self.status.set(
                "Espera a que termine el análisis antes de agregar fotografías."
            )
            return
        self.start_photo_registration(source="file")

    def start_photo_registration(self, source="file", image=None, metadata=None):
        if self.running or self.app.busy:
            self.status.set(
                "Espera a que termine el análisis antes de agregar fotografías."
            )
            return
        if self.lesion_id is None:
            self.status.set("Abre una lesión antes de agregar una fotografía.")
            return
        self.cancel_auto_comparison()
        from longitudinal_capture import FollowupCaptureDialog

        return FollowupCaptureDialog(self, source, image, metadata)

    def capture_photo(self):
        if self.app.frame is None or not self.app.captured or self.app.cap is not None:
            messagebox.showinfo(
                "Captura",
                "Toma una captura fija en la pantalla principal y luego guárdala aquí.",
                parent=self.window,
            )
            return
        self.start_photo_registration(
            image=self.app.region().copy(), metadata=dict(source_kind="main_capture")
        )

    def preview_record(self, event=None):
        # A single selection prepares history actions without opening another page.
        selected = self.history.selection()
        for control in self.history_buttons.values():
            control.configure(state="normal" if selected else "disabled")
        if not selected:
            return
        self.displayed_record_id = selected[0]
        values = self.history.item(selected[0], "values")
        date = values[1] if len(values) > 1 else ""
        self.status.set(
            f"Fotografía seleccionada: {date}. Puedes eliminarla aquí o pulsar Ver fotografía."
        )

    def open_history_photo(self, event=None):
        selected = self.history.selection()
        if not selected:
            self.status.set("Selecciona una fotografía del historial para verla.")
            return
        try:
            self.show_visit(selected[0])
        except Exception as exc:
            messagebox.showerror("Registro", str(exc), parent=self.window)

    def _show_visit(self, identifier):
        record = self.store.record(identifier)
        if record["lesion_id"] != self.lesion_id:
            return
        self.workspace_mode = "photos"
        image, mask = self.store.load_images(record)
        self.clear_output()
        self.displayed_record_id = identifier
        self.selected_photo_ids = [identifier]
        self.refresh_thumbnails()
        self.display_images(
            [mask_overlay(image, mask)], ["Visita seleccionada · contorno revisado"]
        )
        classification = record["metadata"].get("classification")
        capture_quality = record["metadata"].get("capture_quality") or (
            classification or {}
        ).get("quality", {})
        quality_checks = capture_quality.get("checks", [])
        quality_note = (
            "Controles técnicos básicos superados."
            if quality_checks and all(quality_checks)
            else (
                "Revisa esta captura antes de analizarla: "
                + capture_quality.get("message", "calidad no evaluada.")
                if quality_checks
                else "Calidad de captura aún no documentada."
            )
        )
        from longitudinal_analysis import classification_summary

        self.result_explanation.configure(
            text=(
                classification_summary(classification)
                if classification
                else "Esta fotografía está registrada. Pulsa Analizar fotografía para ver su clasificación y su mapa de influencia. Para ver cambios, abre Comparar dos fotos."
            )
            + "\n\nFecha de la foto: "
            + display_capture_date(record["captured_at"])
            + "\nCalidad de captura: "
            + quality_note
            + (
                "\nObservación registrada: " + str(record["metadata"]["note"])
                if record["metadata"].get("note")
                else ""
            )
        )
        report = f"Fecha: {record['captured_at']}\nCalidad de captura: {quality_note}\nObservaciones: {record['metadata'].get('note','')}\n\n"
        if classification:
            self.classification_heading.configure(
                text="Clasificación de esta fotografía"
            )
            self.result_cards[1].grid(column=0, columnspan=2)
            self.update_classification_card(classification)
            self.explanation_button.configure(
                state="normal" if classification.get("explanation") else "disabled"
            )
            report += classification_text(classification)
        else:
            report += "Clasificación pendiente. Pulsa Analizar fotografía para obtener un resultado experimental."
        self.show_text(report)
        self.sync_photo_analysis()
        self.navigate(0)

    def selected_visit_id(self):
        if len(self.selected_photo_ids) == 1:
            return self.selected_photo_ids[0]
        if self.displayed_record_id:
            return self.displayed_record_id
        if self.current_result:
            return self.current_result["current_id"]
        index = self.current.current()
        return self.pair_records[index]["id"] if index >= 0 else None

    def edit_visit_date(self, identifier=None):
        if self.running or self.app.busy:
            self.status.set(
                "Espere a que termine la operación actual antes de editar la fecha."
            )
            return
        identifier = identifier or self.selected_visit_id()
        if not identifier:
            messagebox.showinfo(
                "Fecha",
                "Seleccione una fotografía guardada primero.",
                parent=self.window,
            )
            return
        self.cancel_auto_comparison()
        row = self.store.record(identifier)
        page_before = self.tabs.index("current")
        dialog = tk.Toplevel(self.window)
        dialog.title("Editar fecha de captura")
        dialog.transient(self.window)
        dialog.grab_set()
        dialog.configure(bg=BG)
        label(dialog, "Cuándo se tomó esta fotografía:").grid(
            row=0, column=0, padx=12, pady=10, sticky="w"
        )
        dialog.date_fields = DateTimeFields(dialog, row["captured_at"])
        dialog.date_fields.grid(row=1, column=0, columnspan=2, padx=12, pady=10)
        label(
            dialog,
            "Use la fecha de captura, aunque cargue la foto hoy. Si desconoce la hora, puede usar 00:00:00.\n"
            "Las comparaciones afectadas se conservarán y se marcarán para recalcular.",
            wraplength=530,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, padx=12, pady=10)

        def save():
            try:
                self.store.update_record_date(identifier, dialog.date_fields.get())
                self.refresh_history()
                if page_before == 1:
                    self.history.selection_set(identifier)
                    self.preview_record()
                elif (
                    self.workspace_mode == "photos"
                    and self.photo_selection_id == identifier
                ):
                    self.show_visit(identifier)
                else:
                    self.clear_output()
                    self.refresh_comparison_slots(preview=True)
                    self.refresh_thumbnails()
                self.navigate(page_before)
                self.status.set(
                    "Fecha actualizada. Las comparaciones anteriores afectadas deben recalcularse."
                )
                dialog.destroy()
                if page_before == 0:
                    self.request_auto_comparison()
            except Exception as exc:
                messagebox.showerror(
                    "No se pudo guardar la fecha", str(exc), parent=dialog
                )

        button(dialog, "Guardar fecha", save).grid(row=3, column=1, padx=12, pady=12)

    def classify_visit(self, identifier=None):
        if self.running or self.app.busy:
            self.status.set("Espere a que termine la operación actual.")
            return
        self.cancel_auto_comparison()
        identifier = identifier or self.selected_visit_id()
        if not identifier:
            messagebox.showinfo(
                "Clasificación",
                "Guarde y seleccione una visita primero.",
                parent=self.window,
            )
            return
        if self.app.model is None or self.app.domain_gate is None:
            self.status.set(
                "Espere a que se carguen el modelo y los filtros. No se genera una predicción."
            )
            return
        self.running = True
        self.app.busy = True
        self.compare_button.configure(state="disabled")
        self.classify_button.configure(state="disabled")
        self.status.set("Clasificando la visita y preparando su explicación visual…")
        model, gate, calibration = (
            self.app.model,
            self.app.domain_gate,
            self.app.calibration,
        )
        model_path = self.app.experiment_folder / "model.keras"

        def run():
            try:
                analysis = classify_record(
                    self.store, identifier, model, gate, calibration, model_path
                )
                self.queue.put(("visit_analysis", (identifier, analysis)))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def show_visit_explanation(self, identifier=None):
        identifier = identifier or self.selected_visit_id()
        if not identifier:
            messagebox.showinfo(
                "Explicación", "Seleccione una visita clasificada.", parent=self.window
            )
            return
        try:
            # Expanded and embedded maps use the same saved version of this photo.
            image = self.store.load_explanation(identifier)
            dialog = tk.Toplevel(self.window)
            dialog.title("Explicación visual por oclusión")
            dialog.configure(bg=BG)
            label(
                dialog,
                "Fotografía: "
                + display_capture_date(self.store.record(identifier)["captured_at"]),
                wraplength=500,
            ).pack(padx=14, pady=(12, 0))
            from explainability import explanation_caption

            analysis = self.store.record(identifier)["metadata"].get(
                "classification", {}
            )
            label(
                dialog,
                explanation_caption(analysis.get("explanation_diagnostics")),
                wraplength=500,
                justify="left",
            ).pack(padx=14, pady=(12, 0))
            label(
                dialog,
                "Regiones que influyeron en la clasificación experimental. No es una segmentación ni un diagnóstico.",
                wraplength=500,
            ).pack(padx=14, pady=12)
            row = tk.Frame(dialog, bg=BG)
            row.pack(padx=14, pady=14)
            original, mask = self.store.load_images(self.store.record(identifier))
            from explainability import influence_view
            saved_map = image.copy()
            map_controls = tk.Frame(dialog, bg=BG)
            map_controls.pack(fill="x", padx=14, pady=5)
            contour_visible = tk.BooleanVar(master=dialog, value=False)
            opacity = tk.DoubleVar(master=dialog, value=1.0)
            map_picture = None

            def redraw_map(*args):
                if map_picture is None:
                    return
                rendered = influence_view(original, saved_map, mask, opacity.get(), contour_visible.get())
                photo = ImageTk.PhotoImage(ImageOps.contain(rendered, (420, 420)), master=dialog)
                map_picture.configure(image=photo)
                map_picture.image = photo

            tk.Checkbutton(map_controls, text="Mostrar contorno revisado", variable=contour_visible,
                           command=redraw_map, bg=BG).pack(side="left")
            tk.Scale(map_controls, from_=0, to=1, resolution=0.05, orient="horizontal",
                     label="Intensidad", variable=opacity, command=redraw_map, bg=BG).pack(side="right")
            for source, caption in (
                (original, "Fotografía original"),
                (image, "Mapa de influencia"),
            ):
                frame = tk.Frame(row, bg=BG)
                frame.pack(side="left", padx=7)
                label(frame, caption).pack()
                photo = ImageTk.PhotoImage(ImageOps.contain(source, (420, 420)))
                picture = tk.Label(frame, image=photo)
                picture.image = photo
                picture.pack()
                if caption == "Mapa de influencia":
                    map_picture = picture

            def recalculate():
                dialog.destroy()
                self.displayed_record_id = identifier
                self.classify_visit()

            button(dialog, "Recalcular explicación", recalculate).pack(pady=(0, 14))
        except (ValueError, OSError) as exc:
            messagebox.showinfo("Explicación", str(exc), parent=self.window)

    def compare(self):
        if self.running or self.app.busy:
            self.status.set(
                "Espera a que termine el análisis o la carga de modelos de la pantalla principal."
            )
            return
        try:
            a, b = self.previous.current(), self.current.current()
            if min(a, b) < 0:
                raise ValueError(
                    "Añade al menos dos registros y selecciona sus fechas."
                )
            previous_id, current_id = (
                self.pair_records[a]["id"],
                self.pair_records[b]["id"],
            )
            mode = self.comparison_mode_key()
            if (
                mode == "longitudinal"
                and self.pair_records[a]["captured_at"]
                > self.pair_records[b]["captured_at"]
            ):
                a, b = b, a
                previous_id, current_id = current_id, previous_id
                self.previous.current(a)
                self.current.current(b)
                self.update_pair_summary()
            self.store.pair(previous_id, current_id, mode)
        except Exception as exc:
            messagebox.showinfo("Comparación", str(exc), parent=self.window)
            return
        self.running = True
        self.app.busy = True
        self.active_lesion_id = (
            self.store.record(current_id)["lesion_id"]
            if mode == "visual"
            else self.lesion_id
        )
        self.compare_button.configure(state="disabled")
        self.status.set(
            "Comparando regiones: características visuales, índice descriptivo y siluetas…"
            if mode == "visual"
            else "Comparando: controles de imagen, alineación, características y clasificación actual…"
        )
        model, gate = self.app.model, self.app.domain_gate
        extractor = getattr(self.app.reference_index, "extractor", None)
        model_path = self.app.experiment_folder / "model.keras"

        def run():
            try:
                payload = compare_records(
                    self.store,
                    previous_id,
                    current_id,
                    model,
                    gate,
                    extractor,
                    model_path,
                    self.app.calibration,
                    mode=mode,
                    fallback_visual=(mode == "longitudinal"),
                )
                self.queue.put(("ok", payload))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        if getattr(self, "poll_job", None):
            self.window.after_cancel(self.poll_job)
            self.poll_job = None
        try:
            kind, payload = self.queue.get_nowait()
            pending = False
            self.running = pending
            self.app.busy = pending
            self.app.refresh_actions()
            self.compare_button.configure(state="disabled" if pending else "normal")
            self.classify_button.configure(state="disabled" if pending else "normal")
            if kind == "error":
                self.followup_pending = []
                self.followup_batch = False
                self.status.set("No se completó la comparación.")
                messagebox.showerror("Comparación", payload, parent=self.window)
            elif kind == "visit_analysis":
                identifier, analysis = payload
                row = self.store.record(identifier)
                if row["lesion_id"] == self.lesion_id:
                    self.refresh_history()
                    if (
                        self.workspace_mode == "photos"
                        and self.photo_selection_id == identifier
                    ):
                        self.show_visit(identifier)
                    elif self.workspace_mode == "compare":
                        self.sync_photo_analysis()
                        # Keep the chosen pair and update its classification snapshot.
                        self.request_auto_comparison()
                    else:
                        self.draw_timeline()
                self.status.set(
                    "Clasificación guardada en la visita. "
                    + classification_text(analysis).splitlines()[0]
                )
            elif kind == "auto_followup":
                if payload["lesion_id"] == self.lesion_id:
                    self.display_auto_comparison(
                        payload["comparison_id"], payload["selection"]
                    )
            elif kind == "auto_followup_error":
                self.refresh_history()
                message = "No se pudo completar la comparación automática: " + payload
                self.status.set(message)
                self.result_explanation.configure(text=message)
                self.details_card.pack(fill="x", padx=18, pady=(0, 18))
            elif kind == "followup_done":
                if payload["lesion_id"] == self.lesion_id:
                    self.refresh_history()
                    self.refresh_workspace_layout()
                    self.draw_timeline()
                failures = payload.get("failures", [])
                self.status.set(
                    "Seguimiento actualizado. "
                    + str(payload.get("count", 0))
                    + " comparaciones revisadas."
                    + (
                        " No se completaron "
                        + str(len(failures))
                        + ": "
                        + failures[0]["reason"]
                        if failures
                        else ""
                    )
                )
            elif kind == "ok":
                self.lesion_id = self.active_lesion_id
                self.refresh_lesions()
                for widget, key in [
                    (self.previous, "previous_id"),
                    (self.current, "current_id"),
                ]:
                    widget.current(
                        next(
                            i
                            for i, r in enumerate(self.pair_records)
                            if r["id"] == payload["result"][key]
                        )
                    )
                self.selected_photo_ids = [
                    payload["result"]["previous_id"],
                    payload["result"]["current_id"],
                ]
                self.refresh_thumbnails()
                self.display_images(
                    [payload["previous"], payload["current"], payload["overlay"]],
                    [
                        (
                            "Imagen A"
                            if payload["result"].get("mode") == "visual"
                            else "Anterior"
                        ),
                        (
                            "Imagen B (modo visual)"
                            if payload["result"].get("mode") == "visual"
                            else (
                                "Actual alineada"
                                if payload["result"]["comparable"]
                                else "Actual (no comparable)"
                            )
                        ),
                        (
                            "Mapa de siluetas"
                            if payload["result"].get("mode") == "visual"
                            else (
                                "Mapa de diferencias alineadas"
                                if payload["result"]["comparable"]
                                else "Mapa no disponible"
                            )
                        ),
                    ],
                )
                self.update_pair_summary()
                self.show_result(payload["result"])
                self.reveal_comparison_result()
                self.status.set(
                    "Comparación visual guardada: índice, barras y mapa de siluetas disponibles."
                    if payload["result"].get("mode") == "visual"
                    else "Comparación guardada. "
                    + (
                        "Índice exploratorio disponible."
                        if payload["result"]["comparable"]
                        else "No evaluable: consulta el motivo."
                    )
                )
                if getattr(self, "followup_pending", []):
                    self.window.after_idle(self.run_next_followup)
                elif getattr(self, "followup_batch", False):
                    self.followup_batch = False
                    self.refresh_workspace_layout()
                    self.draw_timeline()
        except queue.Empty:
            pass
        if not self.running and not self.app.busy:
            count = len(self.selected_photo_ids)
            for control in self.photo_buttons.values():
                control.configure(state="normal" if count == 1 else "disabled")
            self.compare_button.configure(state="normal" if count == 2 else "disabled")
        self.refresh_comparison_slots()
        self.poll_job = self.window.after(100, self.poll)

    def display_images(self, images, titles):
        if images:
            self.compare_card.grid()
        self.compare_heading.configure(
            text=(
                "Fotografía seleccionada"
                if len(images) == 1
                else "Fotografías seleccionadas"
            )
        )
        first, second = (self.picture_widgets[i][1].master for i in (0, 1))
        first.grid(columnspan=2 if len(images) == 1 else 1)
        if len(images) == 1:
            second.grid_remove()
        else:
            second.grid()
        self.image_sources = list(images)
        self.image_titles = list(titles)
        self.render_images()

    def render_images(self):
        self.render_dashboard_images()

    def show_text(self, text):
        self.details_card.pack(fill="x", padx=18, pady=(0, 18))
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", text)
        self.report.configure(state="disabled")
        self.refresh_workspace_layout()

    def _show_result(self, result):
        if not getattr(self, "followup_batch", False):
            self.workspace_mode = "compare"
        self.update_dashboard_result(result)
        self.heatmap_ids = []
        self.refresh_thumbnails()
        classification = result["current_classification"]
        from longitudinal_analysis import classification_summary
        from longitudinal_insights import date_label
        from longitudinal_insights import comparison_narrative, quality_guidance

        self.result_explanation.configure(
            text="Fotos comparadas: "
            + date_label(result.get("previous_date"))
            + " → "
            + date_label(result.get("current_date"))
            + "\n\n"
            + comparison_narrative(result)
            + "\n\n"
            + quality_guidance(result)
            + "\n\nResultado de la foto posterior: "
            + classification_summary(classification)
        )
        if result.get("mode") == "visual":
            visual = result["visual_differences"]
            self.show_text(
                "COMPARACIÓN VISUAL DE IMÁGENES\n"
                f"Índice de diferencia visual: {result['visual_index']:.1f}/100 · {result['visual_level']} (heurístico).\n"
                f"Cobertura: {visual['area_coverage_pp']:+.2f} puntos porcentuales; excluida del índice.\n"
                f"Forma: {visual['shape']:.4f} · Asimetría: {visual['asymmetry']:+.4f} · Borde: {visual['border']:+.4f}\n"
                f"Color LAB: {visual['color']:.3f} · Textura: {visual['texture']:.4f}\n\n"
                + "\n".join(result["warnings"])
                + "\n\n"
                + classification_text(classification)
            )
            return
        lines = [
            f"{result['previous_date']} → {result['current_date']} · {result['elapsed_days']:.1f} días",
            classification_text(classification),
        ]
        if result["comparable"]:
            changes = result["changes"]
            lines += [
                f"\nÍndice de cambio: {result['change_index']:.1f}/100 · {result['change_level']} (categoría heurística)",
                f"Área aparente alineada: {changes['area']:+.2f} %",
                f"Forma (distancia entre siluetas, 0–1): {changes['shape']:.4f}",
                f"Asimetría (diferencia): {changes['asymmetry']:+.4f}",
                f"Irregularidad de borde (diferencia): {changes['border']:+.4f}",
                f"Color medio (distancia LAB): {changes['color']:.3f}",
                f"Textura (distancia entre histogramas, 0–1): {changes['texture']:.4f}",
            ]
            deep = result.get("deep_cosine_distance")
            lines += [
                "MobileNet (distancia coseno, 0–2): "
                + ("no disponible" if deep is None else f"{deep:.5f}")
            ]
            ranked = sorted(
                result["index_components"],
                key=result["index_components"].get,
                reverse=True,
            )
            names = dict(
                area="área",
                shape="forma",
                asymmetry="asimetría",
                border="borde",
                color="color",
                texture="textura",
            )
            changed = [names[k] for k in ranked if result["index_components"][k] >= 0.1]
            lines += [
                "Mayores diferencias en esta comparación: "
                + (
                    ", ".join(changed)
                    if changed
                    else "sin diferencias destacadas según la escala heurística."
                )
            ]
        else:
            lines += [
                "\nEvolución no cuantificable: no se asigna índice de cambio longitudinal."
            ]
            visual = result.get("visual_differences")
            if visual:
                lines += [
                    "\nDiferencias visuales sin alineación:",
                    f"Cobertura de la región marcada: {visual['area_coverage_pp']:+.2f} puntos porcentuales",
                    f"Forma (distancia entre siluetas): {visual['shape']:.4f}",
                    f"Asimetría: {visual['asymmetry']:+.4f}",
                    f"Borde: {visual['border']:+.4f}",
                    f"Color medio LAB: {visual['color']:.3f}",
                    f"Textura: {visual['texture']:.4f}",
                    visual["warning"],
                ]

        lines += ["\nObservaciones:"] + [
            "• " + warning for warning in result["warnings"]
        ]
        lines += [
            "\nEl seguimiento compara características de fotografías fechadas; no utiliza un modelo predictivo temporal.",
            "El índice no predice malignidad. No se mide crecimiento físico sin referencia de escala.",
        ]
        self.show_text("\n".join(lines))

    def restore_comparison(self, event=None):
        selected = self.comparisons.selection()
        if not selected:
            return
        row = next(c for c in self.saved_comparisons if c["id"] == selected[0])
        try:
            from longitudinal_insights import comparison_validity

            scope = self.records
            if (
                row["result"].get("requested_mode", row["result"].get("mode"))
                == "visual"
            ):
                scope = [
                    self.store.record(row[side + "_id"])
                    for side in ("previous", "current")
                ]
            invalid = comparison_validity(row, scope)
            for side in ("previous", "current"):
                latest = self.store.record(row[side + "_id"])["metadata"].get(
                    "classification"
                )
                snapshot = row["result"].get(side + "_classification", {})
                if latest and any(
                    latest.get(k) != snapshot.get(k)
                    for k in ("state", "raw_score", "model_sha256", "calibration")
                ):
                    invalid = "La clasificación guardada de una fotografía cambió; vuelve a comparar."
            if invalid:
                self.comparison_pair = [row["previous_id"], row["current_id"]]
                self.comparison_result_id = None
                self.workspace_mode = "compare"
                self.selected_photo_ids = self.active_photo_ids()
                self.clear_output()
                self.readiness_title.configure(text="RECALCULAR", fg="#c74764")
                self.readiness_detail.configure(
                    text="El resultado guardado ya no corresponde a los datos actuales. "
                    + invalid
                )
                self.refresh_pair_choices()
                self.refresh_comparison_slots(preview=True)
                self.show_text(
                    "Este resultado necesita actualizarse: "
                    + invalid
                    + "\nSe conservarán estas mismas dos fotografías."
                )
                self.status.set("Comparación pendiente de actualizar.")
                self.navigate(0)
                self.request_auto_comparison()
                return
            self.clear_output()
            self.comparison_mode.current(
                1
                if row["result"].get("requested_mode", row["result"].get("mode"))
                == "visual"
                else 0
            )
            self.refresh_pair_choices()
            previous, current = self.store.pair(
                row["previous_id"],
                row["current_id"],
                row["result"].get("mode", "longitudinal"),
            )
            im0, mask0 = self.store.load_images(previous)
            im1, mask1 = self.store.load_images(current)
            if row["result"]["comparable"]:
                import cv2
                from longitudinal_analysis import normalized

                original, _ = normalized(im0, mask0)
                actual, _ = normalized(im1, mask1)
                im0 = Image.fromarray(original)
                matrix = np.array(row["result"]["registration"]["matrix"])
                aligned = cv2.warpAffine(
                    actual, matrix, (original.shape[1], original.shape[0])
                )
                offset = np.array(
                    row["result"]["color_normalization"]["offset"], dtype="float32"
                )
                if np.max(np.abs(offset)) >= 1e-6:
                    lab = (
                        cv2.cvtColor(aligned.astype("float32") / 255, cv2.COLOR_RGB2LAB)
                        + offset
                    )
                    lab[:, :, 0] = np.clip(lab[:, :, 0], 0, 100)
                    aligned = np.uint8(
                        np.clip(
                            np.rint(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB) * 255), 0, 255
                        )
                    )
                im1 = Image.fromarray(aligned)
            with Image.open(self.store.path(row["overlay"])) as source:
                overlay = source.convert("RGB")
            for widget, key in [
                (self.previous, "previous_id"),
                (self.current, "current_id"),
            ]:
                widget.current(
                    next(
                        i
                        for i, r in enumerate(self.pair_records)
                        if r["id"] == row[key]
                    )
                )
            self.selected_photo_ids = [row["previous_id"], row["current_id"]]
            self.refresh_thumbnails()
            self.display_images(
                [im0, im1, overlay],
                (
                    ["Imagen A", "Imagen B", "Mapa de siluetas guardado"]
                    if row["result"].get("mode") == "visual"
                    else [
                        "Anterior",
                        "Actual alineada" if row["result"]["comparable"] else "Actual",
                        "Mapa guardado",
                    ]
                ),
            )
            self.update_pair_summary()
            self.show_result(row["result"])
            self.navigate(0)
            self.reveal_comparison_result()
        except Exception as exc:
            messagebox.showerror("Comparación guardada", str(exc), parent=self.window)

    def draw_timeline(self):
        self.draw_evolution_board()

    def export(self):
        target = filedialog.askdirectory(
            parent=self.window, title="Carpeta para exportar registros y comparaciones"
        )
        if target:
            try:
                folder = Path(target) / (
                    "dermavision-export-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                )
                records, pairs = self.store.export(folder)
                self.status.set(
                    f"Exportado: {records} registros y {pairs} comparaciones en {folder}"
                )
            except Exception as exc:
                messagebox.showerror("Exportación", str(exc), parent=self.window)

    def close(self):
        if self.running or getattr(self, "followup_pending", []):
            self.status.set(
                "Espera a que termine el guardado de la comparación antes de cerrar esta ventana."
            )
            return
        self.cancel_auto_comparison()
        self.cancel_followup_calculation()
        self.stop_evolution_playback()
        self.closed = True
        if self.poll_job:
            self.window.after_cancel(self.poll_job)
        cancel_window_tasks(self.window)
        self.window.destroy()
        self.app.root.deiconify()
        self.app.root.lift()
