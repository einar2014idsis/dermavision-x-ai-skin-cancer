"""Synchronized visual inspection of two photos; no geometric registration is applied."""

from dataclasses import dataclass
import math
import tkinter as tk

from PIL import Image, ImageTk

from ui_theme import BACKGROUND, SURFACE, INK, MUTED, ACCENT


def viewport_geometry(image_size, canvas_size, zoom=1.0, center=(0.5, 0.5)):
    """Return image x, y, width, height, preserving aspect and avoiding empty panning."""
    iw, ih = image_size
    cw, ch = canvas_size
    if min(iw, ih, cw, ch) <= 0:
        raise ValueError("Image and viewport dimensions must be positive.")
    scale = min(cw / iw, ch / ih) * max(1.0, min(8.0, zoom))
    width, height = iw * scale, ih * scale

    def position(extent, available, requested):
        if extent <= available:
            return (available - extent) / 2
        half = available / (2 * extent)
        position = max(half, min(1 - half, requested))
        return available / 2 - position * extent

    return position(width, cw, center[0]), position(height, ch, center[1]), width, height


@dataclass
class SharedViewport:
    zoom: float = 1.0
    center: tuple = (0.5, 0.5)

    def reset(self):
        self.zoom, self.center = 1.0, (0.5, 0.5)

    def pan(self, delta, image_size, canvas_size):
        x, y, width, height = viewport_geometry(image_size, canvas_size, self.zoom, self.center)
        cw, ch = canvas_size
        # Derive the effective center so letterboxing does not accumulate invisible pan.
        center = ((cw / 2 - x) / width, (ch / 2 - y) / height)
        self.center = tuple(0.5 if extent <= available else max(0.0, min(1.0, c - d / extent))
                            for c, d, extent, available in zip(center, delta, (width, height), (cw, ch)))

    def zoom_at(self, factor, image_size, canvas_size, point=None):
        old = self.zoom
        self.zoom = max(1.0, min(8.0, old * factor))
        if self.zoom == 1.0:
            self.center = (0.5, 0.5)
            return
        if point is None:
            return
        x, y, width, height = viewport_geometry(image_size, canvas_size, old, self.center)
        cw, ch = canvas_size
        anchor = ((point[0] - x) / width, (point[1] - y) / height)
        ratio = self.zoom / old
        self.center = tuple(max(0.0, min(1.0, a - (p - available / 2) / (extent * ratio)))
                            for a, p, available, extent in zip(anchor, point, (cw, ch), (width, height)))


