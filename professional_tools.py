"""Herramientas de revisión: presentación, notas y controles de comparación."""

from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

from longitudinal_dashboard import action, text
from longitudinal_insights import date_label
from ui_theme import SURFACE, INK, MUTED, SUCCESS, WARNING


def comparison_confidence(result):
    """Technical readiness, deliberately not a clinical confidence score."""
    if not result:
        return "Pendiente", "Selecciona dos fotos y calcula su comparación.", MUTED
    if not result.get("comparable"):
        return "Baja", next(iter(result.get("warnings", [])), "Solo revisión visual disponible."), WARNING
    checks = [result.get(side + "_classification", {}).get("quality", {}).get("checks", []) for side in ("previous", "current")]
    reviewed = all(bool(values) and all(values) for values in checks)
    return (
        ("Alta", "Alineación aceptada y controles técnicos registrados.", SUCCESS)
        if reviewed else
        ("Media", "Alineación aceptada; revisa los controles de captura y los contornos.", WARNING)
    )


def wipe_images(before, after, fraction):
    """Reveal aligned images without blending their pixels."""
    before = before.convert("RGB")
    after = after.convert("RGB").resize(before.size)
    result = after.copy()
    cut = round(before.width * max(0, min(1, float(fraction))))
    result.paste(before.crop((0, 0, cut, before.height)), (0, 0))
    return result


