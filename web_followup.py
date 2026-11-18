"""Rutas web para los datos de seguimiento y la cuenta local."""
import csv
import hashlib
import io
import json
import secrets
import tempfile
from collections import deque
from datetime import date as calendar_date
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Literal

import cv2
import numpy as np
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app_paths import DATA_DIR, PROJECT_DIR
from anatomy import validate_anatomical_location
from evolution_video import export_photo_video, export_video
from local_auth import LocalAdmin
from longitudinal_analysis import classify, classify_record, compare_records, local_texture_map, mask_overlay, normalized, suggest_mask
from longitudinal_analysis import prepare_record_analysis
from longitudinal_insights import comparison_narrative, comparison_validity, finite, measurement_rows, trend_series
from longitudinal_review import identity_description, visit_review_rows
from longitudinal_reports import export_lesion_pdf, report_comparison_state, report_photo_state
from longitudinal_store import LongitudinalStore
from longitudinal_store import now
from workspace_records import archive_document, dashboard, document_file, documents, ensure_workspace, lesion_summary, patient_visits

router = APIRouter()
admin = LocalAdmin(DATA_DIR / "security" / "administrator.json")
sessions = deque(maxlen=32)
cookie = "dermavision_session"
comparison_previews = {}
preview_lock = Lock()
report_pdf_lock = Lock()
account_lock = Lock()
visit_previews = {}


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class Person(BaseModel):
    code: str
    name: str = ""
    notes: str = ""


class NewPerson(Person):
    automatic_code: bool = False


class Lesion(BaseModel):
    name: str
    site: str = ""


class AnatomicalLocation(BaseModel):
    region_id: str = Field(max_length=80)
    x: float = Field(ge=0, le=1, strict=True)
    y: float = Field(ge=0, le=1, strict=True)
    origin: Literal["manual", "default"]


class LesionDetails(Lesion):
    registered_on: calendar_date
    description: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=500)
    body_view: Literal["front", "back"] = "front"
    location: AnatomicalLocation | None = None
    automatic_code: bool = False

    def details(self):
        if not self.description.strip():
            raise ValueError("Indica una descripción inicial de la lesión.")
        return self.registered_on.isoformat(), self.description.strip(), self.notes.strip(), self.body_view

    def marker(self):
        if self.location is None:
            raise ValueError("Selecciona una región anatómica en el mapa o en el desplegable.")
        return validate_anatomical_location(self.location.region_id, self.body_view, self.site.strip(),
                                             self.location.x, self.location.y, self.location.origin)


class PasswordChange(BaseModel):
    current: str = Field(min_length=1, max_length=256)
    replacement: str = Field(min_length=10, max_length=256)


class Pair(BaseModel):
    previous: str
    current: str
    mode: str = "longitudinal"


class VisitEdit(BaseModel):
    date: str
    observation: str = Field(max_length=2000)


ReportSection = Literal["identity", "photos", "classifications", "charts",
                        "measurements", "maps", "summary", "observations"]


class ReportOptions(BaseModel):
    sections: set[ReportSection]


class VideoOptions(BaseModel):
    seconds: Literal[2, 3, 4, 5] = 4
    show_date: bool = True
    show_label: bool = True
    transition: Literal["cut", "fade"] = "cut"


@router.get("/session")
def session(request: Request):
    return {"authenticated": request.cookies.get(cookie) in sessions, "configured": admin.exists()}


@router.post("/session")
def login(data: Credentials, response: Response):
    with account_lock:
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
        raise HTTPException(401, "Inicia sesión para acceder a DermaVision X.")


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


@records.get("/workspace")
def workspace_home():
    return dashboard(store())


@records.get("/people/{identifier}/profile")
def patient_profile(identifier: str):
    db = store()
    return {"person": db.person(identifier), "lesions": lesion_summary(db, identifier),
            "visits": patient_visits(db, identifier), "documents": documents(db, identifier)}


@records.get("/people/{identifier}/documents/{key}")
def read_document(identifier: str, key: str, preview: bool = False):
    path, filename = document_file(store(), identifier, key)
    return FileResponse(path, filename=filename, content_disposition_type="inline" if preview else "attachment")