class ComparisonInspector:
    def __init__(self, parent, previous_image, current_image, previous_caption,
                 current_caption, note=""):
        self.images = [previous_image.convert("RGB").copy(), current_image.convert("RGB").copy()]
        self.viewport = SharedViewport()
        self.photos = [None, None]
        self.drag_position = None
        self.render_job = None
        self.window = tk.Toplevel(parent)
        self.window.title("Inspección de fotografías · Zoom sincronizado")
        self.window.geometry("1120x720")
        self.window.minsize(760, 520)
        self.window.configure(bg=BACKGROUND)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        tk.Label(self.window, text="Inspeccionar las dos fotografías", bg=BACKGROUND,
                 fg=INK, font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=20, pady=(15, 5))
        tk.Label(self.window,
                 text="Zoom y posición relativa sincronizados. Esta vista no alinea las fotos ni verifica que sean la misma lesión.",
                 bg=BACKGROUND, fg=MUTED, font=("Segoe UI", 10), wraplength=1040,
                 justify="left").pack(anchor="w", padx=20, pady=(0, 8))
        if note:
            tk.Label(self.window, text=note, bg=BACKGROUND, fg=INK,
                     font=("Segoe UI", 10), wraplength=1040, justify="left").pack(
                         anchor="w", padx=20, pady=(0, 8))
        controls = tk.Frame(self.window, bg=BACKGROUND)
        controls.pack(fill="x", padx=20, pady=(0, 10))
        for caption, command in (("− Alejar", lambda: self.zoom(1 / 1.25)),
                                 ("+ Acercar", lambda: self.zoom(1.25)),
                                 ("Restablecer vista", self.reset)):
            tk.Button(controls, text=caption, command=command, bg=SURFACE, fg=ACCENT,
                      relief="flat", padx=12, pady=7).pack(side="left", padx=(0, 8))
        self.zoom_label = tk.Label(controls, bg=BACKGROUND, fg=INK, font=("Segoe UI", 10))
        self.zoom_label.pack(side="left", padx=10)
        tk.Label(self.window, text="Rueda: acercar/alejar · Arrastrar: mover ambas vistas · 0: restablecer",
                 bg=BACKGROUND, fg=MUTED, font=("Segoe UI", 10)).pack(side="bottom", pady=12)
        body = tk.Frame(self.window, bg=BACKGROUND)
        body.pack(fill="both", expand=True, padx=20)
        body.rowconfigure(0, weight=1)
        self.canvases = []
        for index, caption in enumerate((previous_caption, current_caption)):
            body.columnconfigure(index, weight=1, uniform="photos")
            panel = tk.Frame(body, bg=SURFACE)
            panel.grid(row=0, column=index, sticky="nsew", padx=(0, 6) if index == 0 else (6, 0))
            tk.Label(panel, text=caption, bg=SURFACE, fg=INK, wraplength=480,
                     font=("Segoe UI", 10, "bold"), pady=10).pack(fill="x")
            canvas = tk.Canvas(panel, bg="#232637", highlightthickness=0, cursor="fleur")
            canvas.pack(fill="both", expand=True)
            self.canvases.append(canvas)
            canvas.bind("<Configure>", lambda event: self.schedule_render())
            canvas.bind("<MouseWheel>", lambda event, i=index: self.wheel(event, i))
            canvas.bind("<ButtonPress-1>", lambda event: setattr(self, "drag_position", (event.x, event.y)))
            canvas.bind("<B1-Motion>", lambda event, i=index: self.drag(event, i))
            canvas.bind("<ButtonRelease-1>", lambda event: setattr(self, "drag_position", None))
        self.window.bind("<Key-plus>", lambda event: self.zoom(1.25))
        self.window.bind("<Key-minus>", lambda event: self.zoom(1 / 1.25))
        self.window.bind("<Key-0>", lambda event: self.reset())
        self.window.bind("<Escape>", lambda event: self.close())
        self.schedule_render()

    def canvas_size(self, index):
        canvas = self.canvases[index]
        return max(1, canvas.winfo_width()), max(1, canvas.winfo_height())

    def wheel(self, event, index):
        if event.delta:
            self.zoom(1.25 if event.delta > 0 else 1 / 1.25, index, (event.x, event.y))
        return "break"

    def zoom(self, factor, index=0, point=None):
        self.viewport.zoom_at(factor, self.images[index].size, self.canvas_size(index), point)
        self.schedule_render()

    def drag(self, event, index):
        if self.drag_position is not None:
            dx, dy = event.x - self.drag_position[0], event.y - self.drag_position[1]
            self.viewport.pan((dx, dy), self.images[index].size, self.canvas_size(index))
            self.drag_position = (event.x, event.y)
            self.schedule_render()

    def reset(self):
        self.viewport.reset()
        self.schedule_render()

    def schedule_render(self):
        if self.render_job is None:
            self.render_job = self.window.after(16, self.render)

    def render(self):
        self.render_job = None
        self.zoom_label.configure(text=f"{self.viewport.zoom:.2f}× · relativo al ajuste inicial")
        for index, (source, canvas) in enumerate(zip(self.images, self.canvases)):
            cw, ch = self.canvas_size(index)
            x, y, width, height = viewport_geometry(source.size, (cw, ch), self.viewport.zoom, self.viewport.center)
            scale = width / source.width
            # Render only visible source pixels; avoid an oversized full-image allocation at 8×.
            left, top = max(0, math.floor(-x / scale)), max(0, math.floor(-y / scale))
            right = min(source.width, math.ceil((cw - x) / scale))
            bottom = min(source.height, math.ceil((ch - y) / scale))
            cropped = source.crop((left, top, right, bottom))
            fitted = cropped.resize((max(1, round(cropped.width * scale)),
                                     max(1, round(cropped.height * scale))), Image.Resampling.LANCZOS)
            self.photos[index] = ImageTk.PhotoImage(fitted, master=self.window)
            canvas.delete("all")
            canvas.create_image(x + left * scale, y + top * scale, image=self.photos[index], anchor="nw")

    def close(self):
        if self.render_job is not None:
            self.window.after_cancel(self.render_job)
            self.render_job = None
        self.window.destroy()
