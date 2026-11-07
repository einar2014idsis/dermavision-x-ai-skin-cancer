"""Capture and review saved follow-up photographs without changing individual analysis."""

import hashlib
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageOps, ImageTk

from capture_guide import CaptureGuide
from longitudinal_analysis import classify
from longitudinal_dashboard import action, text
from ui_theme import BACKGROUND, SURFACE, INK, MUTED, SUCCESS, WARNING


class CaptureReview:
    def __init__(self):
        self.image = None
        self.analysis = None
        self.explanation = None

    def clear(self):
        self.image = self.analysis = self.explanation = None

    def approve(self, image, analysis, explanation=None):
        self.clear()
        # Score uncertainty is different from a content filter that abstained.
        if (
            analysis.get("state") not in ("accepted", "uncertain")
            or (
                analysis.get("state") == "uncertain"
                and analysis.get("reason") != "score_uncertainty"
            )
            or not analysis.get("quality", {}).get("checks")
            or not all(analysis["quality"]["checks"])
        ):
            return False
        self.image = image.convert("RGB").copy()
        self.analysis = dict(analysis)
        self.explanation = explanation
        return True

    def matches(self, image):
        return (
            self.image is not None
            and self.image.size == image.size
            and self.image.tobytes() == image.convert("RGB").tobytes()
        )

    def snapshot(self, image):
        if not self.matches(image):
            raise ValueError(
                "La fotografía cambió o no superó los controles. Vuelve a verificarla."
            )
        return dict(self.analysis), self.explanation


