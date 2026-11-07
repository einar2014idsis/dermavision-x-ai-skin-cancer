"""Presentación del seguimiento: tarjetas claras, navegación y datos reales."""

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageOps, ImageTk

from ui_theme import (
    BACKGROUND,
    SURFACE as WHITE,
    INK,
    MUTED as SECONDARY,
    BORDER as LINE,
    ACCENT as BLUE,
    DANGER as RED,
    SIDEBAR,
    SIDEBAR_ACTIVE,
    ACCENT_SOFT,
    configure_ttk,
)


def text(parent, value, size=10, color=INK, bold=False, **options):
    return tk.Label(
        parent,
        text=value,
        bg=parent.cget("bg"),
        fg=color,
        font=("Segoe UI", size, "bold" if bold else "normal"),
        **options,
    )


def action(parent, title, command, primary=False):
    return tk.Button(
        parent,
        text=title,
        command=command,
        bg=BLUE if primary else WHITE,
        fg=WHITE if primary else INK,
        activebackground=ACCENT_SOFT,
        activeforeground=INK,
        relief="flat",
        borderwidth=0,
        cursor="hand2",
        font=("Segoe UI", 10, "bold"),
        padx=13,
        pady=9,
        highlightthickness=1,
        highlightbackground=BLUE if primary else LINE,
    )


def card(parent, title):
    frame = tk.Frame(parent, bg=WHITE, highlightthickness=1, highlightbackground=LINE)
    text(frame, title, 11, bold=True).pack(anchor="w", padx=13, pady=(12, 8))
    return frame


