"""Archivo local versionado: personas seudónimas, lesiones, visitas y comparaciones."""

import csv
import hashlib
import json
import sqlite3
import uuid
import shutil
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def readable_comparison_map(path):
    """Check both the file structure and pixels before reusing a saved map."""
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
        return True
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return False


from longitudinal_lifecycle import LifecycleMixin


class LongitudinalStore(LifecycleMixin):
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "history.sqlite3"
        existed = self.db.exists()
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError(
                    "Versión de archivo longitudinal no compatible; no se modificaron sus tablas."
                )
            db.execute(
                "CREATE TABLE IF NOT EXISTS trash(kind TEXT NOT NULL, identifier TEXT NOT NULL, batch TEXT NOT NULL, deleted_at TEXT NOT NULL, PRIMARY KEY(kind,identifier))"
            )
            if version == 2:
                return
            if existed:
                backup = self.root / "backups"
                backup.mkdir(exist_ok=True)
                self.migration_backup = (
                    backup / f"history-before-persons-{uuid.uuid4().hex}.sqlite3"
                )
                with closing(sqlite3.connect(self.migration_backup)) as destination:
                    db.backup(destination)
            db.executescript(
                """
            CREATE TABLE IF NOT EXISTS lesions(
                id TEXT PRIMARY KEY, patient TEXT NOT NULL, name TEXT NOT NULL,
                site TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(patient,name));
            CREATE TABLE IF NOT EXISTS records(
                id TEXT PRIMARY KEY, lesion_id TEXT NOT NULL REFERENCES lesions(id),
                captured_at TEXT NOT NULL, created TEXT NOT NULL, image TEXT NOT NULL,
                mask TEXT NOT NULL, sha256 TEXT NOT NULL, mask_sha256 TEXT NOT NULL,
                metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS comparisons(
                id TEXT PRIMARY KEY, previous_id TEXT NOT NULL REFERENCES records(id),
                current_id TEXT NOT NULL REFERENCES records(id), created TEXT NOT NULL,
                result TEXT NOT NULL, overlay TEXT NOT NULL);
            PRAGMA user_version=1;
            """
            )
            db.execute("BEGIN")
            db.execute(
                """CREATE TABLE persons(
                id TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL, updated TEXT NOT NULL,
                CHECK(length(trim(code)) BETWEEN 1 AND 160))"""
            )
            db.execute(
                "ALTER TABLE lesions ADD COLUMN person_id TEXT REFERENCES persons(id)"
            )
            for row in db.execute("SELECT DISTINCT patient FROM lesions").fetchall():
                identifier, timestamp = uuid.uuid4().hex, now()
                db.execute(
                    "INSERT INTO persons VALUES(?,?,?,?,?,?)",
                    (identifier, row["patient"], "", "", timestamp, timestamp),
                )
                db.execute(
                    "UPDATE lesions SET person_id=? WHERE patient=?",
                    (identifier, row["patient"]),
                )
            db.execute("CREATE INDEX lesions_person_id ON lesions(person_id)")
            for operation in ("INSERT", "UPDATE"):
                db.execute(
                    f"""CREATE TRIGGER lesions_person_{operation.lower()}
                    BEFORE {operation} ON lesions
                    WHEN NEW.person_id IS NULL OR NOT EXISTS(
                        SELECT 1 FROM persons WHERE id=NEW.person_id AND code=NEW.patient)
                    BEGIN SELECT RAISE(ABORT, 'Seleccione una persona existente.'); END"""
                )
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def validate_person(code, name, notes):
        code, name, notes = code.strip(), name.strip(), notes.strip()
        if not code or len(code) > 160 or len(name) > 160 or len(notes) > 2000:
            raise ValueError(
                "Indique un código de hasta 160 caracteres, nombre de hasta 160 y observaciones de hasta 2000."
            )
        return code, name, notes

    def update_visit_notes(self, identifier, notes):
        allowed = {"itch", "bleeding", "pain", "evolution", "sun", "observation", "tags", "author"}
        if set(notes) - allowed or any(not isinstance(v, str) or len(v) > 2000 for v in notes.values()):
            raise ValueError("Notas inválidas: máximo 2000 caracteres por campo.")
        values = {key: value.strip() for key, value in notes.items()}
        for key in ("itch", "bleeding", "pain"):
            if values.get(key, "No registrado") not in ("No registrado", "No", "Sí"):
                raise ValueError("Estado de síntoma inválido.")
        with self.connect() as db:
            row = db.execute("SELECT metadata FROM records WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise ValueError("Visita no encontrada.")
            metadata = json.loads(row["metadata"])
            previous = metadata.get("visit_notes", {})
            metadata["visit_notes"] = values
            metadata.setdefault("visit_audit", []).append(dict(at=now(), author=values.get("author", ""), action="Actualización de notas y etiquetas", previous=previous, current=values))
            db.execute("UPDATE records SET metadata=? WHERE id=?", (dumps(metadata), identifier))

    def create_person(self, code, name="", notes=""):
        code, name, notes = self.validate_person(code, name, notes)
        identifier, timestamp = uuid.uuid4().hex, now()
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO persons VALUES(?,?,?,?,?,?)",
                    (identifier, code, name, notes, timestamp, timestamp),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ya existe una persona con ese código.") from exc
        return identifier

    def persons(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    """SELECT p.*, count(l.id) AS lesion_count
                FROM persons p LEFT JOIN lesions l ON l.person_id=p.id
                GROUP BY p.id ORDER BY p.code"""
                )
            ]

    def person(self, identifier):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM persons WHERE id=?", (identifier,)
            ).fetchone()
        if row is None:
            raise ValueError("Persona inexistente.")
        return dict(row)

    def update_person(self, identifier, code, name="", notes=""):
        code, name, notes = self.validate_person(code, name, notes)
        try:
            with self.connect() as db:
                result = db.execute(
                    "UPDATE persons SET code=?,name=?,notes=?,updated=? WHERE id=?",
                    (code, name, notes, now(), identifier),
                )
                if not result.rowcount:
                    raise ValueError("Persona inexistente.")
                db.execute(
                    "UPDATE lesions SET patient=? WHERE person_id=?", (code, identifier)
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ya existe una persona con ese código.") from exc

    def create_lesion(self, patient, name, site=""):
        """Compatibility entry point for imports using a person code."""
        patient, name, site = patient.strip(), name.strip(), site.strip()
        if not patient or not name or max(len(patient), len(name), len(site)) > 160:
            raise ValueError(
                "Indique código de persona y nombre de lesión (máximo 160 caracteres)."
            )
        with self.connect() as db:
            person = db.execute(
                "SELECT id FROM persons WHERE code=?", (patient,)
            ).fetchone()
        person_id = person["id"] if person else self.create_person(patient)
        return self.create_lesion_for_person(person_id, name, site)

    def create_lesion_for_person(self, person_id, name, site=""):
        name, site = name.strip(), site.strip()
        if not name or max(len(name), len(site)) > 160:
            raise ValueError("Indique nombre de lesión y zona de hasta 160 caracteres.")
        identifier = uuid.uuid4().hex
        try:
            with self.connect() as db:
                person = db.execute(
                    "SELECT code FROM persons WHERE id=?", (person_id,)
                ).fetchone()
                if person is None:
                    raise ValueError("Seleccione una persona existente.")
                db.execute(
                    "INSERT INTO lesions(id,patient,name,site,created,person_id) VALUES(?,?,?,?,?,?)",
                    (identifier, person["code"], name, site, now(), person_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Esa lesión ya existe para esta persona.") from exc
        return identifier

    def lesions(self, person_id=None):
        with self.connect() as db:
            if person_id is not None:
                return [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM lesions WHERE person_id=? ORDER BY name",
                        (person_id,),
                    )
                ]
            return [
                dict(r)
                for r in db.execute("SELECT * FROM lesions ORDER BY patient,name")
            ]

    def records(self, lesion_id):
        with self.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT * FROM records WHERE lesion_id=? AND id NOT IN (SELECT identifier FROM trash WHERE kind='record') ORDER BY captured_at,created,id""",
                    (lesion_id,),
                )
            ]
        for index, row in enumerate(rows):
            row["label"] = f"T{index}"
            row["metadata"] = json.loads(row["metadata"])
        return rows

    def record(self, identifier):
        with self.connect() as db:
            row = db.execute(
                """SELECT * FROM records WHERE id=? AND id NOT IN
                (SELECT identifier FROM trash WHERE kind='record')""",
                (identifier,),
            ).fetchone()
        if row is None:
            raise ValueError("Registro inexistente.")
        row = dict(row)
        row["metadata"] = json.loads(row["metadata"])
        return row

    def path(self, relative):
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("Ruta fuera del archivo de seguimiento.")
        return target

    def add_record(
        self,
        lesion_id,
        captured_at,
        image,
        mask,
        metadata,
        analysis=None,
        explanation=None,
    ):
        # Las fechas representan hora local de adquisición, sin inferirlas del archivo.
        try:
            date = datetime.fromisoformat(captured_at.strip())
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                "Indique una fecha válida en formato AAAA-MM-DD o AAAA-MM-DD HH:MM:SS."
            ) from exc
        if date.tzinfo is not None:
            raise ValueError("Use fecha y hora locales, sin zona horaria.")
        captured_at = date.isoformat(timespec="seconds")
        image = ImageOps.exif_transpose(image).convert("RGB")
        mask_array = np.asarray(mask.convert("L")) > 0
        if mask.size != image.size or mask_array.sum() < 25 or mask_array.mean() > 0.85:
            raise ValueError(
                "Revise el contorno: debe incluir la lesión y dejar piel alrededor."
            )
        if metadata.get("mask_reviewed") is not True:
            raise ValueError("Debe revisar y confirmar el contorno antes de guardarlo.")
        with self.connect() as db:
            if (
                db.execute("SELECT id FROM lesions WHERE id=?", (lesion_id,)).fetchone()
                is None
            ):
                raise ValueError("Seleccione una lesión existente.")
        metadata_text = dumps(metadata)
        identifier = uuid.uuid4().hex
        folder = self.root / "records" / identifier
        folder.mkdir(parents=True)
        photo, contour = folder / "image.png", folder / "mask.png"
        try:
            image.save(photo)
            Image.fromarray(mask_array.astype("uint8") * 255).save(contour)
            image_hash = hashlib.sha256(photo.read_bytes()).hexdigest()
            mask_hash = hashlib.sha256(contour.read_bytes()).hexdigest()
            if analysis is not None:
                classification = dict(
                    analysis,
                    analyzed_at=now(),
                    image_sha256=image_hash,
                    mask_sha256=mask_hash,
                )
                if explanation is not None:
                    explanation_path = folder / "analyses" / "initial.png"
                    explanation_path.parent.mkdir()
                    explanation.convert("RGB").save(explanation_path)
                    classification["explanation"] = dict(
                        path=explanation_path.relative_to(self.root).as_posix(),
                        sha256=hashlib.sha256(
                            explanation_path.read_bytes()
                        ).hexdigest(),
                        method=classification.get("explanation_diagnostics", {}).get(
                            "method", "occlusion"
                        ),
                    )
                metadata_text = dumps(dict(metadata, classification=classification))
            with self.connect() as db:
                db.execute(
                    "INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        lesion_id,
                        captured_at,
                        now(),
                        photo.relative_to(self.root).as_posix(),
                        contour.relative_to(self.root).as_posix(),
                        image_hash,
                        mask_hash,
                        metadata_text,
                    ),
                )
        except Exception:
            shutil.rmtree(folder)
            raise
        return identifier

    def load_images(self, row):
        images = []
        for key, hash_key in [("image", "sha256"), ("mask", "mask_sha256")]:
            path = self.path(row[key])
            if hashlib.sha256(path.read_bytes()).hexdigest() != row[hash_key]:
                raise ValueError(
                    "Una imagen guardada cambió: no se puede reproducir la comparación."
                )
            with Image.open(path) as im:
                images.append(im.convert("RGB" if key == "image" else "L"))
        return images

    def update_record_date(self, identifier, captured_at):
        try:
            date = datetime.fromisoformat(captured_at.strip())
        except (ValueError, AttributeError) as exc:
            raise ValueError("Indique una fecha válida: AAAA-MM-DD HH:MM:SS.") from exc
        if date.tzinfo is not None:
            raise ValueError("Use fecha y hora locales, sin zona horaria.")
        captured_at = date.isoformat(timespec="seconds")
        with self.connect() as db:
            row = db.execute(
                "SELECT captured_at,metadata FROM records WHERE id=?", (identifier,)
            ).fetchone()
            if row is None:
                raise ValueError("Registro inexistente.")
            if row["captured_at"] == captured_at:
                return captured_at
            metadata = json.loads(row["metadata"])
            metadata.setdefault("date_corrections", []).append(
                dict(previous=row["captured_at"], current=captured_at, edited_at=now())
            )
            db.execute(
                "UPDATE records SET captured_at=?,metadata=? WHERE id=?",
                (captured_at, dumps(metadata), identifier),
            )
        return captured_at

    def save_record_analysis(self, identifier, classification, explanation=None):
        """Save a prediction snapshot without changing acquisition metadata."""
        record = self.record(identifier)
        analysis = dict(classification)
        analysis.update(
            analyzed_at=now(),
            image_sha256=record["sha256"],
            mask_sha256=record["mask_sha256"],
        )
        photo = None
        try:
            if explanation is not None:
                folder = self.root / "records" / identifier / "analyses"
                folder.mkdir(parents=True, exist_ok=True)
                photo = folder / f"{uuid.uuid4().hex}.png"
                explanation.convert("RGB").save(photo)
                analysis["explanation"] = dict(
                    path=photo.relative_to(self.root).as_posix(),
                    sha256=hashlib.sha256(photo.read_bytes()).hexdigest(),
                    method=analysis.get("explanation_diagnostics", {}).get(
                        "method", "occlusion"
                    ),
                )
            with self.connect() as db:
                row = db.execute(
                    "SELECT metadata FROM records WHERE id=?", (identifier,)
                ).fetchone()
                if row is None:
                    raise ValueError("Registro inexistente.")
                metadata = json.loads(row["metadata"])
                metadata["classification"] = analysis
                db.execute(
                    "UPDATE records SET metadata=? WHERE id=?",
                    (dumps(metadata), identifier),
                )
        except Exception:
            if photo is not None:
                photo.unlink(missing_ok=True)
            raise
        return analysis

    def load_explanation(self, identifier, analysis=None):
        record = self.record(identifier)
        self.load_images(record)
        analysis = analysis or record["metadata"].get("classification", {})
        artifact = analysis.get("explanation")
        if not artifact:
            raise ValueError("Esta visita no tiene una explicación visual guardada.")
        if analysis.get("image_sha256") != record["sha256"]:
            raise ValueError(
                "La explicación no corresponde a la imagen de esta visita."
            )
        path = self.path(artifact["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError(
                "La explicación guardada cambió; vuelva a clasificar la visita."
            )
        with Image.open(path) as image:
            return image.convert("RGB")

    def pair(self, previous_id, current_id, mode="longitudinal"):
        previous, current = self.record(previous_id), self.record(current_id)
        if mode not in ("longitudinal", "visual"):
            raise ValueError("Modo de comparación no válido.")
        if previous_id == current_id or (
            mode == "longitudinal" and previous["lesion_id"] != current["lesion_id"]
        ):
            raise ValueError("Seleccione dos registros diferentes de la misma lesión.")
        if mode == "longitudinal" and previous["captured_at"] >= current["captured_at"]:
            raise ValueError("La fecha anterior debe preceder a la actual.")
        return previous, current

    def save_comparison(self, previous_id, current_id, result, overlay):
        self.pair(previous_id, current_id, result.get("mode", "longitudinal"))

        # Reuse identical computations rather than duplicate timeline points.
        def stable(value):
            if isinstance(value, dict):
                return {
                    k: stable(v)
                    for k, v in value.items()
                    if k not in ("analyzed_at", "explanation")
                }
            if isinstance(value, list):
                return [stable(v) for v in value]
            return value

        with self.connect() as db:
            candidates = db.execute(
                """SELECT id,result,overlay FROM comparisons WHERE previous_id=? AND current_id=?
                AND id NOT IN (SELECT identifier FROM trash WHERE kind='comparison') ORDER BY created DESC""",
                (previous_id, current_id),
            ).fetchall()
        for row in candidates:
            if stable(json.loads(row["result"])) == stable(result):
                # The computation still matches, but its derived files may have
                # disappeared or become unreadable. Repair them without adding
                # another comparison or changing the historical result.
                photo = self.path(row["overlay"])
                if not readable_comparison_map(photo):
                    photo.parent.mkdir(parents=True, exist_ok=True)
                    temporary = photo.with_name(f".{photo.name}.{uuid.uuid4().hex}.tmp")
                    try:
                        overlay.save(temporary, format="PNG")
                        temporary.replace(photo)
                    finally:
                        temporary.unlink(missing_ok=True)
                report = self.root / "comparisons" / f"{row['id']}.json"
                try:
                    report_valid = json.loads(
                        report.read_text(encoding="utf-8")
                    ) == json.loads(row["result"])
                except (OSError, ValueError):
                    report_valid = False
                if not report_valid:
                    report.parent.mkdir(parents=True, exist_ok=True)
                    temporary = report.with_name(
                        f".{report.name}.{uuid.uuid4().hex}.tmp"
                    )
                    try:
                        temporary.write_text(row["result"], encoding="utf-8")
                        temporary.replace(report)
                    finally:
                        temporary.unlink(missing_ok=True)
                return row["id"]
        identifier = uuid.uuid4().hex
        folder = self.root / "comparisons"
        folder.mkdir(exist_ok=True)
        photo, report = folder / f"{identifier}.png", folder / f"{identifier}.json"
        text = dumps(result)
        try:
            overlay.save(photo)
            report.write_text(text, encoding="utf-8")
            with self.connect() as db:
                db.execute(
                    "INSERT INTO comparisons VALUES(?,?,?,?,?,?)",
                    (
                        identifier,
                        previous_id,
                        current_id,
                        now(),
                        text,
                        photo.relative_to(self.root).as_posix(),
                    ),
                )
        except Exception:
            photo.unlink(missing_ok=True)
            report.unlink(missing_ok=True)
            raise
        return identifier

    def comparisons(self, lesion_id):
        with self.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT c.*,p.captured_at AS live_previous_date,r.captured_at AS live_current_date FROM comparisons c
                JOIN records r ON r.id=c.current_id JOIN records p ON p.id=c.previous_id
                WHERE r.lesion_id=? AND c.id NOT IN (SELECT identifier FROM trash WHERE kind='comparison') AND r.id NOT IN (SELECT identifier FROM trash WHERE kind='record') AND p.id NOT IN (SELECT identifier FROM trash WHERE kind='record') ORDER BY c.created""",
                    (lesion_id,),
                )
            ]
        for row in rows:
            row["result"] = json.loads(row["result"])
            row["stale_dates"] = row["result"].get("mode") != "visual" and (
                row["result"].get("previous_date") != row["live_previous_date"]
                or row["result"].get("current_date") != row["live_current_date"]
            )
        return rows

    def export(self, destination):
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        record_rows, pair_rows = [], []
        for lesion in self.lesions():
            for record in self.records(lesion["id"]):
                record_rows.append(
                    dict(
                        patient_id=lesion["patient"],
                        lesion_id=lesion["id"],
                        record_id=record["id"],
                        timepoint=record["label"],
                        captured_at=record["captured_at"],
                        image=str(self.path(record["image"])),
                        mask=str(self.path(record["mask"])),
                        image_sha256=record["sha256"],
                        mask_sha256=record["mask_sha256"],
                        metadata_json=dumps(record["metadata"]),
                        reference_diagnosis="",
                        split="",
                    )
                )
            for comparison in self.comparisons(lesion["id"]):
                result = comparison["result"]
                pair_rows.append(
                    dict(
                        patient_id=lesion["patient"],
                        lesion_id=lesion["id"],
                        comparison_id=comparison["id"],
                        previous_id=comparison["previous_id"],
                        current_id=comparison["current_id"],
                        comparable=result["comparable"]
                        and not comparison["stale_dates"],
                        requires_recalculation=comparison["stale_dates"],
                        mode=result.get("mode", "longitudinal"),
                        visual_index=result.get("visual_index"),
                        model_a_score=result.get("current_classification", {}).get(
                            "score"
                        ),
                        change_index=(
                            None
                            if comparison["stale_dates"]
                            else result.get("change_index")
                        ),
                        model_b_trained=False,
                        reference_diagnosis="",
                        split="",
                        result_json=dumps(result),
                    )
                )
        for name, rows, fields in [
            (
                "records.csv",
                record_rows,
                [
                    "patient_id",
                    "lesion_id",
                    "record_id",
                    "timepoint",
                    "captured_at",
                    "image",
                    "mask",
                    "image_sha256",
                    "mask_sha256",
                    "metadata_json",
                    "reference_diagnosis",
                    "split",
                ],
            ),
            (
                "pairs.csv",
                pair_rows,
                [
                    "patient_id",
                    "lesion_id",
                    "comparison_id",
                    "previous_id",
                    "current_id",
                    "comparable",
                    "requires_recalculation",
                    "mode",
                    "visual_index",
                    "model_a_score",
                    "change_index",
                    "model_b_trained",
                    "reference_diagnosis",
                    "split",
                    "result_json",
                ],
            ),
        ]:
            with (destination / name).open(
                "w", newline="", encoding="utf-8-sig"
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        (destination / "README.txt").write_text(
            "Exportación de investigación DermaVision-X longitudinal-v1.\n"
            "Rutas absolutas locales; las fotos no se copian. Los CSV incluyen códigos de persona.\n"
            "Model A: puntuación estática. Model B: características temporales, todavía sin modelo entrenado.\n"
            "Diagnóstico de referencia y partición vacíos deliberadamente: no usar predicciones como etiquetas.\n"
            "Separar por paciente; conservar todas sus lesiones y fechas en la misma partición.\n"
            "Usar solo información disponible hasta la fecha actual; evaluar ambos modelos en los mismos casos.\n",
            encoding="utf-8",
        )
        return len(record_rows), len(pair_rows)