@records.post("/people/{identifier}/lesion-details")
def register_lesion_details(identifier: str, data: LesionDetails):
    db = store()
    ensure_workspace(db)
    name = None if data.automatic_code else data.name
    return {"id": db.create_lesion_for_person(identifier, name, data.site, data.details(), data.marker())}


@records.get("/people/{identifier}/lesion-code")
def suggest_lesion_code(identifier: str):
    db = store()
    db.person(identifier)
    return {"code": db.next_code(identifier)}


@records.put("/people/{identifier}/lesion-details/{key}")
def edit_lesion_details(identifier: str, key: str, data: LesionDetails):
    import sqlite3
    db = store()
    ensure_workspace(db)
    name, site = data.name.strip(), data.site.strip()
    if not name or len(name) > 160 or len(site) > 160:
        raise ValueError("Indica un código y localización de hasta 160 caracteres.")
    try:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("""
                SELECT l.name,l.site,m.region_id FROM lesions l
                LEFT JOIN workspace_lesion_locations m ON m.lesion_id=l.id
                WHERE l.id=? AND l.person_id=?
            """, (key, identifier)).fetchone()
            if existing is None:
                raise HTTPException(404, "Lesión inexistente para este paciente.")
            if name != existing["name"] and conn.execute(
                "SELECT 1 FROM lesions WHERE person_id=? AND id<>? AND name=? COLLATE NOCASE",
                (identifier, key, name),
            ).fetchone():
                raise ValueError("Esa lesión ya existe para esta persona.")
            marker = None
            if data.location is not None or existing["region_id"] or site != existing["site"]:
                marker = data.marker()
            conn.execute("UPDATE lesions SET name=?,site=? WHERE id=? AND person_id=?",
                         (name, site, key, identifier))
            conn.execute("""INSERT INTO workspace_lesions VALUES(?,?,?,?,?)
                ON CONFLICT(lesion_id) DO UPDATE SET registered_on=excluded.registered_on,
                description=excluded.description,notes=excluded.notes,body_view=excluded.body_view""",
                         (key, *data.details()))
            if marker:
                conn.execute("""INSERT INTO workspace_lesion_locations VALUES(?,?,?,?,?)
                    ON CONFLICT(lesion_id) DO UPDATE SET region_id=excluded.region_id,
                    marker_x=excluded.marker_x,marker_y=excluded.marker_y,origin=excluded.origin""",
                             (key, *marker))
    except sqlite3.IntegrityError as exc:
        raise ValueError("Esa lesión ya existe para esta persona.") from exc
    return {"id": key}


@records.get("/settings")
def administrator_settings():
    import platform
    from classifier_runtime import default_experiment
    db = store()
    ensure_workspace(db)
    with db.connect() as conn:
        health = conn.execute("PRAGMA quick_check").fetchone()[0]
        documentation = conn.execute("SELECT count(*) FROM workspace_documents").fetchone()[0]
        activity = [dict(row) for row in conn.execute(
            "SELECT created,action FROM workspace_admin_activity ORDER BY id DESC LIMIT 10")]
    experiment = default_experiment()
    package = PROJECT_DIR / "web" / "package.json"
    version = json.loads(package.read_text(encoding="utf-8")).get("version") if package.is_file() else None
    return {"username": admin.username(), "role": "Administrador local", "database_ok": health == "ok",
            "database_bytes": db.db.stat().st_size, "documents": documentation, "activity": activity,
            "python": platform.python_version(), "model": experiment.name, "version": version,
            "model_available": (experiment / "model.keras").is_file()}


@records.put("/settings/password")
def rotate_password(data: PasswordChange, response: Response):
    db = store()
    ensure_workspace(db)
    with account_lock:
        if not admin.change_password(data.current, data.replacement):
            raise HTTPException(400, "La contraseña actual es incorrecta.")
        sessions.clear()
        response.delete_cookie(cookie)
    with db.connect() as conn:
        conn.execute("INSERT INTO workspace_admin_activity(created,action) VALUES(?,?)",
                     (now(), "Contraseña actualizada"))
    return {"authenticated": False}


