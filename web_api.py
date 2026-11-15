"""API local para el análisis individual de DermaVision."""
import io
import json
import logging
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError

from classifier_runtime import default_experiment, load_classifier
from longitudinal_analysis import classify
from web_followup import router as followup_router

app = FastAPI(title="DermaVision-X")
runtime_lock = Lock()
runtime = None
active_model = None
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 24_000_000
log = logging.getLogger(__name__)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.include_router(followup_router, prefix="/api")


@app.exception_handler(ValueError)
async def invalid_input(_request, error):
    return JSONResponse({"detail": str(error)}, status_code=400)


@app.middleware("http")
async def local_uploads(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin not in {
        None, "http://127.0.0.1:8765", "http://127.0.0.1:5173",
        "http://localhost:8765", "http://localhost:5173",
    }:
        return JSONResponse({"detail": "Origen no autorizado."}, status_code=403)
    return await call_next(request)


@app.get("/api/status")
def status():
    folder = default_experiment()
    return {"service": "DermaVision-X", "experiment": folder.name,
            "model_available": (folder / "model.keras").is_file()}


@app.get("/api/model/results")
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


@app.post("/api/analyze")
def analyze(file: UploadFile):
    content = file.file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "La imagen supera los 12 MB.")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(415, "Usa una imagen JPEG, PNG o WebP.")
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(413, "La imagen supera los 24 megapíxeles.")
            rgb = ImageOps.exif_transpose(image).convert("RGB")
    except Image.DecompressionBombError as exc:
        raise HTTPException(413, "La imagen supera el tamaño permitido.") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(415, "No se pudo abrir la imagen.") from exc

    with runtime_lock:
        model_path, classifier = get_runtime()
        result = classify(rgb, *classifier)
    if result["state"] != "accepted":
        result.pop("raw_score", None)
        result["score"] = None
    return {**result, "experiment": model_path.parent.name}


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
