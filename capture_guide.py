"""Calidad técnica de la zona elegida. No localiza ni identifica lesiones."""

from dataclasses import dataclass
import time

import cv2
import numpy as np


@dataclass
class Assessment:
    ready: bool
    message: str
    brightness: float
    sharpness: float
    box: tuple | None = None
    progress: float = 0
    checks: tuple = ()


class CaptureGuide:
    def __init__(self, hold_seconds=2.0, warmup_seconds=3.0):
        if hold_seconds <= 0 or warmup_seconds < 0:
            raise ValueError("Tiempos de captura inválidos.")
        self.hold_seconds = hold_seconds
        self.warmup_seconds = warmup_seconds
        self.reset()

    def reset(self):
        self.previous = None
        self.since = None
        self.last_time = None
        self.started = None

    def evaluate(self, image, now=None, static=False):
        now = time.monotonic() if now is None else now
        if self.started is None:
            self.started = now
        gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        gray = cv2.resize(gray, (224, 224), interpolation=cv2.INTER_AREA)
        brightness = float(gray.mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        stable_gray = cv2.GaussianBlur(gray, (9, 9), 0).astype(float)
        motion = float("inf")
        if self.previous is not None:
            # El autoexposure y el parpadeo de una pantalla no son desplazamiento.
            # Compensar solo pequeños cambios globales de brillo y hasta 3 píxeles
            # de traslación; un movimiento grande continúa bloqueando la captura.
            old = self.previous - self.previous.mean()
            new = stable_gray - stable_gray.mean()
            motion = float(np.abs(new - old).mean())
            (dx, dy), response = cv2.phaseCorrelate(old, new)
            if response > 0.25 and max(abs(dx), abs(dy)) <= 3:
                aligned = cv2.warpAffine(
                    new,
                    np.float64([[1, 0, -dx], [0, 1, -dy]]),
                    (224, 224),
                    borderMode=cv2.BORDER_REFLECT,
                )
                motion = float(np.abs(aligned[5:-5, 5:-5] - old[5:-5, 5:-5]).mean())
            elif response > 0.25 and max(abs(dx), abs(dy)) > 3:
                motion = float("inf")
        self.previous = stable_gray
        if self.last_time is not None and now - self.last_time > 0.5:
            self.since = None
        self.last_time = now
        box = None
        message = ""
        resolution_ok = min(image.size) >= 128
        light_ok = (
            45 <= brightness <= 215
            and float((gray < 15).mean()) <= 0.35
            and float((gray > 245).mean()) <= 0.20
        )
        focus_ok = sharpness >= 40
        # El encuadre es una elección del usuario: la antigua máscara no es un
        # localizador entrenado y ya no puede bloquear imágenes por su posición.
        checks = (resolution_ok, light_ok, focus_ok, static or motion <= 4)
        if not resolution_ok:
            message = (
                "Resolución insuficiente: acerque la cámara o aumente su resolución."
            )
        elif brightness < 45 or float((gray < 15).mean()) > 0.35:
            message = "Falta iluminación. Evite sombras."
        elif brightness > 215 or float((gray > 245).mean()) > 0.20:
            message = "Exceso de luz o reflejos. Reduzca la iluminación."
        elif not focus_ok:
            message = (
                "Enfoque insuficiente. Ajuste la distancia y el enfoque de la cámara."
            )
        elif not static and now - self.started < self.warmup_seconds:
            message = f"Ajustando cámara: espere {self.warmup_seconds-(now-self.started):.1f} s."
        elif not static and motion > 4:
            message = "Mantenga la cámara estable y espere a que termine de enfocar."
        if message:
            self.since = None
            return Assessment(False, message, brightness, sharpness, box, 0, checks)
        if static:
            return Assessment(
                True,
                "Revise el encuadre y pulse «Analizar captura».",
                brightness,
                sharpness,
                box,
                1,
                checks,
            )
        if self.since is None:
            self.since = now
        elapsed = now - self.since
        ready = elapsed >= self.hold_seconds
        return Assessment(
            ready,
            (
                "Captura técnica lista; falta verificar que sea una lesión."
                if ready
                else f"Mantenga la posición: {max(0, self.hold_seconds-elapsed):.1f} s"
            ),
            brightness,
            sharpness,
            box,
            min(1, elapsed / self.hold_seconds),
            checks,
        )