class DashboardMixin:
    def build_dashboard(self):
        self.current_result = None
        self.thumbnail_photos = []
        self.window.configure(bg=BACKGROUND)
        self.window.geometry(
            f"{min(1360, self.window.winfo_screenwidth()-40)}x{min(900, self.window.winfo_screenheight()-80)}"
        )
        self.window.minsize(1000, 620)
        style = configure_ttk(self.window)

        style.configure("TCombobox", padding=6)
        style.configure("TButton", padding=(12, 8), font=("Segoe UI", 10))
        style.map(
            "Evo.Treeview",
            background=[("selected", ACCENT_SOFT)],
            foreground=[("selected", INK)],
        )
        style.configure("Evo.TNotebook", background=BACKGROUND, borderwidth=0)
        style.layout("Evo.TNotebook.Tab", [])
        style.configure(
            "Evo.Treeview",
            background=WHITE,
            fieldbackground=WHITE,
            foreground=INK,
            rowheight=34,
            font=("Segoe UI", 10),
        )
        style.configure("Evo.Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure(
            "Evo.Horizontal.TProgressbar", background=BLUE, troughcolor=LINE
        )
        sidebar = tk.Frame(self.window, bg=SIDEBAR, width=218)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        text(sidebar, "◈  DermaVision-X", 16, WHITE, True).pack(
            anchor="w", padx=17, pady=(25, 4)
        )
        text(sidebar, "Registro y comparación fotográfica", 9, "#b7c5d7").pack(
            anchor="w", padx=20
        )
        text(sidebar, "Prototipo de investigación", 9, "#8fa3bb").pack(
            anchor="w", padx=20, pady=(4, 28)
        )
        self.nav_buttons = {}
        for title, subtitle, command in [
            ("Personas y lesiones", "1 · Abre una ficha", lambda: self.navigate(2)),
            (
                "Fotografías y seguimiento",
                "Registra, compara y consulta",
                lambda: self.navigate(0),
            ),
            (
                "Historial y reportes",
                "Comparaciones guardadas",
                lambda: self.navigate(1),
            ),
            (
                "Análisis individual sin guardar",
                "Cámara en vivo o archivo",
                self.open_individual,
            ),
            ("Configuración", "Cámara y modelo", lambda: self.navigate(3)),
        ]:
            b = tk.Button(
                sidebar,
                text=f"{title}\n{subtitle}",
                anchor="w",
                justify="left",
                command=command,
                bg=SIDEBAR,
                fg=WHITE,
                activebackground=SIDEBAR_ACTIVE,
                activeforeground=WHITE,
                relief="flat",
                padx=20,
                pady=15,
                font=("Segoe UI", 10),
                cursor="hand2",
            )
            b.pack(fill="x")
            self.nav_buttons[title] = b
            b.bind("<Enter>", lambda event, widget=b: widget.configure(fg="#c7c3ff"))
            b.bind("<Leave>", lambda event, widget=b: widget.configure(fg=WHITE))
        if getattr(self.app, "authenticated", False):
            tk.Button(sidebar, text="Cerrar sesión", command=self.app.logout,
                      bg=SIDEBAR, fg=WHITE, relief="flat", anchor="w", padx=20, pady=12,
                      font=("Segoe UI", 10)).pack(fill="x")
        tk.Button(
            sidebar,
            text="Acerca de\nDermaVision-X EVO · v1",
            command=lambda: self.navigate(4),
            bg=SIDEBAR,
            fg="#c4d1e1",
            relief="flat",
            justify="left",
            anchor="w",
            padx=20,
            pady=22,
        ).pack(side="bottom", fill="x")
        content = tk.Frame(self.window, bg=BACKGROUND)
        content.pack(side="left", fill="both", expand=True)
        # Child captions must not resize the notebook or its hidden pages.
        content.pack_propagate(False)
        header = tk.Frame(content, bg=BACKGROUND)
        header.pack(fill="x", padx=20, pady=(18, 12))
        self.heading = text(header, "Seguimiento de lesión", 23, bold=True)
        self.heading.pack(anchor="w")
        self.subtitle = text(header, "", 11, SECONDARY, justify="left")
        self.subtitle.pack(anchor="w", pady=3)
        self.context_label = text(header, "", 11, INK, True, justify="left")
        self.context_label.pack(anchor="w", pady=(6, 0))
        self.professional_mode = tk.BooleanVar(value=True)
        tk.Checkbutton(
            header,
            text="Modo profesional · vista enfocada en seguimiento",
            variable=self.professional_mode,
            command=self.apply_professional_mode,
            bg=BACKGROUND,
            fg=SECONDARY,
            selectcolor=BACKGROUND,
            font=("Segoe UI", 9),
        ).pack(anchor="e", side="right", padx=4)
        header.bind(
            "<Configure>",
            lambda e: self.context_label.configure(wraplength=max(200, e.width - 20)),
            add="+",
        )
        header.bind(
            "<Configure>",
            lambda e: self.subtitle.configure(wraplength=max(200, e.width - 20)),
        )
        text(
            header,
            "Prototipo experimental · No sustituye la evaluación médica.",
            9,
            "#635bdb",
        ).pack(anchor="w", pady=(6, 0))
        tk.Label(
            content,
            textvariable=self.status,
            bg="#eeedf7",
            fg=SECONDARY,
            wraplength=1000,
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
            padx=15,
            pady=8,
        ).pack(side="bottom", fill="x")
        if getattr(self.app, "demo", False):
            text(
                content,
                "DEMOSTRACIÓN SINTÉTICA · Imágenes generadas por código; fechas ficticias. "
                "Archivo separado. No representa pacientes ni validación clínica.",
                10, "#8a5215", True, wraplength=850, justify="left",
            ).pack(side="top", fill="x", padx=20, pady=(0, 8))
        self.tabs = ttk.Notebook(content, style="Evo.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        self.pages = [tk.Frame(self.tabs, bg=BACKGROUND) for _ in range(5)]
        for page, title in zip(
            self.pages,
            ["Seguimiento", "Resultados", "Personas", "Configuración", "Acerca de"],
        ):
            page.pack_propagate(False)
            self.tabs.add(page, text=title)
        shell = self.pages[0]
        self.workspace_mode = "photos"
        workspace_bar = tk.Frame(shell, bg=BACKGROUND)
        workspace_bar.pack(fill="x", padx=18, pady=(0, 10))
        self.workspace_buttons = {}
        for key, title in [
            ("photos", "1 · Registrar fotos"),
            ("compare", "2 · Comparar fotos"),
            ("followup", "3 · Ver evolución"),
        ]:
            control = action(
                workspace_bar, title, lambda key=key: self.set_workspace_mode(key)
            )
            control.pack(side="left", fill="x", expand=True, padx=2)
            self.workspace_buttons[key] = control
        scroll = ttk.Scrollbar(shell, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.dashboard_canvas = tk.Canvas(
            shell, bg=BACKGROUND, highlightthickness=0, yscrollcommand=scroll.set
        )
        self.dashboard_canvas.pack(fill="both", expand=True)
        scroll.configure(command=self.dashboard_canvas.yview)
        dashboard = tk.Frame(self.dashboard_canvas, bg=BACKGROUND)
        self.lesion_overview = text(dashboard, "", 10, INK, justify="left", anchor="w", wraplength=950)
        self.lesion_overview.pack(fill="x", padx=18, pady=(4, 10))
        self.lesion_overview.bind("<Configure>", lambda e: self.lesion_overview.configure(wraplength=max(200, e.width - 16)))
        item = self.dashboard_canvas.create_window(
            0, 0, window=dashboard, anchor="nw", width=1000
        )
        dashboard.bind(
            "<Configure>",
            lambda e: self.dashboard_canvas.configure(
                scrollregion=self.dashboard_canvas.bbox("all")
            ),
        )
        self.dashboard_canvas.bind(
            "<Configure>",
            lambda e: self.dashboard_canvas.itemconfigure(item, width=e.width),
        )
        self.dashboard = dashboard
        self.window.bind("<MouseWheel>", self.scroll_dashboard, add="+")
        # Internal selectors retain stable record IDs for the processing layer.
        hidden = tk.Frame(dashboard)
        self.patient_choice = ttk.Combobox(hidden, state="readonly")
        self.lesion_choice = ttk.Combobox(hidden, state="readonly")
        toolbar = tk.Frame(dashboard, bg=BACKGROUND)
        toolbar.pack(fill="x", padx=18, pady=(0, 10))
        action(toolbar, "← Ficha de la persona", self.return_to_person).pack(
            side="left"
        )
        strip = card(dashboard, "Fotografías de esta lesión")
        strip.pack(fill="x", padx=18, pady=(0, 10))
        self.photo_strip = strip
        addbar = tk.Frame(strip, bg=WHITE)
        addbar.pack(fill="x", padx=12, pady=(0, 8))
        self.photo_addbar = addbar
        action(addbar, "+ Cargar fotografía", self.import_photo, True).pack(side="left")
        action(addbar, "Tomar con cámara", self.capture_in_lesion).pack(
            side="left", padx=8
        )
        self.flow_hint = text(strip, "", 11, INK, justify="left", wraplength=700)
        self.flow_hint.pack(anchor="w", padx=13, pady=(2, 8))
        strip.bind(
            "<Configure>",
            lambda e: self.flow_hint.configure(wraplength=max(200, e.width - 30)),
        )
        self.strip_canvas = tk.Canvas(strip, bg=WHITE, highlightthickness=0, height=180)
        self.strip_canvas.pack(fill="x", padx=12)
        strip_scroll = ttk.Scrollbar(
            strip, orient="horizontal", command=self.strip_canvas.xview
        )
        strip_scroll.pack(fill="x", padx=12, pady=(0, 8))
        self.strip_canvas.configure(xscrollcommand=strip_scroll.set)
        self.strip_frame = tk.Frame(self.strip_canvas, bg=WHITE)
        self.strip_canvas.create_window(0, 0, window=self.strip_frame, anchor="nw")
        self.strip_frame.bind(
            "<Configure>",
            lambda e: self.strip_canvas.configure(
                scrollregion=self.strip_canvas.bbox("all")
            ),
        )
        visit_actions = tk.Frame(strip, bg=WHITE)
        self.visit_actions = visit_actions
        self.photo_buttons = {}
        for key, title in [
            ("classify", "Analizar fotografía"),
            ("notes", "Notas y etiquetas"),
            ("date", "Editar fecha"),
            ("delete", "Eliminar"),
        ]:
            control = action(
                visit_actions, title, lambda key=key: self.selected_photo_action(key)
            )
            control.pack(side="left", padx=(0, 6))
            self.photo_buttons[key] = control
        self.classify_button = self.photo_buttons["classify"]
        self.compare_previous_button = action(
            visit_actions,
            "Comparar con visita anterior",
            self.compare_with_previous,
            True,
        )
        self.compare_previous_button.pack(side="right")
        selection_actions = tk.Frame(strip, bg=WHITE)
        self.selection_actions = selection_actions
        self.compare_button = action(
            selection_actions, "Volver a analizar estas fotos", self.compare_selected
        )
        self.compare_button.pack(side="left")
        action(selection_actions, "Quitar selección", self.clear_photo_selection).pack(
            side="left", padx=8
        )
        middle = tk.Frame(dashboard, bg=BACKGROUND)
        middle.pack(fill="x", padx=18)
        self.evidence_frame = middle
        for i in range(2):
            middle.columnconfigure(i, weight=1, uniform="main")
        compare = card(middle, "Fotografías seleccionadas")
        compare.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        self.compare_card = compare
        results = tk.Frame(dashboard, bg=BACKGROUND)
        results.pack(fill="x", padx=18, pady=10)
        self.result_details_frame = results
        for i in range(2):
            results.columnconfigure(i, weight=1, uniform="results")
        changes = card(results, "Mediciones de las dos fotografías seleccionadas")
        changes.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        classification = card(results, "Clasificación de la fotografía posterior")
        classification.grid(row=1, column=1, sticky="nsew")
        self.result_cards = (changes, classification)
        self.classification_heading = classification.winfo_children()[0]
        self.result_pair_label = text(
            changes, "", 11, INK, True, justify="left", wraplength=350
        )
        self.result_pair_label.pack(anchor="w", padx=12, pady=(0, 8))
        changes.bind(
            "<Configure>",
            lambda e: self.result_pair_label.configure(
                wraplength=max(180, e.width - 30)
            ),
            add="+",
        )
        self.compare_heading = compare.winfo_children()[0]
        text(compare, "Evidencia visual: revisa las fotos, el encuadre y los mapas. El informe PDF resume el seguimiento para compartirlo.", 9, SECONDARY, justify="left", wraplength=760).pack(fill="x", padx=12, pady=(0, 6))
        self.changes_heading = changes.winfo_children()[0]
        self.comparison_mode = ttk.Combobox(
            hidden,
            state="readonly",
            values=(
                "Seguimiento de la misma lesión",
                "Comparación visual (imágenes distintas)",
            ),
        )
        self.comparison_mode.current(0)
        self.previous = ttk.Combobox(hidden, state="readonly")
        self.current = ttk.Combobox(hidden, state="readonly")
        self.pair_summary = text(compare, "", 11, INK, justify="left", wraplength=760)
        self.pair_summary.pack(fill="x", padx=12, pady=(4, 8))
        compare.bind(
            "<Configure>",
            lambda e: self.pair_summary.configure(wraplength=max(220, e.width - 30)),
        )
        self.readiness_frame = tk.Frame(compare, bg=ACCENT_SOFT)
        self.readiness_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.readiness_title = text(
            self.readiness_frame, "PENDIENTE DE COMPARACIÓN", 10, BLUE, True
        )
        self.readiness_title.pack(anchor="w", padx=12, pady=(9, 2))
        self.readiness_detail = text(
            self.readiness_frame,
            "Elige dos fotografías de la misma lesión.",
            10,
            INK,
            justify="left",
            wraplength=730,
        )
        self.readiness_detail.pack(anchor="w", fill="x", padx=12, pady=(0, 10))
        self.confidence_label = text(self.readiness_frame, "Controles técnicos: pendientes", 10, SECONDARY, justify="left", wraplength=730)
        self.confidence_label.pack(fill="x", padx=12, pady=(0, 8))
        self.pair_checks = text(self.readiness_frame, "", 9, SECONDARY, justify="left", wraplength=730)
        self.pair_checks.pack(fill="x", padx=12, pady=(0, 8))
        action(compare, "Ampliar las dos fotos · zoom sincronizado", self.open_pair_inspector).pack(anchor="w", padx=12, pady=4)
        self.readiness_frame.bind(
            "<Configure>",
            lambda e: self.readiness_detail.configure(
                wraplength=max(220, e.width - 30)
            ),
        )
        self.pictures_frame = tk.Frame(compare, bg=WHITE)
        self.pictures_frame.pack(fill="x", padx=10, pady=10)
        self.pictures_frame.bind("<Configure>", lambda e: self.render_images())
        self.picture_widgets = []
        self.slot_buttons = []
        for i, title in enumerate(["Anterior", "Actual"]):
            panel = tk.Frame(self.pictures_frame, bg="#f1f2f7", height=300, width=1)
            panel.grid(row=0, column=i, sticky="ew", padx=3)
            panel.pack_propagate(False)
            panel.bind("<Configure>", lambda event: self.render_images())
            self.pictures_frame.columnconfigure(i, weight=1, uniform="photo")
            caption = text(panel, title, 9, SECONDARY)
            caption.pack(pady=5)
            control = action(
                panel, "Elegir foto", lambda side=i: self.open_comparison_picker(side)
            )
            control.pack(side="bottom", fill="x", padx=8, pady=5)
            self.slot_buttons.append(control)
            picture = tk.Label(panel, bg="#f1f2f7")
            picture.pack(expand=True)
            self.picture_widgets.append((caption, picture))
        self.overlay_mode = tk.BooleanVar(value=False)
        self.overlay_check = tk.Checkbutton(
            compare,
            text="Activar comparador / superposición de fotos alineadas",
            variable=self.overlay_mode,
            command=self.render_images,
            bg=WHITE,
            fg=SECONDARY,
            selectcolor=WHITE,
            font=("Segoe UI", 9),
            state="disabled",
        )
        self.overlay_check.pack(anchor="w", padx=10)
        self.wipe_mode = tk.BooleanVar(value=True)
        tk.Checkbutton(compare, text="Comparador deslizante antes / después", variable=self.wipe_mode, command=self.render_images, bg=WHITE, fg=SECONDARY).pack(anchor="w", padx=10)
        self.blend = ttk.Scale(
            compare,
            from_=0,
            to=1,
            value=0.5,
            command=lambda value: self.render_images(),
        )
        self.blend.pack(fill="x", padx=16, pady=5)
        self.comparison_note = text(
            changes, "", 11, INK, justify="left", wraplength=350
        )
        self.comparison_note.pack(anchor="w", fill="x", padx=12, pady=(0, 8))
        changes.bind(
            "<Configure>",
            lambda e: self.comparison_note.configure(wraplength=max(180, e.width - 30)),
        )
        self.change_values = {}
        for key, title in [
            ("area", "Área aparente"),
            ("shape", "Forma"),
            ("asymmetry", "Asimetría"),
            ("border", "Borde"),
            ("color", "Color"),
            ("texture", "Textura"),
            ("deep", "MobileNet"),
        ]:
            row = tk.Frame(changes, bg=WHITE)
            row.pack(fill="x", padx=12, pady=4)
            text(row, title, 10, SECONDARY).pack(side="left")
            value = text(row, "—", 10, INK, True)
            value.pack(side="right")
            self.change_values[key] = value
            if key == "deep":
                row.pack_forget()
        action(changes, "Ver mediciones y calidad", self.open_analysis_detail).pack(
            anchor="w", padx=12, pady=8
        )
        index_box = tk.Frame(changes, bg="#eeecfc")
        index_box.pack(fill="x", padx=12, pady=12)
        self.index_heading = text(
            index_box, "Índice descriptivo de cambio", 10, BLUE, True
        )
        self.index_heading.pack(anchor="w", padx=10, pady=(8, 0))
        self.index_value = text(index_box, "— / 100", 15, BLUE, True)
        self.index_value.pack(anchor="w", padx=10)
        text(
            index_box,
            "Resumen auxiliar de diferencias; no mide gravedad.",
            9,
            SECONDARY,
            wraplength=300,
            justify="left",
        ).pack(anchor="w", padx=10, pady=4)
        self.index_level = text(index_box, "Pendiente de comparación", 9, SECONDARY)
        self.index_level.pack(anchor="w", padx=10, pady=(0, 8))
        self.class_label = text(
            classification,
            "Sin análisis actual",
            11,
            SECONDARY,
            True,
            wraplength=205,
            justify="left",
        )
        self.class_label.pack(anchor="w", padx=13, pady=(5, 8))
        self.classification_context = text(
            classification, "Analiza una fotografía para consultar su resultado.",
            10, SECONDARY, justify="left", wraplength=350,
        )
        self.classification_context.pack(fill="x", padx=13, pady=10)
        classification.bind("<Configure>", lambda e: self.classification_context.configure(wraplength=max(180, e.width - 30)), add="+")
        self.malignant_value = text(classification, "— %", 25, RED, True)
        self.malignant_value.pack(anchor="w", padx=13)
        text(classification, "Puntuación maligna", 10, SECONDARY).pack(
            anchor="w", padx=13
        )
        self.malignant_bar = ttk.Progressbar(
            classification, maximum=100, style="Evo.Horizontal.TProgressbar"
        )
        self.malignant_bar.pack(fill="x", padx=13, pady=(7, 15))
        self.benign_value = text(classification, "— %", 23, INK, True)
        self.benign_value.pack(anchor="w", padx=13)
        text(classification, "Puntuación benigna", 10, SECONDARY).pack(
            anchor="w", padx=13
        )
        self.benign_bar = ttk.Progressbar(
            classification, maximum=100, style="Evo.Horizontal.TProgressbar"
        )
        self.benign_bar.pack(fill="x", padx=13, pady=(7, 15))
        text(
            classification,
            "Calibración interna con abstención.\nNo son probabilidades clínicas.",
            9,
            SECONDARY,
            wraplength=210,
            justify="left",
        ).pack(anchor="w", padx=13, pady=8)
        self.build_photo_analysis(dashboard)
        lower = tk.Frame(dashboard, bg=BACKGROUND)
        lower.pack(fill="x", padx=18, pady=10)
        self.lower_results = lower
        lower.pack(fill="x", padx=18, pady=10, after=self.evidence_frame)
        for i in range(2):
            lower.columnconfigure(i, weight=1, uniform="lower")
        evolution = card(lower, "Tablero de seguimiento en el tiempo")
        evolution.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.table_heading = evolution.winfo_children()[0]
        self.chart_heading = text(
            evolution, "Comparaciones en el tiempo", 11, INK, True
        )
        self.timeline_table = ttk.Treeview(
            evolution,
            columns=("pair", "index", "state"),
            show="headings",
            height=4,
            style="Evo.Treeview",
        )
        for key, title, width in [
            ("pair", "Fechas comparadas", 210),
            ("index", "Índice / 100", 80),
            ("state", "Estado", 130),
        ]:
            self.timeline_table.heading(key, text=title)
            self.timeline_table.column(key, width=width, minwidth=55)
        self.timeline_table.pack(fill="x", padx=12, pady=(0, 8))
        self.build_evolution_controls(evolution)
        self.chart = tk.Canvas(
            evolution, bg=WHITE, height=220, width=1, highlightthickness=0
        )
        self.build_period_summary(evolution)
        self.chart_toggle = tk.BooleanVar(value=True)
        tk.Checkbutton(
            evolution,
            text="Mostrar línea de tiempo",
            variable=self.chart_toggle,
            command=self.toggle_chart,
            bg=WHITE,
            fg=INK,
            selectcolor=WHITE,
        ).pack(anchor="w", padx=12)
        self.chart.bind("<Configure>", lambda e: self.draw_timeline())
        self.chart.bind("<Button-1>", self.open_trend_capture)
        self.chart_note = text(
            evolution,
            "Cada punto corresponde a una comparación.\nLos intervalos pueden ser distintos.",
            9,
            SECONDARY,
            justify="left",
        )
        self.timeline_table.pack_forget()
        # The timeline is a primary follow-up artefact, so it is visible from
        # the first visit instead of requiring the user to discover a toggle.
        self.toggle_chart()
        evolution.bind(
            "<Configure>",
            lambda e: self.chart_note.configure(wraplength=max(140, e.width - 30)),
            add="+",
        )
        map_holder = tk.Frame(dashboard, bg=BACKGROUND)
        map_holder.pack(fill="x", padx=18, pady=10)
        self.map_holder = map_holder
        map_holder.columnconfigure(0, weight=1)
        map_card = card(
            map_holder, "Mapa de diferencias entre las dos fotografías seleccionadas"
        )
        map_card.grid(row=0, column=0, sticky="nsew")
        self.map_card = map_card
        controls = tk.Frame(map_card, bg=WHITE)
        controls.pack(fill="x", padx=12, pady=(0, 8))
        self.map_zoom = tk.BooleanVar(value=True)
        tk.Checkbutton(
            controls,
            text="Acercamiento a la lesión",
            variable=self.map_zoom,
            command=self.render_images,
            bg=WHITE,
            fg=SECONDARY,
            selectcolor=WHITE,
            font=("Segoe UI", 10),
        ).pack(side="left")
        action(controls, "Abrir mapa de diferencias", self.open_difference_map).pack(
            side="right"
        )
        map_panel = tk.Frame(map_card, bg=WHITE, height=385, width=1)
        map_panel.pack(fill="x")
        map_panel.pack_propagate(False)
        self.map_panel = map_panel
        map_panel.bind("<Configure>", lambda event: self.render_images())
        caption = text(map_panel, "Sin comparación", 9, SECONDARY)
        caption.pack()
        picture = tk.Label(map_panel, bg=WHITE)
        picture.pack(expand=True)
        self.picture_widgets.append((caption, picture))
        self.map_note = text(
            map_card,
            "Cian: anterior · Naranja: actual\nColor cálido: mayor diferencia visual.",
            9,
            SECONDARY,
            justify="left",
            wraplength=260,
        )
        self.map_note.pack(anchor="w", padx=12, pady=8)
        map_card.bind(
            "<Configure>",
            lambda event: self.map_note.configure(
                wraplength=max(220, event.width - 30)
            ),
        )
        details = card(dashboard, "Descripción y observaciones")
        details.pack(fill="x", padx=18, pady=(0, 18))
        self.details_card = details
        self.result_explanation = text(
            details, "", 11, INK, justify="left", anchor="w", wraplength=750
        )
        self.result_explanation.pack(fill="x", padx=12, pady=(0, 12))
        details.bind(
            "<Configure>",
            lambda e: self.result_explanation.configure(
                wraplength=max(200, e.width - 30)
            ),
            add="+",
        )
        self.explanation_button = action(
            details, "Ver explicación de la clasificación", self.show_visit_explanation
        )
        self.explanation_button.configure(state="disabled")
        self.report = tk.Text(
            details,
            bg=WHITE,
            fg=SECONDARY,
            font=("Segoe UI", 10),
            wrap="word",
            height=9,
            width=1,
            relief="flat",
            state="disabled",
        )
        report_scroll = ttk.Scrollbar(details, command=self.report.yview)
        report_scroll.pack(side="right", fill="y")
        self.report.pack(fill="x", padx=12, pady=(0, 12))
        self.report.configure(yscrollcommand=report_scroll.set)
        self.report_scroll = report_scroll
        self.report_expanded = False
        self.report_toggle = action(
            details, "Ver detalles y observaciones", self.toggle_report_details
        )
        self.report_toggle.pack(anchor="w", padx=12, pady=(0, 12))
        self.report.pack_forget()
        report_scroll.pack_forget()
        self.conclusion_card = card(dashboard, "Resultado final de la comparación")
        self.conclusion_text = text(self.conclusion_card, "", 11, INK, justify="left", anchor="w", wraplength=750)
        self.conclusion_text.pack(fill="x", padx=16, pady=(2, 16))
        self.conclusion_card.bind("<Configure>", lambda e: self.conclusion_text.configure(wraplength=max(200, e.width - 40)))
        self.build_history_page()
        self.build_people_page()
        self.build_settings_page()
        about = card(self.pages[4], "Acerca de DermaVision-X EVO")
        about.pack(fill="x", padx=18, pady=12)
        text(
            about,
            "Seguimiento longitudinal de lesiones cutáneas.\n\n"
            "Conserva el análisis individual y compara fotografías fechadas de una misma lesión.\n"
            "El índice describe diferencias visuales; no diagnostica cáncer.\n"
            "Compara fotografías; no confirma crecimiento físico sin una referencia de escala.\n\n"
            "Las imágenes se almacenan localmente al guardar un registro.",
            11,
            SECONDARY,
            justify="left",
            wraplength=780,
        ).pack(anchor="w", padx=16, pady=15)
        self.navigate(2)
        self.apply_professional_mode()
        self.refresh_workspace_layout()

    def apply_professional_mode(self):
        """Keep the clinical workflow focused while leaving all features available."""
        focused = self.professional_mode.get()
        if not hasattr(self, "_technical_score_layout"):
            self._technical_score_layout = []
            for child in self.result_cards[1].winfo_children()[1:]:
                if child not in (self.class_label, self.classification_context) and child.winfo_manager() == "pack":
                    self._technical_score_layout.append((child, child.pack_info()))
        for child, layout in self._technical_score_layout:
            if focused:
                child.pack_forget()
            elif not child.winfo_manager():
                child.pack(**layout)
        # Camera analysis remains a primary entry point in either display mode.
        individual = self.nav_buttons.get("Análisis individual sin guardar")
        if individual and not individual.winfo_manager():
            individual.pack(fill="x", after=self.nav_buttons["Historial y reportes"])
        for title in ("Configuración",):
            button = self.nav_buttons.get(title)
            if button:
                if focused:
                    button.pack_forget()
                elif not button.winfo_manager():
                    button.pack(fill="x", before=self.nav_buttons["Personas y lesiones"])
        self.subtitle.configure(
            text=(
                "Registra fotografías, revisa su calidad y consulta la evolución de una lesión."
                if focused
                else "Vista completa: seguimiento, herramientas de análisis y configuración."
            )
        )

    def refresh_workspace_layout(self):
        """One place controls visibility: photo management, a pair, or the full series."""
        if self.closed or not hasattr(self, "map_holder"):
            return
        mode = self.workspace_mode
        analysis = {}
        identifier = self.heatmap_record_id()
        if identifier:
            try:
                analysis = self.store.record(identifier)["metadata"].get(
                    "classification", {}
                )
            except ValueError:
                identifier = None
        key = (
            mode,
            bool(self.current_result),
            tuple(self.selected_photo_ids),
            tuple(self.heatmap_ids),
            identifier,
            analysis.get("explanation"),
            analysis.get("explanation_diagnostics", {}).get("display_mode"),
        )
        if getattr(self, "_workspace_layout_key", None) == key:
            return
        self._workspace_layout_key = key
        for key, control in self.workspace_buttons.items():
            control.configure(
                bg=BLUE if key == mode else WHITE, fg=WHITE if key == mode else INK
            )
        groups = (
            self.photo_strip,
            self.evidence_frame,
            self.result_details_frame,
            self.photo_analysis_card,
            self.lower_results,
            self.map_holder,
            self.details_card,
            self.conclusion_card,
        )
        for frame in groups:
            frame.pack_forget()
        self.photo_addbar.pack_forget()
        if mode == "photos":
            self.photo_addbar.pack(
                fill="x", padx=12, pady=(0, 8), before=self.flow_hint
            )
        if mode == "followup":
            visible = [self.lower_results]
        elif mode == "compare":
            visible = [self.evidence_frame]
            if self.current_result:
                visible += [
                    self.conclusion_card,
                    self.details_card,
                    self.result_details_frame,
                    self.map_holder,
                    self.photo_analysis_card,
                ]
        else:
            visible = [self.photo_strip]
            if len(self.selected_photo_ids) == 1:
                visible += [
                    self.details_card,
                    self.result_details_frame,
                    self.photo_analysis_card,
                ]
        for frame in visible:
            frame.pack(fill="x", padx=18, pady=(0, 12))
        self.overlay_check.pack_forget()
        self.blend.pack_forget()
        if (
            mode == "compare"
            and self.current_result
            and self.current_result.get("comparable")
        ):
            self.overlay_check.pack(anchor="w", padx=10, after=self.pictures_frame)
            self.blend.pack(fill="x", padx=16, pady=5, after=self.overlay_check)
        self.heatmap_choice.pack_forget()
        self.heatmap_button.pack_forget()
        original_frame = self.heatmap_pictures[0].master
        map_frame = self.heatmap_pictures[1].master
        if mode == "compare":
            original_frame.grid()
            map_frame.grid(column=1, columnspan=1)
        else:
            original_frame.grid()
            map_frame.grid(column=1, columnspan=1)
        if mode == "compare" and len(self.heatmap_ids) > 1:
            self.heatmap_choice.pack(side="left", fill="x", expand=True)
        if mode == "compare":
            self.visit_actions.pack_forget()
        if identifier and analysis.get("state") == "accepted":
            self.heatmap_button.pack(side="left", padx=8)
        self.dashboard_canvas.configure(scrollregion=self.dashboard_canvas.bbox("all"))

    def toggle_report_details(self):
        self.report_expanded = not self.report_expanded
        if self.report_expanded:
            self.report_scroll.pack(side="right", fill="y")
            self.report.pack(fill="x", padx=12, pady=(0, 12), after=self.report_toggle)
        else:
            self.report.pack_forget()
            self.report_scroll.pack_forget()
        self.report_toggle.configure(
            text=(
                "Ocultar detalles y observaciones"
                if self.report_expanded
                else "Ver detalles y observaciones"
            )
        )

    def navigate(self, index, title=None):
        if index in (0, 1) and self.lesion_id is None:
            self.status.set("Primero abre una persona y selecciona una lesión.")
            index = 2
        self.tabs.select(index)
        names = [
            "Fotografías y seguimiento",
            "Historial y reportes",
            "Personas y lesiones",
            "Configuración",
            "Acerca de",
        ]
        descriptions = [
            "Registra y analiza fotografías. Compara dos fotos y consulta las visitas anteriores en Evolución.",
            "Consulta las comparaciones guardadas de la lesión seleccionada y exporta sus registros.",
            "Organiza personas mediante códigos y conserva un historial separado para cada lesión.",
            "Revisa la cámara, el modelo y la ubicación de los registros locales.",
            "Conoce el alcance y las limitaciones del prototipo de investigación.",
        ]
        self.heading.configure(text=title or names[index])
        self.subtitle.configure(text=descriptions[index])
        for key, b in self.nav_buttons.items():
            b.configure(
                bg=SIDEBAR_ACTIVE if key == (title or names[index]) else SIDEBAR
            )
        if index == 0:
            self.refresh_workspace_layout()
            self.dashboard_canvas.yview_moveto(0)
        if index == 3:
            self.refresh_settings()
        if hasattr(self, "person_rows"):
            self.update_context()

    def open_individual(self):
        self.window.withdraw()
        self.app.root.deiconify()
        self.app.root.lift()
        self.app.root.focus_force()

    def scroll_dashboard(self, event):
        index = self.tabs.index("current")
        if index not in (0, 3):
            return
        widget = event.widget
        if isinstance(widget, (tk.Text, ttk.Combobox, ttk.Scale)):
            return
        (self.dashboard_canvas if index == 0 else self.settings_canvas).yview_scroll(
            -int(event.delta / 120), "units"
        )

    def build_history_page(self):
        page = self.pages[1]
        self.history_context = text(page, "", 12, INK, True)
        self.history_context.pack(anchor="w", padx=18, pady=(12, 0))
        bar = tk.Frame(page, bg=BACKGROUND)
        bar.pack(fill="x", padx=18, pady=10)
        action(bar, "Informe PDF de esta lesión", self.export_pdf, True).pack(
            side="right"
        )
        filters = tk.Frame(page, bg=BACKGROUND)
        filters.pack(fill="x", padx=18, pady=(0, 8))
        self.history_from = tk.StringVar(master=self.window)
        self.history_to = tk.StringVar(master=self.window)
        for caption, variable in (("Desde (DD/MM/AAAA)", self.history_from), ("Hasta", self.history_to)):
            text(filters, caption, 9, SECONDARY).pack(side="left", padx=(0, 5))
            ttk.Entry(filters, textvariable=variable, width=12).pack(side="left", padx=(0, 10))
        self.history_type = ttk.Combobox(filters, state="readonly", width=17,
            values=("Todos los registros", "Fotografías", "Comparaciones"))
        self.history_type.current(0)
        self.history_type.pack(side="left", padx=4)
        self.history_state = ttk.Combobox(filters, state="readonly", width=18,
            values=("Todos los estados", "Pendiente", "Aceptada", "No concluyente", "Rechazada", "Comparable", "No evaluable", "Recalcular", "Solo visual"))
        self.history_state.current(0)
        self.history_state.pack(side="left", padx=4)
        action(filters, "Filtrar", self.apply_history_filters).pack(side="left", padx=4)
        photo_actions = tk.Frame(page, bg=BACKGROUND)
        photo_actions.pack(fill="x", padx=18)
        self.history_buttons = {}
        for key, title, command in [
            ("view", "Ver fotografía", self.open_history_photo),
            ("date", "Editar fecha", self.edit_history_date),
            ("delete", "Eliminar", self.delete_photo),
        ]:
            control = action(photo_actions, title, command)
            control.pack(side="left", padx=(0, 6))
            control.configure(state="disabled")
            self.history_buttons[key] = control
        text(
            page,
            "Fotografías · un clic selecciona; Ver fotografía abre el contenido",
            11,
            bold=True,
        ).pack(anchor="w", padx=18, pady=8)
        self.history = ttk.Treeview(
            page,
            columns=("t", "date", "classification"),
            show="headings",
            height=5,
            selectmode="browse",
            style="Evo.Treeview",
        )
        for key, title, width in [
            ("t", "Registro", 80),
            ("date", "Fecha de fotografía", 240),
            ("classification", "Clasificación guardada", 260),
        ]:
            self.history.heading(key, text=title)
            self.history.column(key, width=width)
        self.history.pack(fill="x", padx=18)
        self.history.bind("<<TreeviewSelect>>", self.preview_record)
        self.history.bind("<Double-1>", self.open_history_photo)
        self.history.bind("<Return>", self.open_history_photo)
        text(
            page, "Comparaciones · selecciona una y pulsa Ver resultado", 11, bold=True
        ).pack(anchor="w", padx=18, pady=(20, 8))
        controls = tk.Frame(page, bg=BACKGROUND)
        controls.pack(fill="x", padx=18, pady=5)
        self.view_comparison_button = action(
            controls, "Ver resultado", self.restore_comparison, True
        )
        self.view_comparison_button.pack(side="left")
        self.view_comparison_button.configure(state="disabled")
        self.remove_comparison_button = action(
            controls, "Eliminar comparación", self.delete_comparison
        )
        self.remove_comparison_button.pack(side="left", padx=6)
        self.remove_comparison_button.configure(state="disabled")
        self.comparisons = ttk.Treeview(
            page,
            columns=("dates", "index", "level"),
            show="headings",
            height=8,
            selectmode="browse",
            style="Evo.Treeview",
        )
        for key, title, width in [
            ("dates", "Anterior → posterior", 390),
            ("index", "Índice / 100", 100),
            ("level", "Estado", 180),
        ]:
            self.comparisons.heading(key, text=title)
            self.comparisons.column(key, width=width)
        self.comparisons.pack(fill="both", expand=True, padx=18, pady=(0, 20))
        self.comparisons.bind("<<TreeviewSelect>>", self.select_comparison)
        self.comparisons.bind("<Double-1>", self.restore_comparison)
        self.comparisons.bind("<Return>", self.restore_comparison)

    def build_people_page(self):
        page = self.pages[2]
        self.person_panel = tk.Frame(page, bg=BACKGROUND)
        self.person_panel.pack(fill="both", expand=True, padx=18, pady=10)
        intro = card(self.person_panel, "Empieza aquí · De una fotografía a un historial revisable")
        intro.pack(fill="x", pady=(0, 10))
        text(
            intro,
            "1  Abre una persona y su lesión.\n"
            "2  Añade fotografías con fecha y revisa sus contornos.\n"
            "3  Elige dos fotos: revisa los controles y las diferencias disponibles.\n"
            "4  Exporta un informe con fotografías, resultados y limitaciones.",
            10, SECONDARY, justify="left", wraplength=770,
        ).pack(anchor="w", padx=13, pady=(0, 10))
        if getattr(self.app, "demo", False):
            text(
                intro,
                "Caso DEMO-001: enero/febrero = repetición con giro; enero/marzo = "
                "aumento sintético; enero/abril = captura desenfocada. "
                "Los contornos y las fechas son de prueba.",
                10, BLUE, justify="left", wraplength=770,
            ).pack(anchor="w", padx=13, pady=(0, 10))
        bar = tk.Frame(self.person_panel, bg=BACKGROUND)
        bar.pack(fill="x", pady=(0, 10))
        action(bar, "+ Nueva persona", self.create_person, True).pack(side="right")
        text(bar, "Buscar por nombre o código", 10, SECONDARY).pack(side="left")
        self.person_search = tk.StringVar()
        ttk.Entry(bar, textvariable=self.person_search, width=30).pack(
            side="left", padx=10
        )
        self.person_search.trace_add("write", self.filter_people)
        text(
            self.person_panel,
            "Selecciona una persona y abre su ficha. También puedes usar doble clic o Enter.",
            11,
            INK,
        ).pack(anchor="w", pady=8)
        self.person_list = ttk.Treeview(
            self.person_panel,
            columns=("code", "name", "count", "notes"),
            show="headings",
            selectmode="browse",
            style="Evo.Treeview",
        )
        for key, title, width in [
            ("code", "Código", 100),
            ("name", "Nombre", 180),
            ("count", "Lesiones", 75),
            ("notes", "Observaciones", 240),
        ]:
            self.person_list.heading(key, text=title)
            self.person_list.column(key, width=width)
        self.person_list.pack(fill="both", expand=True, pady=10)
        self.person_list.bind("<<TreeviewSelect>>", self.select_person)
        self.person_list.bind("<Double-1>", lambda event: self.open_person())
        self.person_list.bind("<Return>", lambda event: self.open_person())
        action(
            self.person_panel, "Abrir ficha de la persona", self.open_person, True
        ).pack(anchor="e", pady=10)
        self.lesion_panel = tk.Frame(page, bg=BACKGROUND)
        bar = tk.Frame(self.lesion_panel, bg=BACKGROUND)
        bar.pack(fill="x", pady=(0, 10))
        action(bar, "← Personas", self.back_to_people).pack(side="left")
        action(bar, "Editar datos de la persona", self.edit_current_person).pack(
            side="right"
        )
        self.person_heading = text(
            self.lesion_panel, "Lesiones de la persona", 16, bold=True
        )
        self.person_heading.pack(anchor="w", pady=10)
        action(self.lesion_panel, "+ Nueva lesión", self.create_lesion, True).pack(
            anchor="w", pady=(0, 10)
        )
        self.people = ttk.Treeview(
            self.lesion_panel,
            columns=("person", "lesion", "site"),
            show="headings",
            selectmode="browse",
            style="Evo.Treeview",
        )
        for key, title in [
            ("person", "Código de persona"),
            ("lesion", "Lesión"),
            ("site", "Zona del cuerpo"),
        ]:
            self.people.heading(key, text=title)
        self.people.pack(fill="both", expand=True, pady=8)
        self.people.bind("<Double-1>", self.choose_person_lesion)
        self.people.bind("<Return>", self.choose_person_lesion)
        action(
            self.lesion_panel,
            "Abrir fotografías de la lesión",
            self.choose_person_lesion,
            True,
        ).pack(anchor="e", pady=12)

    def build_settings_page(self):
        shell = self.pages[3]
        scroll = ttk.Scrollbar(shell, orient="vertical")
        scroll.pack(side="right", fill="y")
        self.settings_canvas = tk.Canvas(
            shell, bg=BACKGROUND, highlightthickness=0, yscrollcommand=scroll.set
        )
        self.settings_canvas.pack(fill="both", expand=True)
        scroll.configure(command=self.settings_canvas.yview)
        page = tk.Frame(self.settings_canvas, bg=BACKGROUND)
        settings_item = self.settings_canvas.create_window(
            0, 0, window=page, anchor="nw", width=900
        )
        self.settings_canvas.bind(
            "<Configure>",
            lambda e: self.settings_canvas.itemconfigure(settings_item, width=e.width),
        )
        page.bind(
            "<Configure>",
            lambda e: self.settings_canvas.configure(
                scrollregion=self.settings_canvas.bbox("all")
            ),
        )
        box = card(page, "Cámara y modelo local")
        box.pack(fill="x", padx=18, pady=12)
        self.settings_text = text(
            box, "", 11, SECONDARY, justify="left", wraplength=760
        )
        self.settings_text.pack(anchor="w", padx=16, pady=12)
        text(box, "Cámara para tomar fotografías", 10).pack(anchor="w", padx=16)
        if hasattr(self.app, "camera_id"):
            tk.Spinbox(
                box, from_=0, to=9, textvariable=self.app.camera_id, width=5
            ).pack(anchor="w", padx=16, pady=10)

        backup_box = card(page, "Protección de datos y recuperación")
        backup_box.pack(fill="x", padx=18, pady=12)
        text(
            backup_box,
            "Copia portable de todos los registros y archivos, con verificación SHA-256.",
            10,
            SECONDARY,
        ).pack(anchor="w", padx=16, pady=8)
        controls = tk.Frame(backup_box, bg=WHITE)
        controls.pack(fill="x", padx=16, pady=12)
        action(controls, "Crear respaldo completo", self.create_backup, True).pack(
            side="left"
        )
        action(controls, "Restaurar respaldo", self.restore_full_backup).pack(
            side="left", padx=8
        )
        action(controls, "Abrir papelera", self.open_trash).pack(side="left")

        tools = card(page, "Herramientas adicionales")
        tools.pack(fill="x", padx=18, pady=12)
        for title, command in [
            ("Comparar imágenes distintas (experimental)", self.open_comparison_tools),
            ("Exportar datos CSV", self.export),
            ("Revisión técnica de la lesión", self.review_followup),
            ("Limpiar comparaciones de la lesión", self.clear_comparisons),
        ]:
            action(tools, title, command).pack(anchor="w", padx=16, pady=4)

    def refresh_settings(self):
        from longitudinal_analysis import VERSION
        from importlib.metadata import version, PackageNotFoundError
        versions = []
        for package in ("Pillow", "opencv-python", "tensorflow"):
            try:
                versions.append(package + " " + version(package))
            except PackageNotFoundError:
                pass
        camera = getattr(self.app, "cap", None)
        resolution = "Sin cámara activa; la resolución se muestra durante la captura."
        if camera is not None and camera.isOpened():
            import cv2
            resolution = f"Resolución actual: {int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))} × {int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))} px"
        self.settings_text.configure(
            text=f"Modelo: {'cargado' if self.app.model is not None else 'pendiente de carga'}\n"
            f"Filtros: {'disponibles' if self.app.domain_gate is not None else 'pendientes'}\n\n"
            f"Motor de comparación: {VERSION}\n" + " · ".join(versions) + "\n" + resolution +
            f"\n\nHistorial local:\n{self.store.root}\n\nLas fotos se guardan solo al confirmar un registro. "
            "El almacenamiento y los respaldos locales no están cifrados por la aplicación.\n"
            + ("Modo demostración: archivo sintético separado." if getattr(self.app, "demo", False) else "Modo de trabajo: registros locales del proyecto.")
        )

    def open_pair_inspector(self):
        from comparison_inspector import ComparisonInspector
        from longitudinal_insights import date_label
        pair = self.comparison_pair
        if not all(pair):
            self.status.set("Selecciona las dos fotografías antes de ampliarlas.")
            return
        try:
            records = [self.store.record(identifier) for identifier in pair]
            images = [self.store.load_images(record)[0] for record in records]
            captions = [record["label"] + " · " + date_label(record["captured_at"]) for record in records]
            self.pair_inspector = ComparisonInspector(self.window, *images, *captions,
                note="Fotografías originales. El zoom comparte posición relativa; no verifica alineación, escala física ni identidad.")
        except (OSError, ValueError) as exc:
            self.status.set("No se pudieron abrir las fotografías: " + str(exc))

    def choose_person_lesion(self, event=None):
        if self.running or self.app.busy:
            self.status.set(
                "Espera a que termine el análisis antes de abrir otra lesión."
            )
            return
        selected = self.people.selection()
        if selected:
            self.lesion_id = selected[0]
            self.selected_photo_ids = []
            self.comparison_mode.current(0)
            self.refresh_lesions()
            self.navigate(0)
            self.status.set(
                "Lesión abierta. Carga una fotografía o selecciona las que quieras consultar."
            )
        else:
            self.status.set(
                "Selecciona una lesión de la lista para abrir sus fotografías."
            )

    def filter_patient(self, event=None):
        person = next(
            (r for r in self.person_rows if r["code"] == self.patient_choice.get()),
            None,
        )
        if (
            person
            and self.person_list.exists(person["id"])
            and self.person_list.selection() != (person["id"],)
        ):
            self.person_list.selection_set(person["id"])
        self.visible_lesions = [
            r for r in self.lesions if r["patient"] == self.patient_choice.get()
        ]
        self.lesion_choice["values"] = [
            f"{r['name']} · {r['site']}" for r in self.visible_lesions
        ]
        self.people.delete(*self.people.get_children())
        for row in self.visible_lesions:
            self.people.insert(
                "",
                "end",
                iid=row["id"],
                values=(row["patient"], row["name"], row["site"]),
            )
        if hasattr(self, "person_heading"):
            self.person_heading.configure(
                text="Lesiones de "
                + ((person["name"] or person["code"]) if person else "la persona")
            )
        if self.visible_lesions:
            index = next(
                (
                    i
                    for i, r in enumerate(self.visible_lesions)
                    if r["id"] == self.lesion_id
                ),
                0,
            )
            self.lesion_choice.current(index)
            self.select_lesion()
        else:
            self.lesion_id = None
            self.lesion_choice.set("")
            self.refresh_history()
            self.clear_output()
        self.update_context()

    def refresh_thumbnails(self):
        valid = (
            {r["id"] for r in self.comparison_records()}
            if self.workspace_mode == "compare"
            else {r["id"] for r in self.records}
        )
        self.selected_photo_ids = [i for i in self.selected_photo_ids if i in valid]
        chosen = self.selected_photo_ids
        count = len(chosen)
        self.visit_actions.pack_forget()
        self.selection_actions.pack_forget()
        if count == 1 and self.workspace_mode == "photos":
            self.visit_actions.pack(
                fill="x", padx=12, pady=(0, 8), before=self.strip_canvas
            )
        self.flow_hint.configure(
            text=(
                "Todavía no hay fotografías. Carga la primera para comenzar."
                if not self.records
                else (
                    "Selecciona una fotografía para verla."
                    if count == 0 and self.workspace_mode == "photos"
                    else (
                        "Selecciona las dos fotografías que quieres comparar."
                        if count == 0
                        else (
                            "Fotografía seleccionada. Puedes analizarla, editar su fecha o eliminarla."
                            if self.workspace_mode == "photos"
                            else (
                                "Selecciona una segunda fotografía para comparar."
                                if count == 1
                                else "2 fotografías seleccionadas. La comparación se muestra automáticamente. Puedes elegir otra foto para continuar."
                            )
                        )
                    )
                )
            )
        )
        available = not (self.running or self.app.busy)
        for control in self.photo_buttons.values():
            control.configure(
                state="normal" if count == 1 and available else "disabled"
            )
        visits = sorted(self.records, key=lambda row: (row["captured_at"], row["id"]))
        has_previous = (
            self.workspace_mode == "photos"
            and count == 1
            and next((i for i, row in enumerate(visits) if row["id"] == chosen[0]), 0)
            > 0
        )
        self.compare_previous_button.configure(
            state="normal" if available and has_previous else "disabled"
        )
        self.compare_button.configure(
            state="normal" if count == 2 and available else "disabled"
        )
        for widget in self.strip_frame.winfo_children():
            widget.destroy()
        self.thumbnail_photos = []
        from datetime import datetime

        for record in self.records:
            selected = record["id"] in chosen
            frame = tk.Frame(
                self.strip_frame,
                bg=ACCENT_SOFT if selected else WHITE,
                highlightbackground=BLUE if selected else LINE,
                highlightthickness=2 if selected else 1,
            )
            frame.pack(side="left", padx=(0, 12), pady=2)
            try:
                image, _ = self.store.load_images(record)
                photo = ImageTk.PhotoImage(
                    ImageOps.contain(image, (120, 90)), master=self.window
                )
                self.thumbnail_photos.append(photo)
                title = (
                    ("✓ Seleccionada" if selected else "Seleccionar")
                    + "\n"
                    + datetime.fromisoformat(record["captured_at"]).strftime("%d/%m/%Y")
                    + " · "
                    + record["label"]
                )
                tk.Button(
                    frame,
                    image=photo,
                    text=title,
                    compound="top",
                    command=lambda identifier=record["id"]: self.select_photo(
                        identifier
                    ),
                    relief="flat",
                    bg=ACCENT_SOFT if selected else WHITE,
                    fg=INK,
                    cursor="hand2",
                    font=("Segoe UI", 10),
                    padx=8,
                    pady=8,
                ).pack()
            except (OSError, ValueError):
                text(frame, "Foto no disponible", 10, SECONDARY).pack(padx=8, pady=8)
        self.sync_photo_analysis()
        self.refresh_workspace_layout()

    def use_photo_as(self, side, identifier):
        index = next(
            (i for i, r in enumerate(self.pair_records) if r["id"] == identifier), None
        )
        if index is not None:
            (self.previous if side == 0 else self.current).current(index)
            self.on_pair_selected()

    def update_pair_summary(self):
        from datetime import datetime

        indices = [self.previous.current(), self.current.current()]
        rows = getattr(self, "pair_records", [])
        if any(i < 0 or i >= len(rows) for i in indices):
            self.pair_summary.configure(
                text="Seleccione una fotografía para A y otra para B. Fechas mostradas: día/mes/año."
            )
            return
        a, b = (rows[i] for i in indices)
        if a["id"] == b["id"]:
            self.pair_summary.configure(
                text="A y B son la misma fotografía. Seleccione dos fotografías diferentes."
            )
            return
        days = (
            datetime.fromisoformat(b["captured_at"])
            - datetime.fromisoformat(a["captured_at"])
        ).total_seconds() / 86400
        detail = f"Intervalo entre capturas: {abs(days):.1f} días."
        if self.comparison_mode_key() == "visual":
            detail += " Fechas informativas: se comparan rasgos visuales, no evolución temporal."
        elif days < 0:
            detail += " El seguimiento ordenará las imágenes de la fecha anterior a la posterior."
        else:
            detail += " Si la alineación falla, se mostrarán diferencias visuales identificadas como tales."
        result = self.current_result or {}
        if (
            self.comparison_mode_key() == "longitudinal"
            and result.get("requested_mode") == "longitudinal"
            and result.get("mode") == "visual"
            and result.get("previous_id") == a["id"]
            and result.get("current_id") == b["id"]
        ):
            detail += " Esta comparación no se alineó; muestra diferencias visuales, no evolución temporal. Puedes elegir otra visita de esta misma lesión."
        self.pair_summary.configure(text=detail)

    def edit_pair_date(self, side):
        index = (self.previous if side == 0 else self.current).current()
        if 0 <= index < len(self.pair_records):
            self.edit_visit_date(self.pair_records[index]["id"])
        else:
            self.status.set("Seleccione primero la fotografía que desea editar.")

    def pick_thumbnail(self, index):
        identifier = self.records[index]["id"]
        index = next(
            i for i, r in enumerate(self.pair_records) if r["id"] == identifier
        )
        self.current.current(index)
        if self.previous.current() >= index:
            self.previous.current(max(0, index - 1))
        self.on_pair_selected()

    def on_pair_selected(self, event=None):
        self.clear_output()
        self.update_pair_summary()
        images = []
        titles = []
        try:
            for widget in (self.previous, self.current):
                index = widget.current()
                if index >= 0:
                    row = self.pair_records[index]
                    image, _ = self.store.load_images(row)
                    images.append(image)
                    from datetime import datetime

                    titles.append(
                        ("Imagen A" if widget is self.previous else "Imagen B")
                        + " · "
                        + datetime.fromisoformat(row["captured_at"]).strftime(
                            "%d/%m/%Y · %H:%M:%S"
                        )
                    )
            self.display_images(images, titles)
        except (OSError, ValueError) as exc:
            self.status.set(str(exc))

    def reset_dashboard_result(self):
        if hasattr(self, "confidence_label"):
            self.confidence_label.configure(text="Controles técnicos: pendientes", fg=SECONDARY)
        self.current_result = None
        self.readiness_title.configure(text="PENDIENTE DE COMPARACIÓN", fg=BLUE)
        self.readiness_detail.configure(
            text="Elige dos fotografías de la misma lesión."
        )
        self.explanation_button.configure(state="disabled")
        self.compare_card.grid_remove()
        self.comparison_note.configure(text="")
        self.overlay_mode.set(False)
        self.overlay_check.configure(state="disabled")
        self.blend.configure(state="disabled")
        for panel in self.result_cards:
            panel.grid_remove()
        self.lower_results.pack_forget()
        self.map_card.grid_remove()
        for value in self.change_values.values():
            value.configure(text="—")
        self.index_value.configure(text="— / 100")
        self.index_level.configure(text="Pendiente de comparación")
        self.class_label.configure(text="Sin análisis actual", fg=SECONDARY)
        self.classification_context.configure(text="Analiza una fotografía para consultar su resultado.")
        self.malignant_value.configure(text="— %")
        self.benign_value.configure(text="— %")
        self.malignant_bar["value"] = 0
        self.benign_bar["value"] = 0

    def update_classification_card(self, classification):
        from explainability import explanation_caption
        details = []
        if classification.get("state") == "accepted":
            score_value = classification.get("score")
            if isinstance(score_value, (int, float)):
                details.append(f"Puntuación experimental para la clase maligna: {score_value * 100:.1f} %. Es la salida del modelo para esta imagen; no expresa la precisión del resultado ni la probabilidad de tener cáncer.")
            details.append("Este resultado corresponde únicamente a esta fotografía; no explica por sí solo el cambio entre A y B.")
            if classification.get("explanation"):
                details.append(explanation_caption(classification.get("explanation_diagnostics")))
        else:
            details.append(classification.get("reason") or "Revisa la calidad de la fotografía y vuelve a analizarla si corresponde.")
        self.classification_context.configure(text="\n\n".join(str(item) for item in details))
        score = classification.get("score")
        state = classification.get("state")
        label = classification.get("label")
        if state == "accepted":
            malignant = label == "malignant"
            self.class_label.configure(
                text=(
                    "Patrón maligno (experimental)"
                    if malignant
                    else "Patrón benigno (experimental)"
                ),
                fg=RED if malignant else "#287a61",
            )
        else:
            titles = dict(
                uncertain="Resultado no concluyente",
                rejected="Imagen rechazada",
                quality_failed="Calidad insuficiente",
                unavailable="Modelo no disponible",
            )
            self.class_label.configure(
                text=titles.get(state, "Sin clasificación disponible"), fg=SECONDARY
            )
        if score is not None and state == "accepted":
            self.malignant_value.configure(text=f"{score*100:.1f} %")
            self.benign_value.configure(text=f"{(1-score)*100:.1f} %")
            self.malignant_bar["value"] = score * 100
            self.benign_bar["value"] = (1 - score) * 100
        else:
            self.malignant_value.configure(text="— %")
            self.benign_value.configure(text="— %")
            self.malignant_bar["value"] = 0
            self.benign_bar["value"] = 0

    def comparison_mode_key(self):
        return "visual" if self.comparison_mode.current() == 1 else "longitudinal"

    def change_comparison_mode(self, event=None):
        self.clear_output()
        self.refresh_pair_choices()
        self.update_mode_labels(self.comparison_mode_key())
        self.update_pair_summary()
        self.draw_timeline()

    def update_mode_labels(self, mode):
        visual = mode == "visual"
        workflow_visual = self.comparison_mode_key() == "visual"
        self.compare_heading.configure(
            text=(
                "Fotografías comparadas · solo diferencias visuales"
                if workflow_visual
                else "Fotografías de la misma lesión"
            )
        )
        self.changes_heading.configure(
            text=(
                "Diferencias visuales entre imágenes"
                if visual
                else "Cambios detectados"
            )
        )
        self.classification_heading.configure(
            text=(
                "Clasificación de la fotografía B"
                if visual
                else "Clasificación de la fotografía posterior"
            )
        )
        self.index_heading.configure(
            text=(
                "Índice de diferencia visual"
                if visual
                else "Índice descriptivo de cambio"
            )
        )
        self.chart_heading.configure(
            text=(
                "Diferencias por característica"
                if workflow_visual
                else "Comparaciones en el tiempo"
            )
        )
        self.chart_note.configure(
            text=(
                "Diferencias visuales; no representan evolución."
                if workflow_visual
                else "La tabla muestra todas las comparaciones. El gráfico opcional utiliza únicamente las de ajuste aceptado."
            )
        )
        self.map_note.configure(
            text=(
                "Siluetas normalizadas: gris=zona común, cian=solo A, naranja=solo B. No es un mapa de crecimiento."
                if visual
                else "Cian: anterior · Naranja: actual. Color cálido: mayor diferencia visual."
            )
        )

    def update_dashboard_result(self, result):
        self.current_result = result
        from longitudinal_insights import comparison_conclusion
        self.conclusion_text.configure(text=comparison_conclusion(result))
        from professional_tools import comparison_confidence
        level, reason, color = comparison_confidence(result)
        self.confidence_label.configure(text=f"Controles técnicos: {reason}", fg=color)
        from longitudinal_insights import comparison_readiness

        title, guidance = comparison_readiness(result)
        self.readiness_title.configure(
            text=title,
            fg=(
                "#287a61"
                if title == "COMPARABLE"
                else RED if title == "NO EVALUABLE" else BLUE
            ),
        )
        self.readiness_detail.configure(text=guidance)
        self._map_preview_cache = None
        self.update_mode_labels(result.get("mode", "longitudinal"))
        self.update_pair_summary()
        from datetime import datetime

        try:
            self.result_pair_label.configure(
                text=datetime.fromisoformat(result["previous_date"]).strftime(
                    "%d/%m/%Y %H:%M"
                )
                + " → "
                + datetime.fromisoformat(result["current_date"]).strftime(
                    "%d/%m/%Y %H:%M"
                )
            )
        except (KeyError, ValueError):
            self.result_pair_label.configure(text="Fotografías seleccionadas")
        self.result_cards[1].grid(column=1, columnspan=1)
        for panel in self.result_cards:
            panel.grid()
        self.map_card.grid()
        self.update_classification_card(result["current_classification"])
        self.explanation_button.configure(
            state=(
                "normal"
                if result["current_classification"].get("explanation")
                else "disabled"
            )
        )
        for value in self.change_values.values():
            value.configure(text="—")
        if result.get("mode") == "visual" and result.get("visual_available"):
            visual = result["visual_differences"]
            formats = dict(
                area=f"{visual['area_coverage_pp']:+.2f} pp de cobertura",
                shape=f"{visual['shape']:.3f}",
                asymmetry=f"{visual['asymmetry']:+.3f}",
                border=f"{visual['border']:+.3f}",
                color=f"{visual['color']:.2f} ΔE",
                texture=f"{visual['texture']:.3f}",
                deep="No incluido",
            )
            for key, value in formats.items():
                self.change_values[key].configure(text=value)
            self.comparison_note.configure(
                text=(
                    "No se confirmó una medición temporal; se muestran diferencias visuales. "
                    if result.get("fallback_reason")
                    else ""
                )
                + "Comparación visual de las regiones marcadas. La cobertura se informa por separado; "
                "no entra en el índice. El encuadre y la iluminación influyen. No demuestra evolución ni malignidad."
            )
            if result.get("requested_mode") == "longitudinal" or result.get("fallback_reason"):
                self.index_heading.configure(text="Medición longitudinal")
                self.index_value.configure(text="No disponible")
                self.index_level.configure(text="No se pudo alinear el par. Verifica que sea la misma lesión y revisa fechas, contornos y encuadre.")
            else:
                self.index_value.configure(text=f"{result['visual_index']:.1f} / 100")
                self.index_level.configure(text=result["visual_level"] + " · diferencia visual heurística")
            self.overlay_mode.set(False)
            self.overlay_check.configure(state="disabled")
            self.blend.configure(state="disabled")
        elif result["comparable"]:
            self.overlay_check.configure(state="normal")
            self.blend.configure(state="normal")
            from longitudinal_insights import comparison_narrative
            self.comparison_note.configure(text=comparison_narrative(result))
            changes = result["changes"]
            formats = dict(
                area=f"{changes['area']:+.2f} %",
                shape=f"{changes['shape']:.3f}",
                asymmetry=f"{changes['asymmetry']:+.3f}",
                border=f"{changes['border']:+.3f}",
                color=f"{changes['color']:.2f} ΔE",
                texture=f"{changes['texture']:.3f}",
            )
            deep = result.get("deep_cosine_distance")
            formats["deep"] = "—" if deep is None else f"{deep:.4f}"
            for key, value in formats.items():
                self.change_values[key].configure(text=value)
            self.index_value.configure(text=f"{result['change_index']:.1f} / 100")
            self.index_level.configure(
                text=result["change_level"] + " · escala heurística"
            )
        else:
            for value in self.change_values.values():
                value.configure(text="No medido")
            reason = next(
                iter(result.get("warnings", [])),
                "Las fotografías no cumplen los controles de comparabilidad.",
            )
            self.comparison_note.configure(
                text="No se pudieron medir los cambios. Esto no significa que las imágenes sean iguales.\nMotivo: "
                + reason
            )
            visual = result.get("visual_differences")
            if visual:
                formats = dict(
                    area=f"{visual['area_coverage_pp']:+.2f} pp de cobertura",
                    shape=f"{visual['shape']:.3f}",
                    asymmetry=f"{visual['asymmetry']:+.3f}",
                    border=f"{visual['border']:+.3f}",
                    color=f"{visual['color']:.2f} ΔE",
                    texture=f"{visual['texture']:.3f}",
                )
                for key, value in formats.items():
                    self.change_values[key].configure(text=value)
                self.comparison_note.configure(
                    text="Diferencias visuales entre las regiones marcadas, sin alineación. "
                    "Área: diferencia de cobertura de la foto en puntos porcentuales (pp), no crecimiento. "
                    "El encuadre y la iluminación influyen.\nMotivo de la falta de alineación: "
                    + reason
                )
            self.index_value.configure(
                text="Sin alineación" if visual else "No evaluable"
            )
            self.index_level.configure(
                text=(
                    "Evolución no cuantificable; diferencias visuales disponibles."
                    if visual
                    else "No se asigna un índice de cambio."
                )
            )
            self.overlay_mode.set(False)
            self.overlay_check.configure(state="disabled")
            self.blend.configure(state="disabled")
        self.draw_timeline()
        self.render_images()

    def reveal_comparison_result(self):
        self.refresh_workspace_layout()
        if self.workspace_mode == "followup":
            return
        self.window.update_idletasks()
        offset = self.details_card.winfo_rooty() - self.dashboard.winfo_rooty()
        self.dashboard_canvas.yview_moveto(
            max(0, (offset - 12) / max(self.dashboard.winfo_height(), 1))
        )

    def difference_map_image(self):
        if len(self.image_sources) < 3:
            return None
        source = self.image_sources[2]
        result = self.current_result or {}
        if not self.map_zoom.get() or not result.get("comparable"):
            return source
        key = (id(source), id(result))
        cached = getattr(self, "_map_preview_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        preview = source
        if (
            result.get("previous_id")
            and result.get("current_id")
            and result.get("registration", {}).get("matrix") is not None
        ):
            from longitudinal_analysis import normalized
            from longitudinal_views import aligned_detail

            previous = self.store.record(result["previous_id"])
            current = self.store.record(result["current_id"])
            _, mask0 = self.store.load_images(previous)
            photo1, mask1 = self.store.load_images(current)
            _, m1 = normalized(photo1, mask1)
            preview = aligned_detail(
                source,
                mask0,
                Image.fromarray(m1.astype("uint8") * 255),
                result["registration"]["matrix"],
            )
        self._map_preview_cache = (key, preview)
        return preview

    def open_difference_map(self):
        from tkinter import messagebox
        import tkinter as tk

        result = self.current_result or {}
        if (
            not (result.get("comparable") or result.get("visual_available"))
            or len(self.image_sources) < 3
        ):
            messagebox.showinfo(
                "Mapa de diferencias",
                "Primero selecciona una comparación con un mapa disponible.",
                parent=self.window,
            )
            return
        dialog = tk.Toplevel(self.window)
        dialog.title("DermaVision-X · Mapa de diferencias")
        dialog.configure(bg=BACKGROUND)
        image = self.difference_map_image()
        photo = ImageTk.PhotoImage(
            ImageOps.contain(
                image,
                (
                    min(950, self.window.winfo_screenwidth() - 100),
                    min(650, self.window.winfo_screenheight() - 200),
                ),
            )
        )
        picture = tk.Label(dialog, image=photo, bg=WHITE)
        picture.image = photo
        picture.pack(padx=15, pady=15)
        text(
            dialog,
            self.map_note.cget("text"),
            10,
            SECONDARY,
            wraplength=800,
            justify="left",
        ).pack(padx=15, pady=(0, 15))

    def render_dashboard_images(self):
        if self.closed:
            return
        if getattr(self, "_rendering_images", False):
            return
        self._rendering_images = True
        try:
            if not hasattr(self, "picture_widgets"):
                return
            self.photos = []
            sources = list(self.image_sources)
            result = self.current_result or {}
            if (
                self.overlay_mode.get()
                and result.get("comparable")
                and len(sources) >= 2
            ):
                from professional_tools import wipe_images
                operation = wipe_images if self.wipe_mode.get() else Image.blend
                sources[1] = operation(
                    sources[0].convert("RGB"),
                    sources[1].convert("RGB").resize(sources[0].size),
                    float(self.blend.get()),
                )
            for i, (caption, picture) in enumerate(self.picture_widgets):
                picture.configure(image="")
                width = picture.master.winfo_width() - 24
                if width <= 20:
                    continue  # Resize callbacks redraw once the real layout is available.
                if i == 2:
                    if not (result.get("comparable") or result.get("visual_available")):
                        caption.configure(
                            text=(
                                "Sin comparación"
                                if not result
                                else "Mapa no disponible: consulta el motivo de la comparación."
                            ),
                            wraplength=width,
                        )
                        continue
                    if len(sources) > 2:
                        sources[2] = self.difference_map_image()
                    title = (
                        "Mapa de siluetas independientes · sin alineación temporal"
                        if result.get("mode") == "visual"
                        else "Diferencias entre las fotografías alineadas"
                    )
                    height = max(100, picture.master.winfo_height() - 45)
                else:
                    title = (
                        "Superposición"
                        if i == 1
                        and self.overlay_mode.get()
                        and result.get("comparable")
                        else (
                            self.image_titles[i] if i < len(self.image_titles) else ""
                        )
                    )
                    if self.workspace_mode == "compare" and not (
                        i == 1 and self.overlay_mode.get() and result.get("comparable")
                    ):
                        from longitudinal_insights import date_label

                        identifier = self.comparison_pair[i]
                        record = next(
                            (
                                r
                                for r in self.comparison_records()
                                if r["id"] == identifier
                            ),
                            None,
                        )
                        same_date = (
                            all(self.comparison_pair)
                            and len(
                                {
                                    r["captured_at"]
                                    for r in self.records
                                    if r["id"] in self.comparison_pair
                                }
                            )
                            == 1
                        )
                        title = (
                            ("Foto A" if i == 0 else "Foto B")
                            if same_date
                            else (
                                "Foto A · anterior" if i == 0 else "Foto B · posterior"
                            )
                        ) + (
                            " · " + date_label(record["captured_at"])
                            if record
                            else " · sin elegir"
                        )
                        if i == 1 and result:
                            title += (
                                " · alineada"
                                if result.get("comparable")
                                else " · sin alineación"
                            )
                    height = 250
                caption.configure(text=title, wraplength=width)
                if i < len(sources) and sources[i] is not None:
                    photo = ImageTk.PhotoImage(
                        ImageOps.contain(sources[i], (width, height)),
                        master=self.window,
                    )
                    self.photos.append(photo)
                    picture.configure(image=photo)
        finally:
            self._rendering_images = False

    def draw_dashboard_timeline(self):
        self.draw_comparison_graph()
        if not self.chart_toggle.get():
            self.chart_note.configure(
                text="Cada fila compara dos fotografías. El índice resume diferencias de imagen; no mide riesgo ni gravedad. "
                "«Solo visual» indica que no se logró ajustar las fotos para evaluar cambios longitudinales. "
                "«Recalcular fecha» indica que alguna fecha se editó después del análisis."
            )

    def draw_comparison_graph(self):
        if not hasattr(self, "chart"):
            return
        self.refresh_comparison_table()
        c = self.chart
        c.delete("all")
        w = max(
            (
                c.winfo_width()
                if self.chart_toggle.get()
                else self.timeline_table.winfo_width()
            ),
            180,
        )
        if self.comparison_mode_key() == "visual":
            result = self.current_result or {}
            components = result.get("visual_components", {})
            if not components:
                c.create_text(
                    w / 2,
                    85,
                    text="Seleccione dos fotografías y compare en modo visual.",
                    width=max(100, w - 20),
                    fill=SECONDARY,
                )
                return
            names = dict(
                shape="Forma",
                asymmetry="Asimetría",
                border="Borde",
                color="Color",
                texture="Textura",
            )
            for i, (key, value) in enumerate(components.items()):
                y = 18 + i * 32
                c.create_text(
                    6,
                    y,
                    anchor="w",
                    text=names[key],
                    fill=SECONDARY,
                    font=("Segoe UI", 8),
                )
                left = 78
                right = max(left + 10, w - 38)
                c.create_rectangle(left, y - 6, right, y + 6, fill=LINE, outline="")
                c.create_rectangle(
                    left,
                    y - 6,
                    left + (right - left) * value,
                    y + 6,
                    fill=BLUE,
                    outline="",
                )
                c.create_text(
                    w - 3,
                    y,
                    anchor="e",
                    text=f"{value*100:.0f}",
                    fill=INK,
                    font=("Segoe UI", 8),
                )
            return
        from longitudinal_views import comparison_summary

        summary = comparison_summary(self.saved_comparisons, self.records)
        points = summary["points"]
        omitted = summary["visual"] + summary["stale"] + summary["invalid"]
        exclusions = f"Fuera del gráfico: {summary['visual']} visual(es), {summary['stale']} pendiente(s) de recalcular, {summary['invalid']} no evaluable(s)."
        self.chart_note.configure(
            wraplength=max(140, w - 25),
            text=exclusions
            + " El índice describe diferencias; no mide riesgo ni gravedad.",
        )
        if not points:
            self.chart_heading.configure(text="Comparaciones en el tiempo")
            message = (
                f"{len(self.saved_comparisons)} comparación(es) guardada(s)\nNinguna evaluable: no hay puntos para graficar."
                if self.saved_comparisons
                else "Aún no hay comparaciones guardadas."
            )
            c.create_text(
                w / 2,
                80,
                text=message,
                fill=SECONDARY,
                width=max(130, w - 30),
                justify="center",
            )
            return
        if len(points) == 1:
            self.chart_heading.configure(text="Resultado de una comparación")
            point = points[0]
            value = point["value"]
            c.create_text(
                w / 2,
                25,
                text=f"{value:.1f} / 100",
                fill=BLUE,
                font=("Segoe UI", 21, "bold"),
            )
            c.create_rectangle(25, 58, w - 25, 75, fill=LINE, outline="")
            c.create_rectangle(
                25, 58, 25 + (w - 50) * value / 100, 75, fill=BLUE, outline=""
            )
            c.create_text(25, 89, text="0", anchor="w", fill=SECONDARY)
            c.create_text(w - 25, 89, text="100", anchor="e", fill=SECONDARY)
            c.create_text(
                w / 2, 117, text=point["pair"], fill=INK, font=("Segoe UI", 11, "bold")
            )
            c.create_text(
                w / 2,
                158,
                text=point["previous_date"].strftime("%d/%m/%Y %H:%M:%S")
                + "\n→ "
                + point["date"].strftime("%d/%m/%Y %H:%M:%S"),
                fill=SECONDARY,
                width=max(120, w - 25),
            )
            c.create_text(
                w / 2,
                202,
                text="Una comparación permite medir diferencias, no una tendencia.",
                fill=SECONDARY,
                width=max(120, w - 25),
                font=("Segoe UI", 9),
            )
            return
        self.chart_heading.configure(
            text=(
                "Cambios respecto a la misma referencia"
                if summary["common_reference"]
                else "Comparaciones con referencias distintas"
            )
        )
        left, right, top, bottom = 40, w - 24, 30, 171
        for value in (0, 50, 100):
            y = bottom - (bottom - top) * value / 100
            c.create_line(left, y, right, y, fill=LINE)
            c.create_text(17, y, text=str(value), fill=SECONDARY, font=("Segoe UI", 8))
        earliest, latest = points[0]["date"], points[-1]["date"]
        span = (latest - earliest).total_seconds()
        positions = []
        for point in points:
            x = left + (right - left) * (
                (point["date"] - earliest).total_seconds() / span if span else 0.5
            )
            y = bottom - (bottom - top) * point["value"] / 100
            positions.append((x, y))
        if summary["common_reference"]:
            c.create_line(*[v for xy in positions for v in xy], fill=BLUE, width=2)
        for i, (point, (x, y)) in enumerate(zip(points, positions)):
            dot = c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=BLUE, outline="")
            c.tag_bind(
                dot,
                "<Enter>",
                lambda event, p=point: self.status.set(
                    f"{p['pair']}: índice {p['value']:.1f}/100 · "
                    + p["previous_date"].strftime("%d/%m/%Y %H:%M:%S")
                    + " → "
                    + p["date"].strftime("%d/%m/%Y %H:%M:%S")
                ),
            )
            if len(points) <= 4:
                c.create_text(
                    x,
                    y - 12,
                    text=f"{point['value']:.1f}",
                    fill=INK,
                    font=("Segoe UI", 8),
                )
            if i in (0, len(points) - 1):
                c.create_text(
                    x,
                    196,
                    text=point["date"].strftime("%d/%m/%y\n%H:%M:%S"),
                    anchor="w" if i == 0 else "e",
                    fill=SECONDARY,
                    font=("Segoe UI", 8),
                )
        self.chart_note.configure(
            text=(
                (
                    "Los puntos comparten una fotografía de referencia. "
                    if summary["common_reference"]
                    else "Cada punto compara un par distinto; no se unen como una tendencia. "
                )
                + exclusions
                + " Índice descriptivo de 0 a 100; no mide riesgo ni gravedad."
            )
        )