@records.get("/settings/backup")
def workspace_backup():
    db = store()
    ensure_workspace(db)
    temp = tempfile.TemporaryDirectory()
    try:
        path = db.backup(Path(temp.name) / "dermavision-respaldo.zip")
        with db.connect() as conn:
            conn.execute("INSERT INTO workspace_admin_activity(created,action) VALUES(?,?)",
                         (now(), "Respaldo verificado generado"))
    except Exception:
        temp.cleanup()
        raise
    return FileResponse(path, filename=path.name, background=BackgroundTask(temp.cleanup))


@records.get("/people")
def people():
    return store().persons()


@records.post("/people")
def create_person(data: NewPerson):
    db = store()
    identifier = db.create_person(None if data.automatic_code else data.code, data.name, data.notes)
    return {"id": identifier, "code": db.person(identifier)["code"]}


@records.get("/people/next-code")
def suggest_person_code():
    return {"code": store().next_code()}


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
    visits = db.records(identifier)
    comparisons = db.comparisons(identifier)
    temporal = [row for row in comparisons if row["result"].get("mode") != "visual"
                or row["result"].get("requested_mode") == "longitudinal"]
    for row in comparisons:
        row.update(comparison_details(row, visits))
        row["map_available"] = bool(
            row["technical"]["show_map"] and row.get("overlay")
            and db.path(row["overlay"]).is_file()
        )
    timeline = reference_timeline(temporal, visits)
    for visit in visits:
        visit["identity_description"] = identity_description(visit)
    pairs = {(row["previous_id"], row["current_id"]): row["technical"]["kind"] for row in comparisons}
    stats = dict(evaluable=sum(kind == "comparable" for kind in pairs.values()), pairs=len(pairs),
                 classified=sum(report_photo_state(visit)[2] for visit in visits))
    return {"visits": visits, "comparisons": comparisons, "timeline": timeline, "report_stats": stats}


def comparison_details(row, visits):
    state = report_comparison_state(row, visits)
    result = row["result"]
    return dict(technical=state, measurements=measurement_rows(result) if state["show_map"] else [],
                description=state["reason"] if state["kind"] == "outdated" else comparison_narrative(result))


def reference_timeline(temporal, visits):
    timeline = []
    if visits:
        series = trend_series(temporal, visits, visits[0]["id"])
        values = {p["target"]: p["value"] for p in series["points"]}
        for item in visit_review_rows(temporal, visits):
            record = item["record"]
            comparison = item["comparison"] if item["state"] in {"available", "invalid"} else None
            result = comparison["result"] if comparison else {}
            changes = result.get("changes", {})
            value = values.get(record["id"])
            valid = value is not None
            metrics = {"index": value}
            for key in ("area", "asymmetry", "border", "color", "texture"):
                metrics[key] = changes.get(key) if valid and finite(changes.get(key)) else None
            timeline.append(dict(
                id=record["id"], date=record["captured_at"], title=item["title"],
                reason=item["reason"], state=item["state"], value=value, metrics=metrics,
                comparison_id=(item["comparison"] or {}).get("id"),
            ))
    return timeline


