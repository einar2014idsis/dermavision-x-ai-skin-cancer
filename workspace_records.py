"""Additional workspace metadata and documents for the existing local archive."""
from contextlib import closing
import hashlib
import shutil
import sqlite3
from threading import Lock
import uuid

from longitudinal_store import now
from longitudinal_reports import report_photo_state

_schema_lock = Lock()


def ensure_workspace(db):
    with _schema_lock, db.connect() as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_lesion_locations'").fetchone():
            return
        folder = db.root.parent / "backups"
        folder.mkdir(exist_ok=True)
        snapshot = folder / f"history-before-workspace-{uuid.uuid4().hex}.sqlite3"
        try:
            with closing(sqlite3.connect(snapshot)) as backup:
                conn.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or backup.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("No se pudo verificar el respaldo previo del historial.")
        except Exception:
            snapshot.unlink(missing_ok=True)
            raise
        conn.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS workspace_lesions(
                lesion_id TEXT PRIMARY KEY REFERENCES lesions(id),
                registered_on TEXT NOT NULL, description TEXT NOT NULL, notes TEXT NOT NULL,
                body_view TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workspace_admin_activity(
                id INTEGER PRIMARY KEY, created TEXT NOT NULL, action TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workspace_documents(
                id TEXT PRIMARY KEY, lesion_id TEXT NOT NULL REFERENCES lesions(id),
                title TEXT NOT NULL, created TEXT NOT NULL, format TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, comparison_id TEXT);
            CREATE TABLE IF NOT EXISTS workspace_lesion_locations(
                lesion_id TEXT PRIMARY KEY REFERENCES workspace_lesions(lesion_id),
                region_id TEXT NOT NULL,
                marker_x REAL NOT NULL CHECK(marker_x BETWEEN 0 AND 1),
                marker_y REAL NOT NULL CHECK(marker_y BETWEEN 0 AND 1),
                origin TEXT NOT NULL CHECK(origin IN ('manual', 'default')));
            CREATE INDEX IF NOT EXISTS workspace_documents_lesion ON workspace_documents(lesion_id,created);
            COMMIT;
        """)


def lesion_summary(db, person_id):
    ensure_workspace(db)
    db.person(person_id)
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT l.id,l.name,l.site,l.created,l.person_id,
                   d.registered_on,d.description,d.notes,d.body_view,
                   m.region_id,m.marker_x,m.marker_y,m.origin,
                   count(r.id) AS visits,max(r.captured_at) AS latest
            FROM lesions AS l LEFT JOIN workspace_lesions AS d ON d.lesion_id=l.id
            LEFT JOIN workspace_lesion_locations AS m ON m.lesion_id=l.id
            LEFT JOIN records AS r ON r.lesion_id=l.id AND NOT EXISTS
                (SELECT 1 FROM trash WHERE kind='record' AND identifier=r.id)
            WHERE l.person_id=? GROUP BY l.id ORDER BY l.name
        """, (person_id,))
        items = []
        for row in rows:
            item = dict(row)
            marker = dict(region_id=item.pop("region_id"), x=item.pop("marker_x"),
                          y=item.pop("marker_y"), origin=item.pop("origin"))
            item["location"] = marker if marker["region_id"] else None
            items.append(item)
        return items


def patient_visits(db, person_id):
    rows = []
    for lesion in db.lesions(person_id):
        for visit in db.records(lesion["id"]):
            snapshot = visit["metadata"].get("classification") or {}
            status, _, _ = report_photo_state(visit)
            if status == "Requiere actualizarse":
                snapshot = {"state": "stale"}
            rows.append(dict(id=visit["id"], lesion_id=lesion["id"], lesion=lesion["name"],
                             site=lesion["site"], label=visit["label"], captured_at=visit["captured_at"],
                             classification={k: snapshot.get(k) for k in ("state", "label", "score")},
                             observations=(visit["metadata"].get("visit_notes") or {}).get("observation")
                             or visit["metadata"].get("notes", "")))
    return sorted(rows, key=lambda row: (row["captured_at"], row["id"]), reverse=True)


def dashboard(db):
    ensure_workspace(db)
    with db.connect() as conn:
        metrics = dict(conn.execute("""
            WITH active AS (SELECT r.* FROM records r WHERE NOT EXISTS
                (SELECT 1 FROM trash WHERE kind='record' AND identifier=r.id))
            SELECT (SELECT count(*) FROM persons) AS patients,
                   (SELECT count(*) FROM lesions) AS lesions,
                   (SELECT count(*) FROM active WHERE json_extract(metadata,'$.classification.analyzed_at') IS NOT NULL) AS analyses,
                   (SELECT count(*) FROM (SELECT lesion_id FROM active GROUP BY lesion_id HAVING count(*)>=2)) AS followups
        """).fetchone())
        rows = conn.execute("""
            WITH active AS (SELECT r.* FROM records r WHERE NOT EXISTS
                (SELECT 1 FROM trash WHERE kind='record' AND identifier=r.id)),
            activity AS (
                SELECT created AS at,id AS person_id,NULL AS lesion_id,NULL AS visit_id,NULL AS item,'patient' AS kind,'Registrado' AS state FROM persons
                UNION ALL SELECT created,person_id,id,NULL,NULL,'lesion','Registrada' FROM lesions
                UNION ALL SELECT r.created,l.person_id,l.id,r.id,NULL,'visit','Registrada' FROM active r JOIN lesions l ON l.id=r.lesion_id
                UNION ALL SELECT json_extract(r.metadata,'$.classification.analyzed_at'),l.person_id,l.id,r.id,NULL,'analysis',
                  CASE json_extract(r.metadata,'$.classification.state') WHEN 'accepted' THEN 'Completado'
                    WHEN 'uncertain' THEN 'No concluyente' ELSE 'Requiere revisión' END
                  FROM active r JOIN lesions l ON l.id=r.lesion_id
                  WHERE json_extract(r.metadata,'$.classification.analyzed_at') IS NOT NULL
                UNION ALL SELECT c.created,l.person_id,l.id,NULL,c.id,'comparison','Guardada'
                  FROM comparisons c JOIN active r ON r.id=c.current_id JOIN active a ON a.id=c.previous_id
                  JOIN lesions l ON l.id=r.lesion_id WHERE NOT EXISTS
                    (SELECT 1 FROM trash WHERE kind='comparison' AND identifier=c.id)
                UNION ALL SELECT d.created,l.person_id,l.id,NULL,d.id,'document','Disponible'
                  FROM workspace_documents d JOIN lesions l ON l.id=d.lesion_id
            )
            SELECT a.*,p.code,l.name AS lesion FROM activity a JOIN persons p ON p.id=a.person_id
            LEFT JOIN lesions l ON l.id=a.lesion_id ORDER BY a.at DESC,a.kind,a.item LIMIT 30
        """)
        return {"metrics": metrics, "activity": [dict(row) for row in rows]}


def documents(db, person_id):
    ensure_workspace(db)
    with db.connect() as conn:
        rows = conn.execute("""
            SELECT d.id,d.lesion_id,l.name AS lesion,d.title,d.created,d.format,d.comparison_id
            FROM workspace_documents d JOIN lesions l ON l.id=d.lesion_id
            WHERE l.person_id=? ORDER BY d.created DESC,d.id
        """, (person_id,))
        return [dict(row) for row in rows]


def archive_document(db, identifier, source, title, comparison_id=None):
    ensure_workspace(db)
    key = uuid.uuid4().hex
    extension = source.suffix.lower()
    folder = db.root / "documents"
    folder.mkdir(exist_ok=True)
    target = folder / (key + extension)
    try:
        shutil.copyfile(source, target)
        with target.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            duplicate = conn.execute("""
                SELECT id FROM workspace_documents
                WHERE lesion_id=? AND format=? AND comparison_id IS ? AND sha256=?
            """, (identifier, extension[1:], comparison_id, digest)).fetchone()
            if duplicate:
                target.unlink()
                return duplicate["id"]
            conn.execute("INSERT INTO workspace_documents VALUES(?,?,?,?,?,?,?,?)",
                         (key, identifier, title, now(), extension[1:], target.relative_to(db.root).as_posix(),
                          digest, comparison_id))
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return key


def document_file(db, person_id, key):
    ensure_workspace(db)
    with db.connect() as conn:
        entry = conn.execute("""
            SELECT d.* FROM workspace_documents d JOIN lesions l ON l.id=d.lesion_id
            WHERE d.id=? AND l.person_id=?
        """, (key, person_id)).fetchone()
    if entry is None:
        raise ValueError("Documento inexistente para este paciente.")
    path = db.path(entry["path"])
    try:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise ValueError("El archivo del documento no está disponible.") from exc
    if digest != entry["sha256"]:
        raise ValueError("El archivo no coincide con el documento registrado.")
    return path, f'{entry["title"]}.{entry["format"]}'
