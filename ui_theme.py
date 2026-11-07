"""Paleta compartida: superficies neutras y acentos índigo."""

BACKGROUND = "#f5f6fa"
SURFACE = "#ffffff"
INK = "#202536"
MUTED = "#6b7285"
BORDER = "#e5e7ef"
ACCENT = "#635bdb"
ACCENT_SOFT = "#eeecfc"
SIDEBAR = "#232637"
SIDEBAR_ACTIVE = "#3c375f"
SUCCESS = "#287a61"
WARNING = "#a66b20"
DANGER = "#c74764"


def configure_ttk(master):
    from tkinter import ttk

    style = ttk.Style(master)
    style.theme_use("clam")
    style.configure(
        "TButton",
        padding=(14, 9),
        font=("Segoe UI", 10),
        background=SURFACE,
        foreground=INK,
        borderwidth=0,
    )
    style.map("TButton", background=[("active", ACCENT_SOFT)])
    style.configure(
        "TCombobox",
        padding=7,
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=INK,
        arrowsize=15,
    )
    style.configure(
        "TSpinbox",
        padding=6,
        fieldbackground=SURFACE,
        background=SURFACE,
        foreground=INK,
    )
    style.configure(
        "Evo.Treeview",
        rowheight=34,
        font=("Segoe UI", 10),
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=INK,
        borderwidth=0,
    )
    style.configure(
        "Evo.Treeview.Heading",
        font=("Segoe UI", 10, "bold"),
        background="#f0f1f7",
        foreground=MUTED,
        relief="flat",
        padding=(8, 10),
    )
    style.map(
        "Evo.Treeview",
        background=[("selected", ACCENT_SOFT)],
        foreground=[("selected", INK)],
    )
    style.configure(
        "Evo.Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor="#edeef4",
        borderwidth=0,
    )
    return style