@records.get("/lesions/{identifier}/export/csv")
def export_timeline_csv(identifier: str):
    db = store()
    visits = db.records(identifier)
    comparisons = [row for row in db.comparisons(identifier) if row["result"].get("mode") != "visual"
                   or row["result"].get("requested_mode") == "longitudinal"]
    timeline = reference_timeline(comparisons, visits)
    content = io.StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(["visita", "fecha_captura", "estado", "indice_0_100",
                     "area_aparente_pct", "delta_asimetria", "delta_bordes", "color_delta_e", "delta_textura"])
    for index, row in enumerate(timeline):
        writer.writerow([f"T{index}", row["date"], row["title"], *row["metrics"].values()])
    return Response("\ufeff" + content.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="seguimiento.csv"'})


@records.post("/lesions/{identifier}/timeline")
def calculate_timeline(identifier: str):
    db = store()
    visits = db.records(identifier)
    if len(visits) < 2:
        raise ValueError("Registra dos fotografías para calcular la evolución.")
    reference = visits[0]
    errors = {}
    for visit in visits[1:]:
        if visit["captured_at"] <= reference["captured_at"]:
            continue
        try:
            compare_records(db, reference["id"], visit["id"], fallback_visual=True)
        except (ValueError, OSError) as exc:
            errors[visit["id"]] = str(exc)
    return {"errors": errors}


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


def reviewed_mask(image, points):
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
    return mask


def visit_metadata(db, identifier, image, notes, same_lesion):
    visits = db.records(identifier)
    assessment = classify(image)["quality"]
    metadata = {"mask_reviewed": True, "notes": notes, "capture_quality": assessment}
    if not visits:
        metadata["lesion_identity"] = dict(status="initial_reference", reference_id=None,
                                           method="initial_registration")
    elif same_lesion:
        metadata["lesion_identity"] = dict(status="user_declared", reference_id=visits[0]["id"],
                                           method="human_confirmation")
    return metadata


@records.post("/lesions/{identifier}/visits")
def add_visit(identifier: str, file: UploadFile, date: str = Form(),
              confirmed: bool = Form(), notes: str = Form(""), points: str = Form(""),
              same_lesion: bool = Form(False)):
    if not confirmed:
        raise ValueError("Revisa y confirma el contorno.")
    image = upload_image(file)
    mask = reviewed_mask(image, points)
    db = store()
    metadata = visit_metadata(db, identifier, image, notes, same_lesion)
    return {"id": db.add_record(identifier, date, image, mask, metadata)}


def visit_fingerprint(image, mask):
    digest = hashlib.sha256(str(image.size).encode())
    digest.update(image.tobytes())
    digest.update(mask.tobytes())
    return digest.hexdigest()


@records.post("/lesions/{identifier}/visit-analysis")
def preview_visit_analysis(identifier: str, request: Request, file: UploadFile,
                           points: str = Form("")):
    from web_api import get_runtime, runtime_lock

    db = store()
    if not any(row["id"] == identifier for row in db.lesions()):
        raise HTTPException(404, "Selecciona una lesión registrada.")
    image = upload_image(file)
    mask = reviewed_mask(image, points)
    with runtime_lock:
        path, (model, gate, calibration) = get_runtime()
        result, explanation = prepare_record_analysis(image, mask, model, gate, calibration, path)
    key = secrets.token_urlsafe(24)
    with preview_lock:
        visit_previews[key] = dict(created=monotonic(), token=request.cookies[cookie], lesion=identifier,
                                   fingerprint=visit_fingerprint(image, mask), result=result, explanation=explanation)
        if len(visit_previews) > 12:
            visit_previews.pop(next(iter(visit_previews)))
    return {"id": key, "state": result["state"], "label": result.get("label"),
            "score": result.get("score"), "message": result.get("message")}


@records.post("/lesions/{identifier}/visits/analyzed")
def save_analyzed_visit(identifier: str, request: Request, file: UploadFile, date: str = Form(),
                        analyzed: str = Form(), confirmed: bool = Form(), notes: str = Form(""),
                        points: str = Form(""), same_lesion: bool = Form(False)):
    if not confirmed:
        raise ValueError("Revisa y confirma el contorno.")
    image = upload_image(file)
    mask = reviewed_mask(image, points)
    db = store()
    with preview_lock:
        entry = visit_previews.get(analyzed)
        if (not entry or entry["token"] != request.cookies[cookie] or entry["lesion"] != identifier
                or monotonic() - entry["created"] > 1800):
            raise HTTPException(409, "Vuelve a analizar esta fotografía antes de guardar.")
        if entry["fingerprint"] != visit_fingerprint(image, mask):
            raise HTTPException(409, "La fotografía o el contorno cambió. Vuelve a analizar la visita.")
        if not entry.get("saved"):
            metadata = visit_metadata(db, identifier, image, notes, same_lesion)
            if metadata.get("lesion_identity") is None:
                raise ValueError("Confirma que la fotografía corresponde a la misma lesión.")
            entry["saved"] = db.add_record(identifier, date, image, mask, metadata,
                                           analysis=entry["result"], explanation=entry["explanation"])
        return {"id": entry["saved"]}


@records.get("/visits/{identifier}/photo")
def photo(identifier: str):
    db = store()
    return FileResponse(db.path(db.record(identifier)["image"]), media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@records.get("/visits/{identifier}/contour")
def visit_contour(identifier: str):
    db = store()
    image, mask = db.load_images(db.record(identifier))
    buffer = io.BytesIO()
    mask_overlay(image, mask).save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")


@records.post("/visits/{identifier}/identity")
def confirm_visit_identity(identifier: str):
    store().confirm_record_identity(identifier)
    return {"id": identifier}


@records.get("/visits/{identifier}/influence")
def visit_influence(identifier: str):
    try:
        image = store().load_explanation(identifier)
    except (ValueError, OSError) as exc:
        raise HTTPException(404, "Analiza la visita para generar su mapa de influencia.") from exc
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")


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
    if data.mode not in {"visual", "longitudinal"}:
        raise ValueError("Modo de comparación inválido.")
    db = store()
    previous, current = db.pair(data.previous, data.current, "visual")
    if previous["lesion_id"] != current["lesion_id"]:
        raise ValueError("Selecciona dos fotografías de la misma ficha de lesión.")
    if previous["captured_at"] > current["captured_at"]:
        previous, current = current, previous
    same_date = previous["captured_at"] == current["captured_at"]
    payload = compare_records(
        db, previous["id"], current["id"],
        mode="visual" if same_date else data.mode, fallback_visual=True,
        requested_mode=data.mode if same_date else None,
    )
    return {"id": payload["id"], "result": payload["result"]}


@records.post("/lesions/{identifier}/comparison-previews")
def preview_comparison(identifier: str, data: Pair, request: Request):
    db = store()
    previous, current = db.pair(data.previous, data.current)
    if previous["lesion_id"] != identifier or data.mode not in {"longitudinal", "visual"}:
        raise ValueError("Selecciona dos fotografías de esta lesión y un modo válido.")
    payload = compare_records(db, data.previous, data.current, mode=data.mode,
                              fallback_visual=True, persist=False)
    key = secrets.token_urlsafe(24)
    row = dict(id=key, previous_id=data.previous, current_id=data.current, result=payload["result"])
    row.update(comparison_details(row, [previous, current]))
    with preview_lock:
        comparison_previews[key] = (monotonic(), request.cookies[cookie], identifier, row, payload["overlay"])
        if len(comparison_previews) > 12:
            comparison_previews.pop(next(iter(comparison_previews)))
    return {**row, "draft": True, "map_available": row["technical"]["show_map"]}


def get_preview(identifier, key, request, visits):
    with preview_lock:
        entry = comparison_previews.get(key)
        if entry and monotonic() - entry[0] > 1800:
            comparison_previews.pop(key)
            entry = None
    if entry is None or entry[1:3] != (request.cookies[cookie], identifier):
        raise HTTPException(404, "La vista previa ya no está disponible. Analiza el par nuevamente.")
    row, overlay = entry[3:]
    invalid = comparison_validity(row, visits)
    if invalid:
        raise HTTPException(409, invalid.capitalize() + ".")
    return row, overlay


@records.post("/lesions/{identifier}/comparison-previews/{key}/save")
def save_comparison_preview(identifier: str, key: str, request: Request):
    db = store()
    row, overlay = get_preview(identifier, key, request, db.records(identifier))
    return {"id": db.save_comparison(row["previous_id"], row["current_id"], row["result"], overlay)}


def stored_comparison(db, identifier, comparison_id):
    row = next((r for r in db.comparisons(identifier) if r["id"] == comparison_id), None)
    if row is None:
        raise HTTPException(404, "Comparación no disponible.")
    return row


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


def aligned_inputs(db, row):
    matrix = np.asarray(row["result"].get("registration", {}).get("matrix"), dtype=float)
    if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
        raise HTTPException(404, "Alineación no disponible.")
    previous, m0 = normalized(*db.load_images(db.record(row["previous_id"])))
    current, m1 = normalized(*db.load_images(db.record(row["current_id"])))
    size = (previous.shape[1], previous.shape[0])
    return (previous, cv2.warpAffine(current, matrix, size), m0,
            cv2.warpAffine(m1.astype("uint8"), matrix, size, flags=cv2.INTER_NEAREST))


@records.get("/lesions/{identifier}/pair-view/{key}/{kind}")
def comparison_asset(identifier: str, key: str, kind: str, request: Request, draft: bool = False):
    db = store()
    visits = db.records(identifier)
    if draft:
        row, overlay = get_preview(identifier, key, request, visits)
    else:
        row, overlay = stored_comparison(db, identifier, key), None
    state = report_comparison_state(row, visits)
    if kind == "map" and state["show_map"]:
        if draft:
            return png(overlay)
        return comparison_map(identifier, key)
    if state["kind"] != "comparable" or kind not in {"previous", "current", "contours", "area", "texture"}:
        raise HTTPException(404, "Vista alineada no disponible para este par.")
    previous, current, m0, m1 = aligned_inputs(db, row)
    if kind == "contours":
        previous = previous.copy()
        for mask, color in ((m0, (5, 220, 111)), (m1, (255, 62, 66))):
            outlines, _ = cv2.findContours(mask.astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(previous, outlines, -1, color, 2)
    if kind == "area":
        previous = previous.copy()
        m1 = m1.astype(bool)
        for region, color in ((m1 & ~m0, (255, 62, 66)), (m0 & ~m1, (36, 111, 255))):
            previous[region] = np.rint(.35 * previous[region] + .65 * np.asarray(color)).astype("uint8")
    if kind == "texture":
        offset = np.asarray(row["result"].get("color_normalization", {}).get("offset"), dtype="float32")
        if offset.shape != (3,) or not np.isfinite(offset).all():
            raise HTTPException(404, "No hay corrección de color disponible para comparar textura local.")
        previous = local_texture_map(previous, current, m0 & m1.astype(bool), offset)
    return png(Image.fromarray(current if kind == "current" else previous))


@records.get("/lesions/{identifier}/comparisons/{key}/export/{extension}")
def export_comparison(identifier: str, key: str, extension: str):
    db = store()
    row = stored_comparison(db, identifier, key)
    visits = db.records(identifier)
    if extension == "pdf":
        return build_export(identifier, "pdf", comparison=row)
    if extension != "csv":
        raise HTTPException(404)
    details = comparison_details(row, visits)
    content = io.StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(["comparacion", "captura_inicial", "captura_posterior", "estado",
                     "indicador", "inicial", "posterior", "diferencia", "unidad_o_interpretacion"])
    base = [key, row["live_previous_date"], row["live_current_date"], details["technical"]["label"]]
    for measurement in details["measurements"] or [["Sin mediciones", "", "", "", details["technical"]["reason"]]]:
        writer.writerow([*base, *measurement])
    return Response("\ufeff" + content.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="comparacion.csv"', "Cache-Control": "no-store"})


@records.get("/lesions/{identifier}/comparisons/{comparison_id}/map")
def comparison_map(identifier: str, comparison_id: str):
    db = store()
    row = next((r for r in db.comparisons(identifier) if r["id"] == comparison_id), None)
    if row is None or not row.get("overlay") or not report_comparison_state(row, db.records(identifier))["show_map"]:
        raise HTTPException(404, "Mapa no disponible.")
    path = db.path(row["overlay"])
    if not path.is_file():
        raise HTTPException(404, "Mapa no disponible.")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@records.get("/lesions/{identifier}/comparisons/{comparison_id}/aligned")
def aligned_timeline_photo(identifier: str, comparison_id: str):
    db = store()
    visits = db.records(identifier)
    comparisons = db.comparisons(identifier)
    temporal = [row for row in comparisons if row["result"].get("mode") != "visual"
                or row["result"].get("requested_mode") == "longitudinal"]
    if not any(point["comparison_id"] == comparison_id and point["state"] == "available"
               for point in reference_timeline(temporal, visits)):
        raise HTTPException(404, "Fotografía alineada no disponible.")
    row = next(row for row in temporal if row["id"] == comparison_id)
    _, aligned, _, _ = aligned_inputs(db, row)
    return png(Image.fromarray(aligned))


@records.get("/lesions/{identifier}/export/{extension}")
def export(identifier: str, extension: str):
    return build_export(identifier, extension)


def report_scope(identifier):
    db = store()
    lesion = next((row for row in db.lesions() if row["id"] == identifier), None)
    if lesion is None:
        raise HTTPException(404, "Selecciona una lesión registrada.")
    person = next((row for row in db.persons() if row["id"] == lesion["person_id"]), None)
    if person is None:
        raise ValueError("La lesión requiere una persona asociada.")
    visits = db.records(identifier)
    if not visits:
        raise ValueError("Registra al menos una fotografía para exportar el seguimiento.")
    return db, lesion, person, visits


def configured_export(extension, generate):
    temp = tempfile.TemporaryDirectory()
    path = Path(temp.name) / f"seguimiento.{extension}"
    try:
        generate(path)
    except OSError as exc:
        temp.cleanup()
        raise ValueError("No se pudo abrir una fotografía o escribir la exportación.") from exc
    except Exception:
        temp.cleanup()
        raise
    return FileResponse(path, filename=path.name, background=BackgroundTask(temp.cleanup))


@records.post("/lesions/{identifier}/reports/pdf")
def configured_pdf(identifier: str, options: ReportOptions, archive: bool = False):
    from longitudinal_pdf import export_configured_pdf

    db, lesion, person, visits = report_scope(identifier)
    for visit in visits:
        if not db.path(visit["image"]).is_file():
            raise ValueError(f'La fotografía {visit["label"]} no está disponible.')
    comparisons = db.comparisons(identifier)
    def generate(path):
        export_configured_pdf(db, lesion, person, visits, comparisons, path, options.sections)
        if archive:
            archive_document(db, identifier, path, "Informe de seguimiento")
    with report_pdf_lock:
        return configured_export("pdf", generate)


@records.post("/lesions/{identifier}/reports/video")
def configured_video(identifier: str, options: VideoOptions):
    db, _, _, visits = report_scope(identifier)
    def generate(path):
        export_photo_video(db, visits, path, **options.model_dump())
        archive_document(db, identifier, path, "Video de seguimiento")
    return configured_export("mp4", generate)


@records.get("/lesions/{identifier}/reports/csv")
def configured_csv(identifier: str):
    db, lesion, person, visits = report_scope(identifier)
    comparisons = [row for row in db.comparisons(identifier) if row["result"].get("mode") != "visual"
                   or row["result"].get("requested_mode") == "longitudinal"]
    timeline = {row["id"]: row for row in reference_timeline(comparisons, visits)}
    content = io.StringIO(newline="")
    writer = csv.writer(content)
    writer.writerow(["codigo_persona", "id_lesion", "visita", "fecha_captura", "clasificacion",
                     "modelo_sha256", "estado_medicion", "indice_0_100", "area_aparente_pct",
                     "delta_asimetria", "delta_bordes", "color_delta_e", "delta_textura"])
    code = person["code"]
    if code.lstrip().startswith(("=", "+", "-", "@")) or code.startswith(("\t", "\r", "\n")):
        code = "'" + code
    for visit in visits:
        row = timeline[visit["id"]]
        state, _, current = report_photo_state(visit)
        model = (visit["metadata"].get("classification") or {}).get("model_sha256") if current else ""
        writer.writerow([code, lesion["id"], visit["label"], visit["captured_at"], state, model,
                         row["title"], *row["metrics"].values()])
    return Response("\ufeff" + content.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="seguimiento.csv"'})


def build_export(identifier, extension, comparison=None):
    if extension not in {"pdf", "mp4"}:
        raise HTTPException(404)
    temp = tempfile.TemporaryDirectory()
    path = Path(temp.name) / f"{'comparacion' if comparison else 'seguimiento'}.{extension}"
    db = store()
    try:
        if comparison:
            export_lesion_pdf(db, identifier, path, comparison_id=comparison["id"],
                              record_ids=[comparison["previous_id"], comparison["current_id"]],
                              detailed=True, include_followup=False)
        elif extension == "pdf":
            export_lesion_pdf(db, identifier, path)
        else:
            export_video(db, db.records(identifier), db.comparisons(identifier), path)
        if comparison:
            archive_document(db, identifier, path, "Informe comparativo", comparison["id"])
        elif extension == "pdf":
            archive_document(db, identifier, path, "Informe de seguimiento")
        else:
            archive_document(db, identifier, path, "Video de seguimiento")
    except Exception:
        temp.cleanup()
        raise
    return FileResponse(path, filename=path.name,
                        background=BackgroundTask(temp.cleanup),
                        headers={"Cache-Control": "no-store"})


router.include_router(records)
