"""Persistence and upgrade checks for people and linked lesions."""

from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path
from longitudinal_store import LongitudinalStore


class PersonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_person_without_lesions_survives_reopen(self):
        identifier = self.store.create_person(" P01 ", "Persona prueba", "Nota")
        reopened = LongitudinalStore(self.temp.name)
        self.assertEqual(reopened.person(identifier)["code"], "P01")
        self.assertEqual(reopened.persons()[0]["lesion_count"], 0)
        self.assertEqual(reopened.lesions(identifier), [])
        self.assertFalse((Path(self.temp.name) / "backups").exists())

    def test_rename_keeps_lesion_and_visits(self):
        person = self.store.create_person("P01")
        lesion = self.store.create_lesion_for_person(person, "L01", "Brazo")
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    "record",
                    lesion,
                    "2026-01-01",
                    "created",
                    "photo",
                    "mask",
                    "sha",
                    "masksha",
                    "{}",
                ),
            )
        self.store.update_person(person, "P02", "Nombre", "Nota")
        reopened = LongitudinalStore(self.temp.name)
        self.assertEqual(reopened.lesions(person)[0]["id"], lesion)
        self.assertEqual(reopened.lesions(person)[0]["patient"], "P02")
        self.assertEqual(reopened.records(lesion)[0]["id"], "record")
        self.assertEqual(reopened.persons()[0]["lesion_count"], 1)

    def test_invalid_and_duplicate_people_and_lesions(self):
        first = self.store.create_person("P01")
        self.store.create_person("P02")
        lesion = self.store.create_lesion_for_person(first, "L01")
        for code in ("", " ", "x" * 161, "P01"):
            with self.assertRaises(ValueError):
                self.store.create_person(code)
        with self.assertRaises(ValueError):
            self.store.update_person(first, "P02")
        self.assertEqual(self.store.person(first)["code"], "P01")
        self.assertEqual(self.store.lesions(first)[0]["id"], lesion)
        with self.assertRaises(ValueError):
            self.store.create_lesion_for_person("missing", "L01")
        with self.assertRaises(ValueError):
            self.store.create_lesion_for_person(first, "L01")
        with self.assertRaises(ValueError):
            self.store.create_lesion_for_person(first, " ")
        other = self.store.persons()[1]["id"]
        self.store.create_lesion_for_person(other, "L01")
        self.assertEqual(len(self.store.lesions(first)), 1)

    def test_database_rejects_orphan_lesions_and_person_delete(self):
        person = self.store.create_person("P01")
        self.store.create_lesion_for_person(person, "L01")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO lesions VALUES(?,?,?,?,?,?)",
                    ("orphan", "P01", "L02", "", "created", None),
                )
        with self.assertRaises(sqlite3.IntegrityError):
            with self.store.connect() as db:
                db.execute("DELETE FROM persons WHERE id=?", (person,))
        with self.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_preserves_old_data_and_creates_backup(self):
        # Reconstruct exactly the old schema in a separate archive.
        with tempfile.TemporaryDirectory() as legacy:
            path = Path(legacy) / "history.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(
                    """
                    CREATE TABLE lesions(id TEXT PRIMARY KEY, patient TEXT NOT NULL,
                        name TEXT NOT NULL, site TEXT NOT NULL, created TEXT NOT NULL,
                        UNIQUE(patient,name));
                    CREATE TABLE records(id TEXT PRIMARY KEY, lesion_id TEXT NOT NULL REFERENCES lesions(id),
                        captured_at TEXT NOT NULL, created TEXT NOT NULL, image TEXT NOT NULL,
                        mask TEXT NOT NULL, sha256 TEXT NOT NULL, mask_sha256 TEXT NOT NULL,
                        metadata TEXT NOT NULL);
                    CREATE TABLE comparisons(id TEXT PRIMARY KEY, previous_id TEXT NOT NULL REFERENCES records(id),
                        current_id TEXT NOT NULL REFERENCES records(id), created TEXT NOT NULL,
                        result TEXT NOT NULL, overlay TEXT NOT NULL);
                    INSERT INTO lesions VALUES('l1','P01','L01','Brazo','created'),
                        ('l2','P01','L02','Pierna','created'),('l3','P02','L01','','created');
                    INSERT INTO records VALUES('r1','l1','2026-01-01','created','photo1','mask1','sha1','msha1','{}'),
                        ('r2','l1','2026-02-01','created','photo2','mask2','sha2','msha2','{}');
                    INSERT INTO comparisons VALUES('c1','r1','r2','created','{}','overlay');
                    PRAGMA user_version=1;
                """
                )
                originals = {
                    table: db.execute("SELECT * FROM " + table).fetchall()
                    for table in ("lesions", "records", "comparisons")
                }
            migrated = LongitudinalStore(legacy)
            self.assertEqual(len(migrated.persons()), 2)
            self.assertEqual(migrated.persons()[0]["lesion_count"], 2)
            self.assertTrue(migrated.migration_backup.exists())
            with migrated.connect() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                for table in originals:
                    rows = [tuple(r) for r in db.execute("SELECT * FROM " + table)]
                    if table == "lesions":
                        rows = [r[:5] for r in rows]
                    self.assertEqual(rows, originals[table])
            with closing(sqlite3.connect(migrated.migration_backup)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(
                    db.execute("SELECT * FROM lesions").fetchall(), originals["lesions"]
                )
            LongitudinalStore(legacy)
            self.assertEqual(len(list((Path(legacy) / "backups").glob("*.sqlite3"))), 1)

    def test_failed_migration_rolls_back_schema_and_data(self):
        with tempfile.TemporaryDirectory() as legacy:
            path = Path(legacy) / "history.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(
                    """
                    CREATE TABLE lesions(id TEXT PRIMARY KEY, patient TEXT NOT NULL,
                        name TEXT NOT NULL, site TEXT NOT NULL, created TEXT NOT NULL,
                        UNIQUE(patient,name));
                    INSERT INTO lesions VALUES('l1','','L01','','created');
                    PRAGMA user_version=1;
                """
                )
            with self.assertRaises(sqlite3.IntegrityError):
                LongitudinalStore(legacy)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(
                    [r[1] for r in db.execute("PRAGMA table_info(lesions)")],
                    ["id", "patient", "name", "site", "created"],
                )
                self.assertFalse(
                    db.execute(
                        "SELECT name FROM sqlite_master WHERE name='persons'"
                    ).fetchone()
                )
                self.assertEqual(
                    db.execute("SELECT count(*) FROM lesions").fetchone()[0], 1
                )


if __name__ == "__main__":
    unittest.main()
