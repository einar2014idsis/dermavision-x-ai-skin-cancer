"""API local para el análisis individual de DermaVision."""
import base64
import io
import json
import logging
from pathlib import Path
from threading import Lock

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from classifier_runtime import default_experiment, load_classifier
from explainability import gradcam_explanation, occlusion_explanation
from longitudinal_analysis import classify, features, normalized, suggest_mask
from web_followup import authenticated, router as followup_router

app = FastAPI(title="DermaVision-X")
runtime_lock = Lock()
runtime = None
active_model = None
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 24_000_000
log = logging.getLogger(__name__)
pdf_lock = Lock()
LOCAL_ORIGINS = {
    f"http://{host}:{port}"
    for host in ("127.0.0.1", "localhost")
    for port in (8765, 5173)
}
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.include_router(followup_router, prefix="/api")


@app.exception_handler(ValueError)
async def invalid_input(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=400)


@app.middleware("http")
async def local_uploads(request: Request, call_next):
    origin = request.headers.get("origin")
    is_api = request.url.path.startswith("/api/")
    if is_api and (
        request.headers.get("sec-fetch-site") == "cross-site"
        or (origin is not None and origin not in LOCAL_ORIGINS)
    ):
        return JSONResponse({"detail": "Origen no autorizado."}, status_code=403)
    response = await call_next(request)
    if is_api:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/status")
def status():
    folder = default_experiment()
    return {"service": "DermaVision-X", "experiment": folder.name,
            "model_available": (folder / "model.keras").is_file()}


@app.get("/api/model/results", dependencies=[Depends(authenticated)])
def model_results():
    folder = default_experiment()
    metrics = folder / "metrics.json"
    if not metrics.is_file():
        raise HTTPException(404, "El modelo activo no tiene un informe de evaluación.")
    values = json.loads(metrics.read_text(encoding="utf-8"))
    scope = "Prueba histórica"
    calibration = folder / "calibration.json"
    if calibration.is_file():
        report = json.loads(calibration.read_text(encoding="utf-8"))
        selective = report.get("test_report_only", {}).get("after_abstention")
        if selective:
            values = {**selective, "confusion_matrix": None}
            scope = "Prueba histórica, casos concluyentes"
    return {
        "experiment": folder.name,
        "evaluation_scope": scope,
        "metrics": {key: values.get(key) for key in
                    ("accuracy", "sensitivity", "specificity", "f1", "auc", "threshold", "coverage")},
        "confusion_matrix": values.get("confusion_matrix"),
    }


def read_analysis_photo(file: UploadFile):
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "La imagen supera los 12 MB.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(415, "Usa una imagen JPEG, PNG o WebP.")
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(413, "La imagen supera los 24 megapíxeles.")
            return ImageOps.exif_transpose(image).convert("RGB")
    except Image.DecompressionBombError as exc:
        raise HTTPException(413, "La imagen supera el tamaño permitido.") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(415, "No se pudo abrir la imagen.") from exc


@app.post("/api/analyze/quality", dependencies=[Depends(authenticated)])
def analyze_quality(file: UploadFile):
    rgb = read_analysis_photo(file)
    result = classify(rgb)
    region = describe_region(rgb) if all(result["quality"]["checks"]) else None
    result["quality"]["framing"] = region["framing"] if region else None
    return result


@app.post("/api/analyze", dependencies=[Depends(authenticated)])
def analyze(file: UploadFile):
    rgb = read_analysis_photo(file)
    with runtime_lock:
        model_path, classifier = get_runtime()
        result = classify(rgb, *classifier)
        region = describe_region(rgb) if all(result["quality"]["checks"]) else None
        if result["state"] == "accepted":
            try:
                overlay, _ = occlusion_explanation(
                    classifier[0], rgb, result["label"], grid=14, display="magnitude-turbo",
                )
                if overlay.info["explanation_stats"]["informative"]:
                    result["heatmap"] = encode_png(overlay)
                    result["signed_heatmap"] = encode_png(overlay.info["signed_map"])
                result["occlusion_diagnostics"] = overlay.info["explanation_stats"]
            except Exception:
                log.exception("No se pudo generar el mapa de influencia")
            try:
                gradcam = gradcam_explanation(classifier[0], rgb, result["label"])
                if gradcam is not None:
                    image, stats = gradcam
                    result["gradcam"] = encode_png(image)
                    result["gradcam_diagnostics"] = stats
            except Exception:
                log.exception("No se pudo generar Grad-CAM")
    result["quality"]["framing"] = region["framing"] if region else None
    if result["state"] == "accepted":
        result["region_summary"] = region
        result["threshold"] = classifier[2].threshold
    if result["state"] != "accepted":
        result.pop("raw_score", None)
        result["score"] = None
    return {**result, "experiment": model_path.parent.name}


def encode_png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def describe_region(image):
    """Describe rasgos medidos sin atribuirles la decisión de la red."""
    try:
        rgb, mask = normalized(image, suggest_mask(image))
        if mask[[0, -1], :].any() or mask[:, [0, -1]].any():
            return None
        measured = features(rgb, mask)
        left, top, right, bottom = Image.fromarray(mask).getbbox()
        height, width = mask.shape
    except ValueError:
        return None
    return {
        "asymmetry": measured["asymmetry"],
        "border": measured["border_irregularity"],
        "lightness_variation": measured["color_lab_std"][0],
        "framing": min(left / width, top / height, 1 - right / width, 1 - bottom / height) >= 0.05,
    }


class AnalysisReport(BaseModel):
    lines: list[str] = Field(min_length=1, max_length=18)


@app.post("/api/analyze/report", dependencies=[Depends(authenticated)])
def analysis_report(report: AnalysisReport):
    from textwrap import wrap

    from matplotlib.figure import Figure

    if any(len(line) > 220 for line in report.lines):
        raise ValueError("El texto del informe es demasiado largo.")
    lines = [part for line in report.lines for part in wrap(line, width=76)]
    with pdf_lock:
        figure = Figure(figsize=(8.27, 11.69), facecolor="white")
        figure.text(.1, .92, "DermaVision-X", fontsize=24, color="#075d58", weight="bold")
        figure.text(.1, .88, "Informe de análisis individual", fontsize=15, weight="bold")
        figure.text(.1, .83, "\n".join(lines), va="top", fontsize=10, linespacing=1.45, parse_math=False)
        figure.text(.1, .07, "Prototipo de investigación. Resultado experimental de una fotografía.", fontsize=9)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="pdf")
    return Response(buffer.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="dermavision-analisis.pdf"'})


def get_runtime():
    """Usar bajo runtime_lock al cargar y ejecutar el clasificador."""
    global runtime, active_model
    model_path = default_experiment() / "model.keras"
    if runtime is None or active_model != model_path:
        try:
            loaded = load_classifier(model_path)
            if loaded[1] is None:
                raise ValueError("Falta el filtro de entrada.")
        except (OSError, ValueError, ImportError) as exc:
            log.exception("No se pudo cargar el clasificador")
            raise HTTPException(503, "No se pudo cargar el modelo y sus filtros.") from exc
        runtime, active_model = loaded, model_path
    return model_path, runtime


dist = Path(__file__).parent / "web" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="web")