class FollowupCaptureDialog:
    def __init__(self, owner, source="file", image=None, metadata=None):
        self.owner = owner
        self.app = owner.app
        self.source = source
        self.metadata = dict(metadata or {})
        self.review = CaptureReview()
        owner.capture_review = self.review
        self.image = None
        self.camera = None
        self.previous_reference = None
        self.reference_caption = "Sin foto anterior"
        self.autofocus_requested = False
        records = sorted(owner.records, key=lambda r: (r["captured_at"], r["id"]))
        if records:
            try:
                self.previous_reference, _ = owner.store.load_images(records[-1])
                previous_date = datetime.fromisoformat(records[-1]["captured_at"])
                self.reference_caption = "Foto anterior: " + previous_date.strftime("%d/%m/%Y")
            except (OSError, ValueError):
                pass
        self.assessment = None
        self.guide = CaptureGuide()
        self.pending = False
        self.closed = False
        self.job = None
        self.poll_job = None
        self.messages = queue.Queue()
        self.window = tk.Toplevel(owner.window)
        self.window.title(
            "Seguimiento · "
            + ("Tomar fotografía" if source == "camera" else "Cargar fotografía")
        )
        self.window.geometry("900x720")
        self.window.minsize(650, 600)
        self.window.configure(bg=BACKGROUND)
        self.window.transient(owner.window)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        text(self.window, "1 · Fotografía y revisión", 20, bold=True).pack(
            anchor="w", padx=20, pady=(16, 4)
        )
        self.stage_label = text(
            self.window, "PASO 1 DE 3 · Foto  →  2 · Contorno  →  3 · Fecha y guardar",
            10, INK, bold=True,
        )
        self.stage_label.pack(anchor="w", padx=20, pady=(0, 8))
        text(self.window, owner.context_label.cget("text"), 10, MUTED).pack(
            anchor="w", padx=20
        )
        text(
            self.window,
            "Incluye la lesión y piel alrededor. El filtro revisa el contenido antes de sugerir un contorno.",
            10,
            INK,
            wraplength=790,
            justify="left",
        ).pack(anchor="w", padx=20, pady=8)
        footer = tk.Frame(self.window, bg=BACKGROUND)
        footer.pack(side="bottom", fill="x", padx=20, pady=15)
        action(footer, "Cancelar", self.close).pack(side="left")
        self.retry = action(
            footer,
            "Repetir captura" if source == "camera" else "Elegir otra foto",
            self.replace,
        )
        self.retry.pack(side="left", padx=8)
        self.next_button = action(
            footer, "Continuar: revisar contorno", self.proceed, True
        )
        self.next_button.pack(side="right")
        self.next_button.configure(state="disabled")
        self.capture_button = action(footer, "Capturar", self.take, True)
        if source == "camera":
            self.capture_button.pack(side="right", padx=8)
        self.capture_button.configure(state="disabled")
        self.auto_capture = tk.BooleanVar(master=self.window, value=True)
        if source == "camera":
            tk.Checkbutton(self.window, text="Capturar automáticamente tras 2 segundos estables",
                           variable=self.auto_capture, bg=BACKGROUND, fg=INK).pack(fill="x", padx=20)
        self.status = text(
            self.window,
            "Preparando fotografía…",
            11,
            INK,
            bold=True,
            wraplength=790,
            justify="left",
        )
        self.status.pack(side="bottom", fill="x", padx=20, pady=8)
        checks = tk.Frame(self.window, bg=SURFACE)
        checks.pack(side="bottom", fill="x", padx=20, pady=8)
        self.check_labels = []
        self.reference_overlay = tk.BooleanVar(master=self.window, value=False)
        tk.Checkbutton(
            self.window, text=self.reference_caption + " · superponer como guía",
            variable=self.reference_overlay, command=self.render, bg=BACKGROUND, fg=INK,
            state="normal" if self.previous_reference is not None else "disabled",
        ).pack(fill="x", padx=20)
        self.preview_caption = text(
            self.window, "Foto original · se conservan las proporciones", 9, MUTED,
            wraplength=790, justify="left",
        )
        self.preview_caption.pack(fill="x", padx=20)
        text(self.window, "Distancia: ajuste manual; no se estima en centímetros. Encuadre: conserva piel alrededor y una posición similar a la anterior.", 9, MUTED, wraplength=790).pack(fill="x", padx=20)
        for column, name in enumerate(
            ("Resolución", "Iluminación", "Enfoque", "Estabilidad")
        ):
            checks.columnconfigure(column, weight=1)
            label = text(checks, "○ " + name, 10, MUTED)
            label.grid(row=0, column=column, padx=5, pady=12, sticky="w")
            self.check_labels.append((name, label))
        self.preview = tk.Label(
            self.window, bg=SURFACE, text="Sin fotografía", fg=MUTED
        )
        self.preview.pack(fill="both", expand=True, padx=20, pady=5)
        self.preview.bind("<Configure>", lambda event: self.render())
        if image is not None:
            self.load_image(image, self.metadata)
        elif source == "camera":
            self.start_camera()
        else:
            self.choose_file()

    def render(self):
        if self.image is None:
            return
        source = self.image
        if self.reference_overlay.get() and self.previous_reference is not None:
            guide = ImageOps.pad(self.previous_reference.convert("RGB"), source.size, color="#ffffff")
            source = Image.blend(source.convert("RGB"), guide, 0.28)
            self.preview_caption.configure(
                text=self.reference_caption + " · GUÍA VISUAL SIN ALINEAR. "
                "La superposición no se analiza ni se guarda; no verifica identidad.",
                fg=WARNING,
            )
        else:
            self.preview_caption.configure(
                text=f"Foto original · {source.width} × {source.height} px · "
                "se conservan las proporciones", fg=MUTED,
            )
        photo = ImageTk.PhotoImage(
            ImageOps.contain(
                source,
                (
                    max(200, self.preview.winfo_width()),
                    max(150, self.preview.winfo_height()),
                ),
            ),
            master=self.window,
        )
        self.preview.configure(image=photo, text="")
        self.preview.photo = photo

    def show_quality(self, assessment, live=False):
        self.assessment = assessment
        for (name, label), ok in zip(self.check_labels, assessment.checks):
            caption = (
                "Estabilidad · no aplica"
                if name == "Estabilidad" and not live
                else name
            )
            label.configure(
                text=("✓ " if ok else "○ ") + caption, fg=SUCCESS if ok else WARNING
            )
            if not ok:
                advice = {"Resolución": "Aumenta la resolución", "Iluminación": "Evita sombras y reflejos", "Enfoque": "Ajusta distancia y enfoque", "Estabilidad": "Mantén la cámara quieta"}
                label.configure(text="○ " + name + "\n" + advice[name])
        self.status.configure(text=assessment.message, fg=INK)
        self.render()

    def choose_file(self):
        path = filedialog.askopenfilename(
            parent=self.window,
            title="Fotografía de esta lesión",
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png")],
        )
        if not path:
            if self.image is None:
                self.close()
            return
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
            self.load_image(
                image, dict(source_kind="file", source_filename=Path(path).name)
            )
        except Exception as exc:
            messagebox.showerror("Fotografía", str(exc), parent=self.window)

    def load_image(self, image, metadata=None):
        self.review.clear()
        self.stage_label.configure(text="PASO 1 DE 3 · Revisar foto  →  2 · Contorno  →  3 · Fecha y guardar")
        self.next_button.configure(state="disabled")
        self.image = ImageOps.exif_transpose(image).convert("RGB")
        self.metadata = dict(metadata or {})
        self.guide.reset()
        self.show_quality(self.guide.evaluate(self.image, static=True))
        if self.assessment.ready:
            self.verify()

    def start_camera(self):
        import cv2

        self.stop_camera()
        self.review.clear()
        self.stage_label.configure(text="PASO 1 DE 3 · Encuadrar y capturar  →  2 · Contorno  →  3 · Fecha y guardar")
        self.next_button.configure(state="disabled")
        self.guide.reset()
        try:
            device = int(self.app.camera_id.get())
            if not 0 <= device <= 9:
                raise ValueError("Revisa el índice de cámara en Configuración.")
            self.camera = cv2.VideoCapture(device)
            if not self.camera.isOpened():
                raise ValueError(
                    "No se pudo abrir la cámara. Revisa conexión y permisos."
                )
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.autofocus_requested = bool(self.camera.set(cv2.CAP_PROP_AUTOFOCUS, 1))
            self.tick()
        except Exception as exc:
            self.stop_camera()
            self.status.configure(text=str(exc), fg=WARNING)

    def tick(self):
        import cv2

        self.job = None
        if self.closed or self.camera is None:
            return
        ok, frame = self.camera.read()
        if not ok:
            self.stop_camera()
            self.status.configure(
                text="Se interrumpió la cámara. Pulsa Repetir captura.", fg=WARNING
            )
            return
        self.image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        self.show_quality(self.guide.evaluate(self.image), live=True)
        if not self.autofocus_requested:
            self.status.configure(
                text=self.assessment.message + " · Ajusta el enfoque físico o la distancia; "
                "el dispositivo no confirmó autofoco."
            )
        ready = (
            self.assessment.ready
            and self.app.model is not None
            and self.app.domain_gate is not None
        )
        self.capture_button.configure(state="normal" if ready else "disabled")
        if self.assessment.ready and not ready:
            self.status.configure(text="Imagen lista. Esperando a que carguen el modelo y el filtro de contenido…", fg=WARNING)
        if ready and self.auto_capture.get():
            self.take()
            return
        self.job = self.window.after(60, self.tick)

    def take(self):
        if (
            self.pending
            or self.camera is None
            or not self.assessment
            or not self.assessment.ready
        ):
            return
        self.metadata = dict(
            source_kind="camera",
            source_captured_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.stop_camera()
        self.verify()

    def verify(self):
        if self.pending or self.image is None:
            return
        self.review.clear()
        self.next_button.configure(state="disabled")
        if self.app.model is None or self.app.domain_gate is None:
            self.status.configure(
                text="Modelo o filtro no disponible. Espera su carga y vuelve a elegir la foto o repetir la captura.",
                fg=WARNING,
            )
            return
        self.pending = True
        self.stage_label.configure(text="PASO 1 DE 3 · Verificando foto…  →  2 · Contorno  →  3 · Fecha y guardar")
        self.owner.running = True
        self.app.busy = True
        self.retry.configure(state="disabled")
        self.status.configure(
            text="Revisando contenido y preparando el análisis…", fg=INK
        )
        image = self.image.copy()
        model, gate, calibration = (
            self.app.model,
            self.app.domain_gate,
            self.app.calibration,
        )
        model_path = self.app.experiment_folder / "model.keras"

        def run():
            try:
                analysis = classify(image, model, gate, calibration)
                explanation = None
                if analysis["state"] == "accepted":
                    from explainability import (
                        occlusion_explanation,
                        explanation_diagnostics,
                    )

                    try:
                        explanation, heat = occlusion_explanation(
                            model,
                            image,
                            analysis["label"],
                            display="magnitude-green-yellow",
                        )
                        analysis["explanation_diagnostics"] = explanation_diagnostics(
                            explanation, heat
                        )
                    except Exception as exc:
                        analysis["explanation_error"] = str(exc)
                analysis["model_sha256"] = (
                    hashlib.sha256(model_path.read_bytes()).hexdigest()
                    if model_path.is_file()
                    else None
                )
                analysis["calibration"] = {
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
                self.messages.put((image, analysis, explanation, None))
            except Exception as exc:
                self.messages.put((image, None, None, str(exc)))

        threading.Thread(target=run, daemon=True).start()
        self.poll_job = self.window.after(80, self.poll)

    def poll(self):
        self.poll_job = None
        try:
            image, analysis, explanation, error = self.messages.get_nowait()
        except queue.Empty:
            self.poll_job = self.window.after(80, self.poll)
            return
        self.pending = False
        self.owner.running = False
        self.app.busy = False
        self.retry.configure(state="normal")
        if error:
            self.stage_label.configure(text="PASO 1 DE 3 · Revisión fallida · Vuelve a elegir la foto")
            self.status.configure(
                text="No se pudo verificar la fotografía: " + error, fg=WARNING
            )
            return
        if self.review.approve(image, analysis, explanation):
            self.stage_label.configure(text="✓ Foto revisada  →  SIGUIENTE: 2 · Contorno  →  3 · Fecha y guardar")
            self.status.configure(
                text="Calidad y filtro de contenido superados. Continúa para revisar contorno y fecha."
                + (
                    " El clasificador no emitió una clase."
                    if analysis["state"] == "uncertain"
                    else ""
                ),
                fg=SUCCESS,
            )
            self.next_button.configure(state="normal")
        else:
            self.stage_label.configure(text="PASO 1 DE 3 · Foto pendiente de corrección")
            self.status.configure(
                text=analysis.get("message")
                or analysis.get("quality", {}).get("message")
                or "No se distingue una lesión con suficiente confianza. Utiliza otra fotografía.",
                fg=WARNING,
            )

    def replace(self):
        if self.pending:
            return
        if self.source == "camera":
            self.start_camera()
        else:
            self.choose_file()

    def proceed(self):
        if self.pending or self.image is None or not self.review.matches(self.image):
            return
        image = self.image.copy()
        metadata = dict(self.metadata, domain_verified=True)
        self.close()
        self.owner.editor(image, metadata)

    def stop_camera(self):
        if self.job:
            self.window.after_cancel(self.job)
            self.job = None
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        self.capture_button.configure(state="disabled")

    def close(self):
        if self.pending:
            self.status.configure(
                text="Espera a que termine la revisión antes de cerrar."
            )
            return
        if self.closed:
            return
        self.closed = True
        self.stop_camera()
        if self.poll_job:
            self.window.after_cancel(self.poll_job)
        self.window.destroy()