class ProfessionalMixin:
    def build_professional_tools(self, parent):
        self.professional_summary = text(parent, "", 10, INK, justify="left", anchor="w", wraplength=780)
        self.professional_summary.pack(fill="x", padx=12, pady=8)
        controls = tk.Frame(parent, bg=SURFACE)
        controls.pack(fill="x", padx=12, pady=8)
        action(controls, "Informe PDF", self.export_pdf).pack(side="left")
        menu_button = ttk.Menubutton(controls, text="Herramientas avanzadas")
        menu = tk.Menu(menu_button, tearoff=False)
        for title, callback in (("Notas y etiquetas de la visita", self.edit_visit_notes),
                                ("Auditoría de visitas", self.show_visit_audit),
                                ("Estadísticas", self.show_project_statistics)):
            menu.add_command(label=title, command=callback)
        menu_button.configure(menu=menu)
        menu_button.pack(side="left", padx=6)
        self.playback_preview = tk.Label(parent, bg=SURFACE)
        self.playback_preview.pack(fill="x", padx=12)
        self.playback_caption = text(parent, "", 10, MUTED, justify="left", wraplength=760)
        self.playback_caption.pack(fill="x", padx=12, pady=5)

    def refresh_professional_summary(self):
        if not hasattr(self, "professional_summary"):
            return
        records = sorted(self.records, key=lambda r: (r["captured_at"], r["id"]))
        from longitudinal_review import visit_review_rows
        valid = sum(r["state"] == "available" for r in visit_review_rows(self.saved_comparisons, records, self.selected_trend_mode()))
        uncertain = sum(r["metadata"].get("classification", {}).get("state") == "uncertain" for r in records)
        pending = sum(not r["metadata"].get("classification") for r in records)
        lines = [f"Esta lesión: {len(records)} fotos · {valid} comparaciones válidas · {uncertain} no concluyentes · {pending} pendientes."]
        if records:
            days = (datetime.now() - datetime.fromisoformat(records[-1]["captured_at"]).replace(tzinfo=None)).days
            lines.append(f"Última fotografía: {date_label(records[-1]['captured_at'])} · hace {max(0, days)} días.")
            if days >= 30:
                lines.append("Recordatorio de registro: han pasado 30 días o más; revisa el plan de seguimiento acordado con el profesional.")
        if len(records) < 2:
            lines.append("Agrega otra fotografía fechada para comparar esta lesión.")
        elif not valid:
            lines.append("Sin mediciones temporales válidas: calcula el seguimiento y revisa los motivos de cada visita.")
        self.professional_summary.configure(text="\n".join(lines))

    def edit_visit_notes(self):
        if not self.idle_for_management():
            return
        identifier = self.photo_selection_id
        if not identifier and self.records:
            identifier = self.records[-1]["id"]
        if not identifier:
            self.status.set("Selecciona o registra una fotografía para agregar sus notas.")
            return
        record = self.store.record(identifier)
        current = record["metadata"].get("visit_notes", {})
        dialog = tk.Toplevel(self.window)
        dialog.title("Notas de visita · " + date_label(record["captured_at"]))
        dialog.transient(self.window)
        fields = {}
        choices = ("No registrado", "No", "Sí")
        for i, (key, title) in enumerate([("itch", "Picazón"), ("bleeding", "Sangrado"), ("pain", "Dolor")]):
            ttk.Label(dialog, text=title).grid(row=i, column=0, padx=12, pady=6, sticky="w")
            field = ttk.Combobox(dialog, values=choices, state="readonly")
            field.set(current.get(key, "No registrado"))
            field.grid(row=i, column=1, padx=12, pady=6)
            fields[key] = field
        for i, (key, title) in enumerate([("evolution", "Evolución percibida"), ("sun", "Exposición solar"), ("observation", "Observación profesional"), ("tags", "Etiquetas separadas por coma"), ("author", "Autor / revisor (declarado)")], start=3):
            ttk.Label(dialog, text=title).grid(row=i, column=0, padx=12, pady=6, sticky="w")
            field = ttk.Entry(dialog, width=55)
            field.insert(0, current.get(key, ""))
            field.grid(row=i, column=1, padx=12, pady=6)
            fields[key] = field
        ttk.Label(dialog, text="Etiquetas sugeridas: seguimiento mensual, foto por repetir, caso académico.", wraplength=520).grid(row=8, column=0, columnspan=2, padx=12, pady=8)

        def save():
            try:
                self.store.update_visit_notes(identifier, {key: field.get() for key, field in fields.items()})
                self.refresh_history()
                dialog.destroy()
                self.status.set("Notas guardadas en la visita; historial de cambios conservado.")
            except (ValueError, OSError) as exc:
                messagebox.showerror("Notas", str(exc), parent=dialog)
        ttk.Button(dialog, text="Guardar notas", command=save).grid(row=9, column=1, padx=12, pady=12, sticky="e")

    def show_visit_audit(self):
        dialog = tk.Toplevel(self.window)
        dialog.title("Registro de cambios de las visitas")
        box = tk.Text(dialog, width=95, height=24, wrap="word")
        box.pack(fill="both", expand=True, padx=12, pady=12)
        lines = []
        for record in self.records:
            lines.append(f"{record['label']} · captura {date_label(record['captured_at'])} · registro {record['created']}")
            for event in record["metadata"].get("visit_audit", []):
                lines.append(f"  {event['at']} · {event['author'] or 'Sin autor declarado'} · {event['action']}")
            for event in record["metadata"].get("date_corrections", []):
                lines.append("  Corrección de fecha: " + str(event))
        box.insert("1.0", "\n".join(lines) or "Sin visitas registradas.")
        box.configure(state="disabled")

    def show_project_statistics(self):
        lesions = self.store.lesions()
        records = [record for lesion in lesions for record in self.store.records(lesion["id"])]
        comparisons = [row for lesion in lesions for row in self.store.comparisons(lesion["id"])]
        from longitudinal_insights import comparison_validity
        valid = sum(bool(row["result"].get("comparable")) and comparison_validity(row, records) is None for row in comparisons)
        pending = sum(not record["metadata"].get("classification") for record in records)
        uncertain = sum(record["metadata"].get("classification", {}).get("state") == "uncertain" for record in records)
        messagebox.showinfo("Resumen del archivo local", f"Personas: {len(self.store.persons())}\nLesiones: {len(lesions)}\nFotografías: {len(records)}\nComparaciones: {len(comparisons)}\nComparaciones temporales válidas: {valid}\nClasificaciones no concluyentes: {uncertain}\nFotografías pendientes de analizar: {pending}", parent=self.window)

    def show_playback_frame(self, record):
        try:
            source, note = self.playback_frame_image(record)
            self.playback_photo = ImageTk.PhotoImage(ImageOps.contain(source, (650, 300)), master=self.window)
            self.playback_preview.configure(image=self.playback_photo)
            self.playback_caption.configure(text=date_label(record["captured_at"]) + " · " + record["label"] + " · " + note)
        except (OSError, ValueError) as exc:
            self.stop_evolution_playback()
            self.status.set("No se pudo reproducir esta visita: " + str(exc))

    def playback_frame_image(self, record, canvas_size=(720, 480)):
        """Build one labelled frame; align to T0 when a valid matrix exists."""
        import cv2
        import numpy as np
        from longitudinal_analysis import mask_overlay, normalized
        from longitudinal_insights import comparison_validity

        image, mask = self.store.load_images(record)
        records = sorted(self.followup_records(), key=lambda r: (r["captured_at"], r["id"]))
        reference = records[0] if records else record
        originals = getattr(self, "playback_originals", None)
        originals = originals.get() if originals is not None else False
        aligned = record["id"] == reference["id"]
        note = "Original · referencia inicial" if aligned else "Original · sin alineación fiable"
        if originals:
            note = "Original · sin ajuste geométrico"
        if not aligned and not originals:
            candidates = [
                row for row in self.saved_comparisons
                if row.get("previous_id") == reference["id"]
                and row.get("current_id") == record["id"]
            ]
            latest = max(candidates, key=lambda r: (str(r.get("created", "")), r["id"])) if candidates else None
            if latest and comparison_validity(latest, records) is None and latest["result"].get("comparable") and latest["result"].get("registration", {}).get("matrix") is not None:
                result = latest["result"]
                ref_image, ref_mask = self.store.load_images(reference)
                ref_image, ref_mask = normalized(ref_image, ref_mask)
                image, mask = normalized(image, mask)
                ref_image = Image.fromarray(ref_image)
                image, mask = Image.fromarray(image), Image.fromarray(mask.astype("uint8") * 255)
                matrix = np.asarray(result["registration"]["matrix"], dtype=float)
                image = Image.fromarray(cv2.warpAffine(np.asarray(image.convert("RGB")), matrix, ref_image.size))
                mask = Image.fromarray(cv2.warpAffine(np.asarray(mask.convert("L")), matrix, ref_image.size, flags=cv2.INTER_NEAREST))
                aligned = True
                note = "Alineada con la visita inicial · ajuste geométrico"
        source = mask_overlay(image, mask).convert("RGB")
        frame = Image.new("RGB", canvas_size, "white")
        fitted = ImageOps.contain(source, (canvas_size[0], canvas_size[1] - 54))
        frame.paste(fitted, ((canvas_size[0] - fitted.width) // 2, 0))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((0, canvas_size[1] - 54, canvas_size[0], canvas_size[1]), fill=(31, 41, 55))
        draw.text((14, canvas_size[1] - 43), date_label(record["captured_at"]) + " · " + record["label"], fill="white")
        draw.text((14, canvas_size[1] - 23), note, fill=(205, 214, 226))
        return frame, note

    def export_evolution_gif(self):
        records = sorted(self.followup_records(), key=lambda r: (r["captured_at"], r["id"]))
        if len(records) < 2:
            messagebox.showinfo("Evolución visual", "Se necesitan al menos dos fotografías para exportar una animación.", parent=self.window)
            return
        destination = filedialog.asksaveasfilename(
            parent=self.window,
            title="Guardar evolución visual",
            defaultextension=".gif",
            filetypes=(("GIF animado", "*.gif"),),
            initialfile="evolucion_lesion.gif",
        )
        if not destination:
            return
        try:
            frames = [self.playback_frame_image(record)[0].convert("P", palette=Image.Palette.ADAPTIVE) for record in records]
            frames[0].save(
                destination,
                save_all=True,
                append_images=frames[1:],
                duration=self.evolution_delay_ms(),
                loop=0,
                optimize=False,
                disposal=2,
            )
            self.status.set(f"GIF exportado con {len(frames)} visitas: {destination}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Evolución visual", "No se pudo crear el GIF: " + str(exc), parent=self.window)

    def export_evolution_video(self):
        import queue
        import threading
        from evolution_video import export_video
        if self.running or self.app.busy:
            self.status.set("Espera a que termine el proceso actual.")
            return
        records = sorted(self.followup_records(), key=lambda r: (r["captured_at"], r["id"]))
        if len(records) < 2:
            messagebox.showinfo("Vídeo de evolución", "Se necesitan al menos dos fotografías.", parent=self.window)
            return
        destination = filedialog.asksaveasfilename(parent=self.window, title="Guardar vídeo de evolución", defaultextension=".mp4", filetypes=(("Vídeo MP4", "*.mp4"),), initialfile="evolucion_lesion.mp4")
        if not destination:
            return
        messages = queue.Queue()
        comparisons = list(self.saved_comparisons)
        mode = self.selected_trend_mode()
        self.app.busy = True
        self.video_button.configure(state="disabled")
        self.video_progress["value"] = 0
        self.status.set("Generando vídeo local…")
        def work():
            try:
                export_video(self.store, records, comparisons, destination, mode, progress=lambda n, total: messages.put(("progress", n * 100 / total)))
                messages.put(("done", destination))
            except Exception as exc:
                messages.put(("error", str(exc)))
        def poll():
            try:
                while True:
                    kind, value = messages.get_nowait()
                    if kind == "progress":
                        self.video_progress["value"] = value
                    else:
                        self.app.busy = False
                        self.video_button.configure(state="normal")
                        if kind == "done":
                            self.status.set("Vídeo exportado: " + value)
                        else:
                            self.status.set("No se pudo exportar el vídeo.")
                            messagebox.showerror("Vídeo de evolución", value, parent=self.window)
                        return
            except queue.Empty:
                pass
            if not self.closed:
                self.window.after(150, poll)
            else:
                self.app.busy = False
        threading.Thread(target=work, daemon=True).start()
        self.window.after(150, poll)
