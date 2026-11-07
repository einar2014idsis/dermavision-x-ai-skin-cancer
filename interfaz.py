"""Interfaz local experimental. Seguimiento guarda imágenes solo por acción explícita."""

import json
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

import numpy as np
from PIL import Image, ImageOps, ImageTk
from capture_guide import CaptureGuide
from app_paths import MODEL_DIR
from ui_lifecycle import cancel_window_tasks
from semantic_gate import SemanticGate, CombinedGate
from domain_gate import DomainGate
from references import ReferenceIndex
from calibration import ScoreCalibration
from explainability import (
    occlusion_explanation,
    explanation_diagnostics,
    explanation_caption,
)

from ui_theme import (
    BACKGROUND as BG,
    SURFACE as PANEL,
    INK as TEXT,
    MUTED,
    ACCENT,
    configure_ttk,
)

CYAN = ACCENT
TECHNICAL_DETAILS = "\n\nDETALLES TÉCNICOS\n"


def describe_result(score, calibration=None):
    if not np.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Puntuación inválida.")
    calibration = calibration or ScoreCalibration()
    decision = calibration.decision(score)
    if decision == "uncertain":
        return (
            "RESULTADO NO CONCLUYENTE\n\nEl filtro aceptó el contenido, pero el "
            "clasificador se abstuvo. No se emite una clase.\n\n"
            "Siguiente paso: toma otra captura con luz, distancia y enfoque controlados. "
            "La abstención no confirma ni descarta cáncer."
            + TECHNICAL_DETAILS
            + f"Puntuación del modelo: {score*100:.1f} %\n"
            f"Umbral experimental: {calibration.threshold*100:.1f} %\n"
            f"Intervalo de abstención: {calibration.uncertain_low*100:.1f}–"
            f"{calibration.uncertain_high*100:.1f} %\n"
            f"Calibración: {calibration.source}. No es una probabilidad clínica."
        )
    pattern = "patrón maligno" if decision == "malignant" else "patrón benigno"
    return (
        f"CONTENIDO ACEPTADO\nClasificación experimental: {pattern}\n\n"
        "El filtro aceptó esta imagen para el análisis. La clase del modelo no confirma "
        "ni descarta cáncer.\n\nSiguiente paso: revisa la explicación visual y los detalles "
        "del resultado. Para guardar una visita, vuelve a Seguimiento."
        + TECHNICAL_DETAILS
        + f"Puntuaciones del modelo · calibración: {calibration.source}\n"
        f"Benigna: {(1-score)*100:.1f} %\nMaligna: {score*100:.1f} %\n\n"
        f"Descripción: la imagen se clasifica como {pattern} según la puntuación "
        f"del modelo y su umbral experimental de {calibration.threshold*100:.1f} %. "
        "\n\nEstas puntuaciones no son probabilidades clínicas ni un diagnóstico. "
        "El resultado requiere interpretación profesional."
    )


