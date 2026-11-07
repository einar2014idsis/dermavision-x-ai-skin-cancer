"""Papelera reversible y respaldos portables con verificación de integridad."""

import hashlib
import json
import sqlite3
import tempfile
import uuid
import zipfile
import shutil
from pathlib import Path
from contextlib import closing
from datetime import datetime, timezone


class LifecycleMixin:
    def trash_items(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    """
                SELECT t.*, COALESCE(r.captured_at,c.created) AS description
                FROM trash t LEFT JOIN records r ON t.kind='record' AND r.id=t.identifier
                LEFT JOIN comparisons c ON t.kind='comparison' AND c.id=t.identifier
                ORDER BY deleted_at DESC"""
                )
            ]

    def move_to_trash(self, kind, identifier=None, lesion_id=None):
        batch = uuid.uuid4().hex
        timestamp = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            if kind == "record":
                if not db.execute(
                    "SELECT 1 FROM records WHERE id=?", (identifier,)
                ).fetchone():
                    raise ValueError("Fotografía inexistente.")
                items = [("record", identifier)]
                items += [
                    ("comparison", r[0])
                    for r in db.execute(
                        "SELECT id FROM comparisons WHERE previous_id=? OR current_id=?",
                        (identifier, identifier),
                    )
                ]
            elif kind == "comparison":
                if not db.execute(
                    "SELECT 1 FROM comparisons WHERE id=?", (identifier,)
                ).fetchone():
                    raise ValueError("Comparación inexistente.")
                items = [("comparison", identifier)]
            elif kind == "history":
                items = [
                    ("comparison", r[0])
                    for r in db.execute(
                        "SELECT c.id FROM comparisons c JOIN records r ON c.current_id=r.id WHERE r.lesion_id=?",
                        (lesion_id,),
                    )
                ]
            else:
                raise ValueError("Operación de papelera no válida.")
            count = 0
            for item_kind, item_id in items:
                count += db.execute(
                    "INSERT OR IGNORE INTO trash VALUES(?,?,?,?)",
                    (item_kind, item_id, batch, timestamp),
                ).rowcount
        return count

    def restore_trash(self, kind, identifier):
        with self.connect() as db:
            row = db.execute(
                "SELECT batch FROM trash WHERE kind=? AND identifier=?",
                (kind, identifier),
            ).fetchone()
            if row is None:
                raise ValueError("Elemento no disponible en la papelera.")
            if kind == "record":
                db.execute("DELETE FROM trash WHERE batch=?", (row[0],))
            else:
                c = db.execute(
                    "SELECT previous_id,current_id FROM comparisons WHERE id=?",
                    (identifier,),
                ).fetchone()
                if (
                    not c
                    or db.execute(
                        "SELECT 1 FROM trash WHERE kind='record' AND identifier IN (?,?)",
                        tuple(c),
                    ).fetchone()
                ):
                    raise ValueError(
                        "Restaure primero las fotografías de esta comparación."
                    )
                db.execute(
                    "DELETE FROM trash WHERE kind=? AND identifier=?",
                    (kind, identifier),
                )

    def purge_preview(self, kind, identifier):
        with self.connect() as db:
            if not db.execute(
                "SELECT 1 FROM trash WHERE kind=? AND identifier=?", (kind, identifier)
            ).fetchone():
                raise ValueError(
                    "Solo se pueden borrar definitivamente elementos de la papelera."
                )
            ids = (
                [identifier]
                if kind == "comparison"
                else [
                    r[0]
                    for r in db.execute(
                        "SELECT id FROM comparisons WHERE previous_id=? OR current_id=?",
                        (identifier, identifier),
                    )
                ]
            )
            files = []
            if kind == "record":
                record = db.execute(
                    "SELECT image FROM records WHERE id=?", (identifier,)
                ).fetchone()
                folder = self.path(record[0]).parent
                files += [p for p in folder.rglob("*") if p.is_file()]
            for cid in ids:
                row = db.execute(
                    "SELECT overlay FROM comparisons WHERE id=?", (cid,)
                ).fetchone()
                if row:
                    files += [self.path(row[0]), self.path(row[0]).with_suffix(".json")]
        return ids, list(dict.fromkeys(files))

    def purge_trash(self, kind, identifier):
        ids, files = self.purge_preview(kind, identifier)
        # Stage files before transaction; recover them if a database operation fails.
        with tempfile.TemporaryDirectory(dir=self.root, prefix=".purge-") as stage:
            moved = []
            try:
                for i, path in enumerate(files):
                    if path.exists():
                        target = Path(stage) / str(i)
                        path.replace(target)
                        moved.append((path, target))
                with self.connect() as db:
                    for cid in ids:
                        db.execute("DELETE FROM comparisons WHERE id=?", (cid,))
                        db.execute(
                            "DELETE FROM trash WHERE kind='comparison' AND identifier=?",
                            (cid,),
                        )
                    if kind == "record":
                        db.execute("DELETE FROM records WHERE id=?", (identifier,))
                        db.execute(
                            "DELETE FROM trash WHERE kind='record' AND identifier=?",
                            (identifier,),
                        )
            except Exception:
                for path, target in moved:
                    target.replace(path)
                raise

    def backup(self, destination):
        destination = Path(destination).resolve()
        if destination.is_relative_to(self.root):
            raise ValueError("Guarde el respaldo fuera de la carpeta de datos.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "history.sqlite3"
            with self.connect() as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
            files = {"history.sqlite3": snapshot}
            for folder in ("records", "comparisons"):
                for path in (self.root / folder).rglob("*"):
                    if path.is_file():
                        if path.is_symlink():
                            raise ValueError(
                                "No se permiten enlaces en el archivo local."
                            )
                        files[path.relative_to(self.root).as_posix()] = path
            manifest = {
                "format": "dermavision-backup-v1",
                "created": datetime.now(timezone.utc).isoformat(),
                "files": {
                    name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for name, path in files.items()
                },
            }
            temp = destination.with_name(
                destination.name + "." + uuid.uuid4().hex + ".tmp"
            )
            try:
                with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                    for name, path in files.items():
                        archive.write(path, name)
                    archive.writestr("manifest.json", json.dumps(manifest))
                self.validate_backup(temp)
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
        return destination

    @staticmethod
    def validate_backup(source):
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Respaldo con entradas duplicadas.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != "dermavision-backup-v1":
                raise ValueError("Formato de respaldo no compatible.")
            if set(names) != set(manifest["files"]) | {"manifest.json"}:
                raise ValueError("Inventario de respaldo incompleto.")
            for name, digest in manifest["files"].items():
                path = Path(name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or ":" in name
                    or "\\" in name
                ):
                    raise ValueError("Ruta de respaldo no segura.")
                if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                    raise ValueError("Respaldo dañado: " + name)
            if "history.sqlite3" not in manifest["files"]:
                raise ValueError("Falta la base de datos.")
        return manifest

    def restore_backup(self, source):
        manifest = self.validate_backup(source)
        with tempfile.TemporaryDirectory(
            dir=self.root.parent, prefix="restore-"
        ) as tmp:
            stage = Path(tmp) / "new"
            stage.mkdir()
            with zipfile.ZipFile(source) as archive:
                for name in manifest["files"]:
                    target = stage / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
            with closing(sqlite3.connect(stage / "history.sqlite3")) as db:
                if (
                    db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or db.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise ValueError(
                        "La base del respaldo no supera la verificación de integridad."
                    )
                if db.execute("PRAGMA user_version").fetchone()[0] != 2:
                    raise ValueError("Versión de respaldo incompatible.")
                for table, columns in [
                    ("persons", "id,code,name,notes,created,updated"),
                    ("lesions", "id,patient,name,site,created,person_id"),
                    (
                        "records",
                        "id,lesion_id,captured_at,created,image,mask,sha256,mask_sha256,metadata",
                    ),
                    ("comparisons", "id,previous_id,current_id,created,result,overlay"),
                    ("trash", "kind,identifier,batch,deleted_at"),
                ]:
                    db.execute(f"SELECT {columns} FROM {table} LIMIT 0")
                for image, mask, ih, mh in db.execute(
                    "SELECT image,mask,sha256,mask_sha256 FROM records"
                ):
                    for name, digest in ((image, ih), (mask, mh)):
                        if (
                            name not in manifest["files"]
                            or manifest["files"][name] != digest
                        ):
                            raise ValueError(
                                "Falta una fotografía o contorno verificado."
                            )
                for overlay, result in db.execute(
                    "SELECT overlay,result FROM comparisons"
                ):
                    if (
                        overlay not in manifest["files"]
                        or Path(overlay).with_suffix(".json").as_posix()
                        not in manifest["files"]
                    ):
                        raise ValueError("Falta un mapa o resultado de comparación.")
                for (metadata,) in db.execute("SELECT metadata FROM records"):
                    explanation = (
                        json.loads(metadata)
                        .get("classification", {})
                        .get("explanation")
                    )
                    if (
                        explanation
                        and manifest["files"].get(explanation["path"])
                        != explanation["sha256"]
                    ):
                        raise ValueError("Falta una explicación visual verificada.")
            # Recovery ZIP is retained beside the data, never overwriting the source.
            recovery = self.root.parent / (
                "respaldo-antes-restauracion-" + uuid.uuid4().hex + ".zip"
            )
            self.backup(recovery)
            old = Path(tmp) / "old"
            old.mkdir()
            moved = []
            installed = []
            try:
                for name in ("history.sqlite3", "records", "comparisons"):
                    target = self.root / name
                    if target.exists():
                        target.replace(old / name)
                        moved.append(name)
                    if (stage / name).exists():
                        (stage / name).replace(target)
                        installed.append(name)
            except Exception:
                for name in installed:
                    target = self.root / name
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink(missing_ok=True)
                for name in moved:
                    (old / name).replace(self.root / name)
                raise
        return recovery
