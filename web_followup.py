"""Rutas web para los datos de seguimiento y la cuenta local."""
import io
import json
import secrets
import tempfile
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app_paths import DATA_DIR
from evolution_video import export_video
from local_auth import LocalAdmin
from longitudinal_analysis import classify_record, compare_records, mask_overlay, suggest_mask
from domain_gate import feature_model
from longitudinal_reports import export_lesion_pdf
from longitudinal_store import LongitudinalStore

router = APIRouter()
admin = LocalAdmin(DATA_DIR / "security" / "administrator.json")
sessions = deque(maxlen=32)
cookie = "dermavision_session"


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class Person(BaseModel):
    code: str
    name: str = ""
    notes: str = ""


class Lesion(BaseModel):
    name: str
    site: str = ""


class Pair(BaseModel):
    previous: str
    current: str
    mode: str = "longitudinal"


class VisitEdit(BaseModel):
    date: str
    observation: str = Field(max_length=2000)


@router.get("/session")
def session(request: Request):
    return {"authenticated": request.cookies.get(cookie) in sessions, "configured": admin.exists()}


@router.post("/session")
def login(data: Credentials, response: Response):
    if not admin.exists():
        try:
            admin.create(data.username, data.password)
        except FileExistsError:
            pass
    if not admin.verify(data.username, data.password):
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    token = secrets.token_urlsafe(32)
    sessions.append(token)
    response.set_cookie(cookie, token, httponly=True, samesite="strict")
    return {"authenticated": True, "configured": True}


def authenticated(request: Request):
    if request.cookies.get(cookie) not in sessions:
        raise HTTPException(401, "Inicia sesión para abrir el historial.")


@router.delete("/session", dependencies=[Depends(authenticated)])
def logout(request: Request, response: Response):
    try:
        sessions.remove(request.cookies[cookie])
    except ValueError:
        pass
    response.delete_cookie(cookie)
    return {"authenticated": False}


records = APIRouter(dependencies=[Depends(authenticated)])


def store():
    return LongitudinalStore(DATA_DIR / "longitudinal")


@records.get("/people")
def people():
    return store().persons()


@records.post("/people")
def create_person(data: Person):
    return {"id": store().create_person(data.code, data.name, data.notes)}


@records.put("/people/{identifier}")
def update_person(identifier: str, data: Person):
    store().update_person(identifier, data.code, data.name, data.notes)
    return {"id": identifier}


@records.get("/people/{identifier}/lesions")
def lesions(identifier: str):
    return store().lesions(identifier)


@records.post("/people/{identifier}/lesions")
def create_lesion(identifier: str, data: Lesion):
    return {"id": store().create_lesion_for_person(identifier, data.name, data.site)}


@records.get("/lesions/{identifier}")
def followup(identifier: str):
    db = store()
    return {"visits": db.records(identifier), "comparisons": db.comparisons(identifier)}


def upload_image(file):
    content = file.file.read(12 * 1024 * 1024 + 1)
    if len(content) > 12 * 1024 * 1024:
        raise HTTPException(413, "La imagen supera los 12 MB.")
    try:
        with Image.open(io.BytesIO(content)) as im:
            if im.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Usa una imagen JPEG, PNG o WebP.")
            if im.width * im.height > 24_000_000:
                raise ValueError("La imagen supera los 24 megapíxeles.")
            return ImageOps.exif_transpose(im).convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("No se pudo abrir la imagen.") from exc


@records.post("/contour")
def contour(file: UploadFile):
    image = upload_image(file)
    preview = mask_overlay(image, suggest_mask(image))
    buffer = io.BytesIO()
    preview.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")


@records.post("/lesions/{identifier}/visits")
def add_visit(identifier: str, file: UploadFile, date: str = Form(),
              confirmed: bool = Form(), notes: str = Form(""), points: str = Form("")):
    if not confirmed:
        raise ValueError("Revisa y confirma el contorno.")
    image = upload_image(file)
    if points:
        polygon = json.loads(points)
        if not isinstance(polygon, list) or not 3 <= len(polygon) <= 256 or any(
            not isinstance(point, list) or len(point) != 2 or any(
                not isinstance(value, (int, float)) or not 0 <= value <= 1 for value in point
            ) for point in polygon
        ):
            raise ValueError("Dibuja al menos tres puntos válidos.")
        mask = Image.new("L", image.size)
        ImageDraw.Draw(mask).polygon(
            [(round(x * (image.width - 1)), round(y * (image.height - 1))) for x, y in polygon],
            fill=255,
        )
    else:
        mask = suggest_mask(image)
    return {"id": store().add_record(identifier, date, image, mask,
                                    {"mask_reviewed": True, "notes": notes})}


@records.get("/visits/{identifier}/photo")
def photo(identifier: str):
    db = store()
    return FileResponse(db.path(db.record(identifier)["image"]), media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@records.patch("/visits/{identifier}")
def edit_visit(identifier: str, data: VisitEdit):
    db = store()
    visit = db.record(identifier)
    if data.date != visit["captured_at"]:
        db.update_record_date(identifier, data.date)
    notes = {**visit["metadata"].get("visit_notes", {}), "observation": data.observation}
    db.update_visit_notes(identifier, notes)
    return {"id": identifier}


@records.delete("/visits/{identifier}")
def trash_visit(identifier: str):
    return {"undo": store().move_to_trash("record", identifier)}


@records.post("/visits/{identifier}/restore")
def restore_visit(identifier: str):
    store().restore_trash("record", identifier)
    return {"id": identifier}


@records.post("/visits/{identifier}/analyze")
def analyze_visit(identifier: str):
    from web_api import get_runtime, runtime_lock

    with runtime_lock:
        model_path, (model, gate, calibration) = get_runtime()
        return classify_record(store(), identifier, model, gate, calibration, model_path)


@records.post("/comparisons")
def compare(data: Pair):
    from web_api import get_runtime, runtime_lock

    if data.mode not in {"visual", "longitudinal"}:
        raise ValueError("Modo de comparación inválido.")
    with runtime_lock:
        model_path, (model, gate, calibration) = get_runtime()
        payload = compare_records(
            store(), data.previous, data.current, model=model, gate=gate,
            extractor=feature_model(model), model_path=model_path,
            calibration=calibration, mode=data.mode, fallback_visual=True,
        )
    return {"id": payload["id"], "result": payload["result"]}


@records.get("/lesions/{identifier}/comparisons/{comparison_id}/map")
def comparison_map(identifier: str, comparison_id: str):
    db = store()
    row = next((r for r in db.comparisons(identifier) if r["id"] == comparison_id), None)
    if row is None or not row.get("overlay"):
        raise HTTPException(404, "Mapa no disponible.")
    return FileResponse(db.path(row["overlay"]), media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@records.get("/lesions/{identifier}/export/{extension}")
def export(identifier: str, extension: str):
    if extension not in {"pdf", "mp4"}:
        raise HTTPException(404)
    temp = tempfile.TemporaryDirectory()
    path = Path(temp.name) / f"seguimiento.{extension}"
    db = store()
    try:
        if extension == "pdf":
            export_lesion_pdf(db, identifier, path)
        else:
            export_video(db, db.records(identifier), db.comparisons(identifier), path)
    except Exception:
        temp.cleanup()
        raise
    return FileResponse(path, filename=path.name,
                        background=BackgroundTask(temp.cleanup),
                        headers={"Cache-Control": "no-store"})


router.include_router(records)