class App:
    def __init__(self, root, *, store_root=None, autoload_model=True, demo=False, authenticated=False):
        self.root = root
        self.store_root = store_root
        self.demo = demo
        self.authenticated = authenticated
        self.logout_requested = False
        root.title("DermaVision-X | Análisis individual")
        root.geometry(
            f"{min(1220, root.winfo_screenwidth()-40)}x{min(800, root.winfo_screenheight()-70)}"
        )
        root.minsize(1050, 720)
        root.configure(bg=BG)
        configure_ttk(root)
        self.frame = self.cap = self.model = None
        self.domain_gate = None
        self.calibration = ScoreCalibration()
        self.last_explanation = None
        self.last_explanation_diagnostics = {}
        self.reference_index = None
        self.evolution_window = None
        self.analysis_job = None
        self.center = (0.5, 0.5)
        self.selection = None
        self.drag_start = None
        self.closed = False
        self.poll_job = None
        self.autoload_job = None
        self.busy = False
        self.activation_model = None
        self.activations = None
        self.node_info = tk.StringVar(
            value="Analiza una captura para ver activaciones reales."
        )
        self.camera_job = None
        self.full_image = False
        self.guide = CaptureGuide()
        self.assessment = None
        self.captured = False
        self.auto_capture = tk.BooleanVar(value=True)
        self.messages = queue.Queue()
        self.revision = 0
        self.status = tk.StringVar(value=(
            "DEMOSTRACIÓN SINTÉTICA · Comparación técnica sin clasificación diagnóstica."
            if demo else "SIN MODELO · Entrenamiento pendiente"
        ))
        self.result = tk.StringVar(value="Sin predicción")
        self.quality = tk.StringVar(
            value="Sin imagen · Se analizará la zona que revise"
        )
        self.metrics = tk.StringVar(
            value="Sensibilidad —   Especificidad —   F1 —   AUC —   Exactitud —"
        )
        self.experiment_folder = MODEL_DIR / "functional-02"
        header = tk.Frame(root, bg=BG)
        header.pack(fill="x")
        if self.authenticated:
            tk.Button(header, text="Cerrar sesión", command=self.logout, bg=PANEL, fg=TEXT,
                      relief="flat", padx=12, pady=7).pack(side="right", padx=8)
        tk.Button(
            header,
            text="← Volver a seguimiento",
            command=self.show_evolution,
            bg=ACCENT,
            fg="white",
            activebackground=CYAN,
            relief="flat",
            padx=14,
            pady=7,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="right", padx=28)
        self.capture_heading = self.label(header, "Análisis individual", 25, TEXT)
        self.capture_heading.pack(anchor="w", padx=28, pady=(16, 0))
        self.label(
            header,
            "DermaVision-X  ·  Captura → revisión de calidad → resultado experimental",
            10,
            MUTED,
        ).pack(anchor="w", padx=30, pady=(4, 12))
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=26, pady=10)
        for title, command in [
            ("Iniciar / nueva captura", self.camera),
            ("Detener cámara", self.stop_camera),
            ("Abrir imagen", self.open_image),
            ("Capturar", self.capture),
            ("Analizar captura", self.analyze),
        ]:
            primary = command in (self.camera, self.analyze)
            button = tk.Button(
                bar,
                text=title,
                command=command,
                bg=ACCENT if primary else PANEL,
                fg="white" if primary else TEXT,
                activebackground="#eeecfc",
                activeforeground=TEXT,
                disabledforeground="#64748b",
                relief="flat",
                padx=12,
                pady=10,
                font=("Segoe UI", 9, "bold" if primary else "normal"),
            )
            button.pack(side="left", padx=4)
            if command == self.capture:
                self.capture_button = button
                button.configure(state="disabled")
            if command == self.analyze:
                self.analyze_button = button
                button.configure(state="disabled")
        self.camera_id = tk.StringVar(value="0")
        self.label(bar, "Cámara:", 10, MUTED).pack(side="left", padx=(12, 3))
        tk.Spinbox(bar, from_=0, to=9, textvariable=self.camera_id, width=3).pack(
            side="left"
        )
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=28)
        body.pack_propagate(False)
        left, right = tk.Frame(body, bg=PANEL), tk.Frame(body, bg=PANEL)
        # Estado de compatibilidad; esta pantalla no usa referencias de entrenamiento.
        self.reference_status = tk.StringVar(value="")
        self.reference_cards = tk.Frame(body, bg=PANEL)
        right.configure(width=350)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        left.pack(side="left", fill="both", expand=True, padx=(0, 16))
        self.label(left, "01  VISTA DE CÁMARA", 12, CYAN).pack(
            anchor="w", padx=16, pady=16
        )
        self.preview = tk.Canvas(left, bg="#232637", highlightthickness=0, height=260)
        self.preview.pack(fill="both", expand=True, padx=15)
        self.preview.bind("<Configure>", lambda e: self.render())
        self.preview.bind("<ButtonPress-1>", self.begin_selection)
        self.preview.bind("<B1-Motion>", self.drag_selection)
        self.preview.bind("<ButtonRelease-1>", self.end_selection)
        tk.Label(
            left,
            text="Arrastra un recuadro alrededor de la lesión e incluye piel alrededor. La vista derecha muestra la zona exacta que se analizará.",
            bg=PANEL,
            fg=MUTED,
            wraplength=580,
        ).pack(padx=12, pady=10)
        tk.Button(
            left,
            text="Restablecer imagen completa",
            command=self.reset_selection,
            bg=BG,
            fg=CYAN,
            relief="flat",
        ).pack()
        tk.Checkbutton(
            left,
            text="Capturar y analizar automáticamente tras 2 segundos estables",
            variable=self.auto_capture,
            bg=PANEL,
            fg=TEXT,
            selectcolor=BG,
        ).pack()
        self.instruction = tk.StringVar(
            value="Inicie la cámara y coloque la zona dentro del recuadro."
        )
        tk.Label(
            left,
            textvariable=self.instruction,
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 12, "bold"),
            wraplength=580,
        ).pack(padx=12, pady=10)
        self.progress = ttk.Progressbar(left, maximum=100)
        self.progress.pack(fill="x", padx=20, pady=(0, 16))
        # Mantiene visibles la guía y los controles.
        for control in reversed(left.winfo_children()[2:]):
            control.pack_configure(side="bottom", before=self.preview)
        self.label(right, "02  ZONA QUE SE ANALIZARÁ", 12, CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        region_box = tk.Frame(right, bg="#f1f2f7", height=112)
        region_box.pack(fill="x", padx=16, pady=8)
        region_box.pack_propagate(False)
        self.region_preview = tk.Label(
            region_box,
            text="Sin captura\nAquí verás la región seleccionada",
            bg="#f1f2f7",
            fg=MUTED,
            font=("Segoe UI", 10),
        )
        self.region_preview.pack(fill="both", expand=True)
        quality_grid = tk.Frame(right, bg=PANEL)
        quality_grid.pack(fill="x", padx=10)
        self.check_labels = []
        for index, name in enumerate(
            ("Resolución", "Iluminación", "Enfoque", "Estabilidad")
        ):
            label = tk.Label(
                quality_grid,
                text=f"○  {name}",
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 10),
                anchor="w",
            )
            label.grid(row=index // 2, column=index % 2, sticky="w", padx=5, pady=4)
            self.check_labels.append((name, label))
        tk.Label(
            right,
            textvariable=self.quality,
            bg=PANEL,
            fg=MUTED,
            wraplength=270,
            justify="left",
        ).pack(padx=16, pady=6)
        self.label(right, "03  RESULTADO DE LA CAPTURA", 11, CYAN).pack(
            anchor="w", padx=16, pady=6
        )
        result_frame = tk.Frame(right, bg=PANEL)
        result_frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        self.result_text = tk.Text(
            result_frame,
            bg=PANEL,
            fg=TEXT,
            wrap="word",
            relief="flat",
            font=("Segoe UI", 11),
            width=27,
            height=10,
            state="disabled",
        )
        result_scroll = ttk.Scrollbar(result_frame, command=self.result_text.yview)
        result_scroll.pack(side="right", fill="y")
        self.result_text.pack(side="left", fill="both", expand=True)
        self.result_text.configure(yscrollcommand=result_scroll.set)
        self.explain_button = tk.Button(
            right,
            text="Ver explicación visual",
            command=self.show_explanation,
            bg=ACCENT,
            fg="white",
            disabledforeground="#64748b",
            activebackground=CYAN,
            relief="flat",
            state="disabled",
            pady=8,
        )
        self.explain_button.pack(
            side="bottom", before=result_frame, fill="x", padx=12, pady=(0, 12)
        )
        self.details_button = tk.Button(
            right, text="Ver detalles técnicos", command=self.show_result_details,
            bg=BG, fg=CYAN, relief="flat", state="disabled", pady=5,
        )
        self.details_button.pack(
            side="bottom", before=result_frame, fill="x", padx=12, pady=(0, 4)
        )
        self.result.trace_add("write", self.render_result)
        self.render_result()
        self.label(
            root,
            "PROTOTIPO DE INVESTIGACIÓN · No diagnostica cáncer ni determina estadio. Puede equivocarse.",
            10,
            "#946014",
        ).pack(side="bottom", before=body, pady=(3, 8))
        tk.Button(
            root,
            text="Ver evaluación técnica del modelo",
            command=self.show_results,
            bg=BG,
            fg=CYAN,
            relief="flat",
            font=("Segoe UI", 9),
        ).pack(side="bottom", before=body)
        tk.Label(
            root,
            textvariable=self.status,
            bg=BG,
            fg=CYAN,
            font=("Segoe UI", 10),
            wraplength=1000,
        ).pack(side="bottom", before=body, pady=(8, 6))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_job = root.after(100, self.poll)
        default_model = MODEL_DIR / "functional-02" / "model.keras"
        if autoload_model and default_model.exists() and default_model.with_name("metrics.json").exists():
            self.autoload_job = root.after(300, lambda: self.load_model(default_model))

    def label(self, parent, text, size, color):
        return tk.Label(
            parent, text=text, bg=parent.cget("bg"), fg=color, font=("Segoe UI", size)
        )

    def render_result(self, *args):
        summary, separator, _ = self.result.get().partition(TECHNICAL_DETAILS)
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", summary)
        self.result_text.configure(state="disabled")
        self.result_text.yview_moveto(0)
        self.details_button.configure(state="normal" if separator else "disabled")

    def show_result_details(self):
        if TECHNICAL_DETAILS not in self.result.get():
            return
        window = tk.Toplevel(self.root)
        window.title("Resultado individual · Detalles técnicos")
        window.geometry("560x500")
        window.configure(bg=BG)
        self.label(window, "Detalle de esta captura", 18, TEXT).pack(pady=(16, 8))
        box = tk.Text(window, wrap="word", relief="flat", bg=PANEL, fg=TEXT,
                      font=("Segoe UI", 11), padx=16, pady=16)
        scroll = ttk.Scrollbar(window, command=box.yview)
        scroll.pack(side="right", fill="y", pady=12)
        box.pack(fill="both", expand=True, padx=(16, 0), pady=12)
        box.configure(yscrollcommand=scroll.set)
        box.insert("1.0", self.result.get())
        box.configure(state="disabled")

    def show_explanation(self):
        if self.last_explanation is None:
            messagebox.showinfo(
                "Explicación no disponible", "Primero analiza una captura aceptada."
            )
            return
        window = tk.Toplevel(self.root)
        window.title("DermaVision-X · Influencia en una captura individual")
        window.configure(bg=BG)
        window.geometry("640x760")
        self.label(window, "ZONAS QUE MÁS INFLUYERON EN LA SALIDA", 16, CYAN).pack(
            pady=(18, 4)
        )
        tk.Label(
            window,
            text="Una captura · Mapa de influencia por oclusión. El color indica cómo cambia la salida al ocultar regiones. No localiza cáncer ni sustituye una explicación clínica.",
            bg=BG,
            fg=MUTED,
            wraplength=560,
            justify="center",
        ).pack(padx=25, pady=(0, 12))
        self.label(
            window,
            explanation_caption(getattr(self, "last_explanation_diagnostics", {})),
            10,
            MUTED,
        ).pack(padx=25, pady=(0, 10))
        window.winfo_children()[-1].configure(wraplength=570, justify="left")
        legend = tk.Frame(window, bg="#232637")
        legend.pack(padx=25, pady=(0, 10))
        for color, value in [
            ("#2aba6a", "Verde: influencia menor"),
            ("#ffdd30", "Amarillo: influencia mayor"),
        ]:
            item = tk.Frame(legend, bg="#232637")
            item.pack(side="left", padx=10)
            tk.Label(item, bg=color, width=2).pack(side="left", padx=(0, 5))
            tk.Label(item, text=value, bg="#232637", fg="white").pack(side="left")
        photo = ImageTk.PhotoImage(
            ImageOps.contain(self.last_explanation, (480, 480), Image.Resampling.LANCZOS)
        )
        panel = tk.Label(window, image=photo, bg="#232637")
        panel.image = photo
        panel.pack()
        tk.Button(
            window,
            text="Recalcular explicación",
            bg=ACCENT,
            fg="white",
            relief="flat",
            padx=14,
            pady=9,
            command=lambda: (window.destroy(), self.analyze()),
        ).pack(pady=12)

    def clear_references(self):
        for widget in self.reference_cards.winfo_children():
            widget.destroy()
        self.reference_status.set("Analiza una captura para buscar ejemplos.")

    def clear_explanation(self):
        self.last_explanation = None
        self.last_explanation_diagnostics = {}
        if hasattr(self, "explain_button"):
            self.explain_button.configure(state="disabled")

    def show_references(self, matches, error=None):
        self.clear_references()
        self.reference_status.set(
            error
            or (
                f"{len(matches)} ejemplos · ordenados por parecido visual."
                if matches
                else "No hay ejemplos disponibles."
            )
        )
        for match in matches:
            card = tk.Frame(self.reference_cards, bg=PANEL)
            card.pack(fill="x", pady=(0, 12))
            photo = ImageTk.PhotoImage(match["image"])
            preview = tk.Label(card, image=photo, bg=PANEL)
            preview.image = photo
            preview.pack(anchor="w")
            tk.Label(
                card,
                text="Etiqueta de referencia: " + match["label"],
                bg=PANEL,
                fg=TEXT,
                wraplength=205,
                anchor="w",
            ).pack(anchor="w")
            tk.Label(
                card,
                text="Fuente: " + match["source"],
                bg=PANEL,
                fg=MUTED,
                wraplength=205,
                justify="left",
            ).pack(anchor="w")

    def show_results(self):
        try:
            from resultados import show_results

            show_results(self.root, self.experiment_folder)
        except Exception as exc:
            messagebox.showerror("Resultados no disponibles", str(exc))

    def show_evolution(self):
        if self.busy:
            self.status.set(
                "Espera a que termine el análisis antes de volver al seguimiento."
            )
            return
        self.stop_camera()

        try:
            if self.evolution_window is not None and not self.evolution_window.closed:
                self.evolution_window.window.deiconify()
                self.evolution_window.window.lift()
                self.root.withdraw()
                return
            from longitudinal_ui import EvolutionWindow

            self.evolution_window = EvolutionWindow(self)
            self.root.withdraw()
        except Exception as exc:
            self.root.deiconify()
            messagebox.showerror("Seguimiento no disponible", str(exc))

    def load_capture_image(self, image):
        self.stop_camera()
        self.full_image = True
        self.selection = None
        self.guide.reset()
        self.update_frame(ImageOps.exif_transpose(image).convert("RGB"))
        self.captured = True
        self.refresh_actions()
        self.schedule_analysis()

    def draw_network(self, event=None):
        """Mantiene la compatibilidad con la interfaz anterior."""
        pass

    def region(self):
        if self.full_image:
            return self.frame
        return self.frame.crop(self.region_bounds())

    def region_bounds(self):
        w, h = self.frame.size
        if self.full_image:
            return (0, 0, w, h)
        if self.selection is not None:
            x1, y1, x2, y2 = self.selection
            return (
                int(x1 * w),
                int(y1 * h),
                min(w, max(int(x1 * w) + 1, int(x2 * w))),
                min(h, max(int(y1 * h) + 1, int(y2 * h))),
            )
        side = max(1, int(min(w, h) * 0.75))
        x = max(0, min(w - side, int(self.center[0] * w - side / 2)))
        y = max(0, min(h - side, int(self.center[1] * h - side / 2)))
        return (x, y, x + side, y + side)

    def image_position(self, event):
        if self.frame is None:
            return None
        w, h = max(self.preview.winfo_width(), 100), max(
            self.preview.winfo_height(), 100
        )
        fit = ImageOps.contain(self.frame, (w, h))
        x = (event.x - (w - fit.width) / 2) / fit.width
        y = (event.y - (h - fit.height) / 2) / fit.height
        return (x, y) if 0 <= x <= 1 and 0 <= y <= 1 else None

    def begin_selection(self, event):
        if not self.busy:
            self.drag_start = self.image_position(event)
            self.guide.reset()
            self.capture_button.configure(state="disabled")

    def drag_selection(self, event):
        point = self.image_position(event)
        if self.drag_start is None or point is None or self.busy:
            return
        a, b = self.drag_start, point
        bounds = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        if (bounds[2] - bounds[0]) * self.frame.width < 16 or (
            bounds[3] - bounds[1]
        ) * self.frame.height < 16:
            return
        self.selection = bounds
        self.full_image = False
        self.refresh_selection()

    def end_selection(self, event):
        self.drag_selection(event)
        self.drag_start = None
        self.guide.reset()
        if self.frame is not None and not self.busy:
            self.refresh_selection()

    def reset_selection(self):
        if self.frame is None or self.busy:
            return
        self.selection = None
        self.full_image = True
        self.guide.reset()
        self.refresh_selection()

    def refresh_selection(self):
        self.guide.reset()
        self.update_frame(self.frame)
        if self.cap is None:
            self.captured = True
            self.refresh_actions()
            if self.drag_start is None:
                self.schedule_analysis()

    def schedule_analysis(self):
        if self.analysis_job is not None:
            self.root.after_cancel(self.analysis_job)
            self.analysis_job = None
        if not self.captured or self.busy:
            return
        if not self.assessment or not all(self.assessment.checks[:3]):
            self.result.set(
                "No se puede evaluar esta foto.\n" + self.assessment.message
                if self.assessment
                else "Falta una imagen para evaluar."
            )
            return
        revision = self.revision
        self.result.set("Preparando el análisis de tu foto…")

        def run():
            self.analysis_job = None
            if not self.closed and revision == self.revision:
                self.analyze()

        self.analysis_job = self.root.after(350, run)

    def refresh_actions(self):
        loaded = (
            self.model is not None and self.domain_gate is not None and not self.busy
        )
        quality = self.assessment is not None and all(self.assessment.checks[:3])
        self.analyze_button.configure(
            state="normal" if loaded and quality and self.captured else "disabled"
        )

    def move_region(self, event):
        if self.frame is None or self.cap is None or self.busy:
            return
        w, h = self.preview.winfo_width(), self.preview.winfo_height()
        fit = ImageOps.contain(self.frame, (max(w, 1), max(h, 1)))
        x = (event.x - (w - fit.width) / 2) / fit.width
        y = (event.y - (h - fit.height) / 2) / fit.height
        if 0 <= x <= 1 and 0 <= y <= 1:
            self.center = (x, y)
            self.guide.reset()
            self.assessment = None
            self.revision += 1
            self.render()

    def open_image(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            filetypes=[("Imágenes", "*.jpg *.jpeg *.png")]
        )
        if not path:
            return
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
            self.load_capture_image(image)
            # Archivo estático: no necesita espera temporal; sí luz y nitidez.
            if not all(self.assessment.checks[:3]):
                self.instruction.set(self.assessment.message)
                self.result.set(
                    "No se puede evaluar esta foto.\n" + self.assessment.message
                )
                return
            self.captured = True
            self.refresh_actions()
            self.status.set(
                "Imagen recibida. El análisis aparecerá aquí automáticamente."
            )
            self.schedule_analysis()
        except Exception as exc:
            messagebox.showerror("No se pudo abrir la imagen", str(exc))

    def render(self):
        c = self.preview
        c.delete("all")
        w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        if self.frame is None:
            c.create_text(
                w / 2,
                h / 2,
                text="CÁMARA DE VIDEO\n\nPulsa Iniciar cámara",
                fill=MUTED,
                justify="center",
            )
            return
        im = ImageOps.contain(self.frame, (w, h))
        self.photo = ImageTk.PhotoImage(im)
        c.create_image(w / 2, h / 2, image=self.photo)
        x1, y1, x2, y2 = (
            (0, 0, *self.frame.size) if self.full_image else self.region_bounds()
        )
        sx, sy = im.width / self.frame.width, im.height / self.frame.height
        ox, oy = (w - im.width) / 2, (h - im.height) / 2
        color = "#65d8b3" if self.assessment and self.assessment.ready else "#efba77"
        c.create_rectangle(
            ox + x1 * sx,
            oy + y1 * sy,
            ox + x2 * sx,
            oy + y2 * sy,
            outline=color,
            width=3,
        )
        region = ImageOps.contain(self.region(), (268, 96))
        self.region_photo = ImageTk.PhotoImage(region)
        self.region_preview.configure(image=self.region_photo, text="")

    def update_frame(self, image):
        self.clear_references()
        if self.activations is not None:
            self.activations = None
            self.draw_network()
            self.node_info.set(
                "Nueva captura: vuelve a analizar para ver activaciones."
            )
        self.frame = image
        self.captured = False
        self.revision += 1
        self.clear_explanation()
        self.result.set("Sin predicción · captura actual")
        self.assessment = self.guide.evaluate(self.region(), static=self.cap is None)
        self.instruction.set(self.assessment.message)
        self.progress["value"] = 100 * self.assessment.progress
        for (name, label), ok in zip(self.check_labels, self.assessment.checks):
            label.configure(
                text=f'{"✓" if ok else "○"}  {name}', fg="#287a61" if ok else "#946014"
            )
        rw, rh = self.region().size
        self.quality.set(
            f"Zona: {rw} × {rh} px · Brillo: {self.assessment.brightness:.0f}/255\nNitidez: {self.assessment.sharpness:.0f} (mínimo 40; un valor alto no bloquea)\n"
            + (
                "Archivo/captura fija: no requiere estabilidad."
                if self.cap is None
                else f"Cámara: {self.frame.width} × {self.frame.height} · Estabilidad: {self.guide.hold_seconds:.0f} s"
            )
        )
        loaded = (
            self.model is not None and self.domain_gate is not None and not self.busy
        )
        self.capture_button.configure(
            state=(
                "normal"
                if self.cap is not None and self.assessment.ready and loaded
                else "disabled"
            )
        )
        if self.assessment.ready and not loaded:
            self.instruction.set("Imagen lista. Esperando modelo y filtro de objetos…")
        self.analyze_button.configure(state="disabled")
        self.render()

    def capture(self):
        if (
            self.busy
            or self.drag_start is not None
            or self.cap is None
            or not self.assessment
            or not self.assessment.ready
        ):
            return
        self.stop_camera()
        self.captured = True
        self.instruction.set("Captura tomada. Analizando la foto automáticamente…")
        self.progress["value"] = 100
        self.refresh_actions()
        self.schedule_analysis()

    def camera(self):
        if self.cap is not None or self.busy:
            return
        try:
            import cv2

            device = int(self.camera_id.get())
            if not 0 <= device <= 9:
                raise ValueError("Elige un índice de cámara entre 0 y 9.")
            self.cap = cv2.VideoCapture(device)
            if not self.cap.isOpened():
                raise RuntimeError(
                    "No se encuentra la cámara. Revisa conexión y permisos de Windows."
                )
            # Solicitudes al dispositivo: algunos controladores no las soportan.
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            autofocus_requested = self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            self.full_image = True
            self.selection = None
            self.center = (0.5, 0.5)
            self.guide.reset()
            self.assessment = None
            self.captured = False
            self.status.set(
                "Cámara activa · arrastre para seleccionar la zona. "
                + (
                    "Autofoco solicitado al dispositivo."
                    if autofocus_requested
                    else "El controlador no admite autofoco; ajuste la distancia o el enfoque físico."
                )
            )
            self.tick()
        except Exception as exc:
            self.stop_camera()
            messagebox.showerror("Cámara", str(exc))

    def tick(self):
        self.camera_job = None
        if self.cap is None:
            return
        import cv2

        ok, frame = self.cap.read()
        if not ok:
            self.stop_camera()
            messagebox.showerror("Cámara", "Se interrumpió la captura.")
            return
        self.update_frame(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        if (
            self.auto_capture.get()
            and self.drag_start is None
            and self.assessment.ready
            and not self.busy
            and self.model is not None
            and self.domain_gate is not None
        ):
            self.capture()
            return
        self.camera_job = self.root.after(60, self.tick)

    def stop_camera(self):
        self.capture_button.configure(state="disabled")
        self.guide.reset()
        if self.camera_job is not None:
            self.root.after_cancel(self.camera_job)
            self.camera_job = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def work(self, function):
        self.busy = True

        def run():
            try:
                self.messages.put(("ok", function()))
            except Exception as exc:
                self.messages.put(("error", str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def load_model(self, path=None):
        if self.busy:
            return
        if path is None:
            path = filedialog.askopenfilename(
                filetypes=[("Modelo propio Keras", "*.keras")]
            )
            if not path:
                return
            if not messagebox.askyesno(
                "Modelo de confianza",
                "Carga solo modelos creados por tu proyecto o de una fuente confiable. ¿Continuar?",
            ):
                return
        self.status.set("Cargando modelo…")
        self.clear_references()
        self.result.set("Sin predicción")
        self.revision += 1

        def load():
            import tensorflow as tf

            config = json.loads(
                Path(path).with_name("config.json").read_text(encoding="utf-8")
            )
            if (
                config.get("class_mapping") != {"benign": 0, "malignant": 1}
                or config.get("image_size") != 224
                or config.get("threshold") != 0.5
            ):
                raise ValueError(
                    "Configuración incompatible: requiere el modelo del pipeline DermaVision-X."
                )
            model = tf.keras.models.load_model(path, compile=False, safe_mode=True)
            if model.input_shape != (None, 224, 224, 3) or model.output_shape != (
                None,
                1,
            ):
                raise ValueError("Arquitectura de entrada/salida incompatible.")
            pooled = next(
                layer
                for layer in model.layers
                if isinstance(layer, tf.keras.layers.GlobalAveragePooling2D)
            )
            activation_model = tf.keras.Model(
                model.inputs[0],
                [
                    pooled.output,
                    model.get_layer("capa_oculta_32").output,
                    model.get_layer("capa_oculta_16").output,
                    model.output,
                ],
            )
            metrics_path = Path(path).with_name("metrics.json")
            values = (
                json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
            )
            calibration = ScoreCalibration.load(
                Path(path).with_name("calibration.json")
            )
            calibration_path = Path(path).with_name("calibration.json")
            if calibration_path.exists():
                calibration_report = json.loads(
                    calibration_path.read_text(encoding="utf-8")
                )
                selective = calibration_report.get("test_report_only", {}).get(
                    "after_abstention", {}
                )
                if selective:
                    values = {
                        **values,
                        **{
                            key: selective[key]
                            for key in (
                                "sensitivity",
                                "specificity",
                                "accuracy",
                                "f1",
                                "auc",
                            )
                            if key in selective
                        },
                        "coverage": selective.get("coverage"),
                    }
            gate_path = MODEL_DIR / "domain-02" / "config.json"
            reference_path = MODEL_DIR / "domain-01" / "gate.json"
            gate = (
                CombinedGate(
                    SemanticGate(MODEL_DIR / "clip-vit-base-patch32", gate_path),
                    DomainGate(reference_path, path, model),
                )
                if gate_path.exists() and reference_path.exists()
                else None
            )
            from domain_gate import feature_model

            references = ReferenceIndex(
                Path(path).with_name("manifest.csv"), feature_model(model)
            )
            return (
                "model",
                model,
                values,
                Path(path).parent,
                activation_model,
                gate,
                references,
                calibration,
            )

        self.work(load)

    def analyze(self):
        if self.busy:
            return
        if self.model is None or self.frame is None:
            messagebox.showinfo(
                "Falta preparación",
                "Primero inicia la cámara y espera a que se cargue el modelo entrenado. No se generan resultados simulados.",
            )
            return
        if self.domain_gate is None:
            self.status.set(
                "Falta cargar el filtro de objetos. No se emite clasificación."
            )
            self.result.set("Imagen no verificada\nSin clasificación")
            return
        if (
            not self.captured
            or not self.assessment
            or not all(self.assessment.checks[:3])
        ):
            self.status.set("Primero obtenga una captura con calidad suficiente.")
            return
        image = self.region().copy()
        self.clear_references()
        revision = self.revision
        gate, model, calibration = self.domain_gate, self.model, self.calibration
        self.status.set("Verificando lesión frente a objetos…")
        self.result.set("Verificando imagen…")
        self.instruction.set(
            "Paso 1 de 2: verificando si se distingue una posible lesión…"
        )
        self.analyze_button.configure(state="disabled")

        def predict():
            decision = gate.assess(image)
            if decision.state != "accepted":
                return (
                    "analysis",
                    dict(
                        accepted=False, state=decision.state, message=decision.message
                    ),
                    revision,
                )
            self.messages.put(("progress", ("Clasificando posible lesión…", revision)))
            data = np.asarray(
                image.resize((224, 224), Image.Resampling.BILINEAR), dtype="float32"
            )[None]
            raw_score = float(model(data, training=False).numpy()[0, 0])
            if not np.isfinite(raw_score) or not 0 <= raw_score <= 1:
                raise ValueError("Salida del modelo inválida.")
            score = calibration.apply(raw_score)
            decision = calibration.decision(score)
            self.messages.put(
                ("score", ({"score": score, "decision": decision}, revision))
            )
            explanation = None
            explanation_error = None
            explanation_stats = {}
            if decision != "uncertain":
                try:
                    explanation, heat = occlusion_explanation(
                        model, image, decision, display="magnitude-green-yellow"
                    )
                    explanation_stats = explanation_diagnostics(explanation, heat)
                except Exception as exc:
                    explanation_error = str(exc)
            return (
                "analysis",
                dict(
                    accepted=True,
                    score=score,
                    raw_score=raw_score,
                    decision=decision,
                    explanation=explanation,
                    explanation_error=explanation_error,
                    explanation_diagnostics=explanation_stats,
                    matches=[],
                    reference_error=None,
                ),
                revision,
            )

        self.work(predict)

    def poll(self):
        if self.closed:
            return
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
        try:
            kind, value = self.messages.get_nowait()
            if kind == "score":
                if value[1] == self.revision:
                    self.result.set(
                        describe_result(value[0]["score"], self.calibration)
                    )
                    self.status.set(
                        "Resultado disponible · Preparando explicación visual…"
                    )
                else:
                    self.status.set("Captura cambiada · Resultado anterior descartado")
                self.poll_job = self.root.after(100, self.poll)
                return
            if kind == "progress":
                if value[1] == self.revision:
                    self.instruction.set("Paso 2 de 2: " + value[0])
                self.poll_job = self.root.after(100, self.poll)
                return
            self.busy = False
            if kind == "error":
                self.result.set("No se pudo analizar\nSin clasificación")
                self.status.set(
                    "Operación fallida · "
                    + (
                        "Modelo anterior conservado"
                        if self.model is not None
                        else "Sin modelo"
                    )
                )
                messagebox.showerror("Operación fallida", value)
            elif value[0] == "model":
                self.model = value[1]
                self.domain_gate = value[5]
                self.activation_model = value[4]
                self.reference_index = value[6] if len(value) > 6 else None
                self.calibration = value[7] if len(value) > 7 else ScoreCalibration()
                self.activations = None
                self.draw_network()
                self.experiment_folder = value[3]
                if not self.captured:
                    self.status.set(
                        "Modelo y filtro experimental cargados. Inicie cámara o abra una imagen."
                        if self.domain_gate
                        else "Filtro de objetos no disponible; clasificación bloqueada."
                    )
                self.metrics.set(
                    "   ".join(
                        (
                            f"{title}: {value[2][key]:.3f}"
                            if key in value[2]
                            else f"{title}: —"
                        )
                        for key, title in [
                            ("sensitivity", "Sensibilidad"),
                            ("specificity", "Especificidad"),
                            ("f1", "F1"),
                            ("auc", "AUC"),
                            ("accuracy", "Exactitud"),
                            ("coverage", "Cobertura"),
                        ]
                    )
                )
                self.refresh_actions()
                if self.captured:
                    self.schedule_analysis()
            elif value[0] == "analysis" and value[2] == self.revision:
                if not value[1]["accepted"]:
                    self.show_references(
                        [], "Sin comparación: imagen rechazada o no concluyente."
                    )
                    self.result.set(
                        "IMAGEN RECHAZADA\nEl filtro no aceptó el contenido como lesión cutánea.\n\n"
                        "Siguiente paso: elige una foto de la lesión con piel alrededor. "
                        "No se emite clasificación."
                        if value[1]["state"] == "rejected"
                        else "RESULTADO NO CONCLUYENTE\nEl filtro no distingue una lesión "
                        "con suficiente confianza.\n\nSiguiente paso: ajusta el encuadre "
                        "y repite la captura. No se emite clasificación."
                    )
                    self.status.set(value[1]["message"])
                else:
                    score = value[1]["score"]
                    self.result.set(describe_result(score, self.calibration))
                    self.last_explanation = value[1].get("explanation")
                    self.last_explanation_diagnostics = value[1].get(
                        "explanation_diagnostics", {}
                    )
                    self.explain_button.configure(
                        state=(
                            "normal"
                            if self.last_explanation is not None
                            else "disabled"
                        )
                    )
                    if value[1].get("decision") == "uncertain":
                        self.show_references(
                            [],
                            "Sin comparación: el clasificador se abstuvo por incertidumbre.",
                        )
                        self.status.set(
                            "Resultado no concluyente · Repita la captura; no se emite una clase."
                        )
                    else:
                        self.show_references(
                            value[1].get("matches", []), value[1].get("reference_error")
                        )
                        self.status.set(
                            "Filtro superado. Resultado calibrado internamente; no confirma ni descarta cáncer."
                            + (
                                " Explicación visual no disponible: "
                                + value[1]["explanation_error"]
                                if value[1].get("explanation_error")
                                else ""
                            )
                        )
                self.instruction.set(
                    "Proceso terminado. Puede ajustar el recuadro o tomar otra captura."
                )
                self.refresh_actions()
            else:
                self.status.set("Captura cambiada · Resultado anterior descartado")
        except queue.Empty:
            pass
        self.poll_job = self.root.after(100, self.poll)

    def logout(self):
        if self.busy or (self.evolution_window is not None and self.evolution_window.running):
            self.status.set("Espera a que termine el proceso antes de cerrar sesión.")
            return
        self.logout_requested = True
        self.close()

    def close(self):
        if self.evolution_window is not None and self.evolution_window.running:
            self.status.set(
                "Espera a que termine el guardado de la comparación longitudinal antes de cerrar."
            )
            return
        if self.evolution_window is not None and not self.evolution_window.closed:
            self.evolution_window.close()
        self.closed = True
        self.stop_camera()
        for job in (self.poll_job, self.autoload_job, self.analysis_job):
            if job is not None:
                self.root.after_cancel(job)
        cancel_window_tasks(self.root)
        self.root.destroy()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="DermaVision-X: análisis individual y seguimiento longitudinal."
    )
    parser.add_argument(
        "--seguimiento",
        action="store_true",
        help="Abrir el seguimiento longitudinal (predeterminado).",
    )
    parser.add_argument(
        "--individual",
        action="store_true",
        help="Abrir directamente la cámara y el análisis individual.",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Abrir un archivo separado con controles sintéticos, sin cargar modelos.",
    )
    args = parser.parse_args()
    if args.demo and args.individual:
        parser.error("La demostración corresponde al seguimiento; no combine --demo y --individual.")
    demo_root = None
    if args.demo:
        from capstone_demo import prepare_demo
        from app_paths import DATA_DIR

        demo_root = DATA_DIR / "demo_capstone"
        prepare_demo(demo_root)
    from app_paths import DATA_DIR
    from login_ui import require_login
    while True:
        root = tk.Tk()
        root.withdraw()
        if not args.demo and not require_login(root, DATA_DIR / "security" / "administrator.json"):
            root.destroy()
            break
        app = App(root, store_root=demo_root, autoload_model=not args.demo,
                  demo=args.demo, authenticated=not args.demo)
        if not args.individual:
            root.after(0, app.show_evolution)
        else:
            root.deiconify()
        root.mainloop()
        if not app.logout_requested:
            break
