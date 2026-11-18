"""Vídeo local académico a partir de visitas y resultados guardados."""
from pathlib import Path
from datetime import datetime
import os
import subprocess
import tempfile
import textwrap
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from longitudinal_insights import date_label, finite
from longitudinal_review import visit_review_rows


def export_photo_video(store, records, destination, *, seconds=4, show_date=True,
                       show_label=True, transition="cut"):
    """Encode a chronological H.264 sequence playable in the web application."""
    from imageio_ffmpeg import get_ffmpeg_exe

    if not records:
        raise ValueError("Registra al menos una fotografía.")
    if seconds not in (2, 3, 4, 5) or transition not in ("cut", "fade"):
        raise ValueError("Configuración de video inválida.")
    ordered = sorted(records, key=lambda record: (datetime.fromisoformat(record["captured_at"]), record["id"]))
    size, fps = (960, 540), 24
    frames_per_photo = seconds * fps
    fade_frames = fps // 2 if transition == "fade" else 0
    try:
        font = ImageFont.truetype("arial.ttf", 24)
        small = ImageFont.truetype("arial.ttf", 15)
    except OSError:
        font = small = ImageFont.load_default()

    def frame(record):
        photo, _ = store.load_images(record)
        fitted = ImageOps.contain(photo, size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, "#142921")
        canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
        draw = ImageDraw.Draw(canvas)
        title = " · ".join(item for item in (record["label"] if show_label else "",
                                            date_label(record["captured_at"]) if show_date else "") if item)
        if title:
            width = draw.textlength(title, font=font)
            draw.rounded_rectangle((16, 16, 42 + width, 57), radius=8, fill="#132720")
            draw.text((29, 23), title, font=font, fill="white")
        notice = "Uso experimental · No constituye un diagnóstico médico"
        draw.rectangle((0, size[1] - 26, size[0], size[1]), fill="#142921")
        draw.text((14, size[1] - 21), notice, font=small, fill="white")
        return canvas

    destination = Path(destination)
    with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
        temporary = Path(folder) / "video.mp4"
        command = [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
                   "-r", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264",
                   "-preset", "veryfast", "-crf", "22", "-threads", "2",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary)]
        with subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as encoder:
            try:
                current = frame(ordered[0])
                for index in range(len(ordered)):
                    upcoming = frame(ordered[index + 1]) if index + 1 < len(ordered) else None
                    blend = fade_frames if upcoming is not None else 0
                    data = current.tobytes()
                    for _ in range(frames_per_photo - blend):
                        encoder.stdin.write(data)
                    for step in range(1, blend + 1):
                        encoder.stdin.write(Image.blend(current, upcoming, step / (blend + 1)).tobytes())
                    current = upcoming
                encoder.stdin.close()
                if encoder.wait() != 0:
                    raise ValueError("No se pudo codificar el video MP4.")
            except BrokenPipeError as exc:
                raise ValueError("El codificador de video se detuvo antes de terminar.") from exc
            finally:
                if encoder.poll() is None:
                    encoder.kill()
        capture = cv2.VideoCapture(str(temporary))
        try:
            valid, _ = capture.read()
            if not valid or round(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != len(ordered) * frames_per_photo:
                raise ValueError("No se pudo verificar la duración del video.")
        finally:
            capture.release()
        os.replace(temporary, destination)


def export_video(store, records, comparisons, destination, mode="reference", progress=None, size=(1920, 1080), fps=10, seconds=3):
    records = sorted(records, key=lambda r: (r["captured_at"], r["id"]))
    if len(records) < 2:
        raise ValueError("Se necesitan al menos dos fotografías.")
    if mode not in ("reference", "consecutive") or fps < 1 or seconds <= 0 or min(size) < 100 or any(v % 2 for v in size):
        raise ValueError("Opciones de vídeo inválidas.")
    rows = visit_review_rows(comparisons, records, mode)
    width, height = size
    def font(scale):
        try:
            return ImageFont.truetype("arial.ttf", max(12, int(height * scale)))
        except OSError:
            return ImageFont.load_default()
    def slide(title, lines=(), photos=()):
        img = Image.new("RGB", size, "#f5f6fb")
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, width, int(height*.14)), fill="#17243b")
        draw.text((int(width*.04), int(height*.025)), title, font=font(.046), fill="white")
        top = int(height*.18)
        for line in lines:
            for part in textwrap.wrap(str(line), width=90) or [""]:
                draw.text((int(width*.045), top), part, font=font(.027), fill="#293850")
                top += int(height*.045)
        if photos:
            slot = int(width*.90/len(photos))
            available = max(60, height - top - int(height*.09))
            for i, photo in enumerate(photos):
                fitted = ImageOps.contain(photo.convert("RGB"), (slot - 20, available))
                x = int(width*.05) + i*slot + (slot-fitted.width)//2
                img.paste(fitted, (x, top + (available-fitted.height)//2))
        draw.text((int(width*.04), int(height*.95)), "Prototipo experimental · No constituye diagnóstico médico", font=font(.018), fill="#53657d")
        return np.asarray(img)[:, :, ::-1].copy()
    def image(record):
        return store.load_images(record)[0]
    def describe(entry):
        result = entry["comparison"]["result"] if entry["comparison"] else {}
        lines = [entry["title"] + " · " + entry["reason"][:110]]
        if entry["state"] == "available":
            lines.append(f"Índice descriptivo: {result['change_index']:.1f} / 100")
            area = result.get("changes", {}).get("area")
            if finite(area):
                lines.append(f"Área aparente: {area:+.1f} % · no es tamaño físico")
        return lines
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".dermavision-video-", suffix=".mp4", dir=destination.parent)
    os.close(fd)
    writer = None
    try:
        writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
        if not writer.isOpened():
            raise RuntimeError("No está disponible el codificador MP4 de OpenCV en este equipo.")
        total = len(rows) + 4
        def emit(frame, n):
            for _ in range(max(1, round(fps * seconds))):
                writer.write(frame)
            if progress:
                progress(n, total)
        emit(slide("DERMAVISION-X", ["Seguimiento longitudinal de lesiones cutáneas", "Prototipo experimental de investigación"]), 1)
        for i, entry in enumerate(rows):
            rec = entry["record"]
            emit(slide(f"Visita T{i} · {date_label(rec['captured_at'])}", describe(entry), [image(rec)]), i+2)
        emit(slide("Fotografía inicial y final", [date_label(records[0]["captured_at"]) + "   →   " + date_label(records[-1]["captured_at"]), "Fotografías originales · sin superposición"], [image(records[0]), image(records[-1])]), len(rows)+2)
        counts = {s: sum(r["state"] == s for r in rows) for s in ("available", "pending", "invalid", "stale")}
        emit(slide("Resumen del seguimiento", [f"Visitas: {len(records)} · {date_label(records[0]['captured_at'])} a {date_label(records[-1]['captured_at'])}", f"Mediciones disponibles: {counts['available']} · Pendientes: {counts['pending']}", f"No evaluables: {counts['invalid']} · Por recalcular: {counts['stale']}", "Modo: " + ("referencia inicial" if mode == "reference" else "intervalos consecutivos"), "La ausencia de medición no significa ausencia de cambio."]), len(rows)+3)
        emit(slide("DERMAVISION-X", ["Análisis experimental de cambios visuales", "Los resultados no constituyen un diagnóstico médico."]), total)
        writer.release()
        writer = None
        capture = cv2.VideoCapture(tmp)
        ok, frame = capture.read()
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        capture.release()
        if not ok or frame is None or count < total:
            raise RuntimeError("El vídeo generado no pudo verificarse.")
        os.replace(tmp, destination)
    finally:
        if writer is not None:
            writer.release()
        if os.path.exists(tmp):
            os.unlink(tmp)
    return total
