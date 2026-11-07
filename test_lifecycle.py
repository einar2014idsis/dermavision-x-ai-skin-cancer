import tempfile
import unittest
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image
from longitudinal_store import LongitudinalStore
from longitudinal_reports import audit_lesion, export_lesion_pdf


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = LongitudinalStore(self.root / "data")
        self.lesion = self.store.create_lesion("P01", "Lesión de prueba")
        photo = Image.new("RGB", (100, 100), "#ad8b76")
        mask = np.zeros((100, 100), dtype="uint8")
        mask[30:70, 30:70] = 255
        self.a = self.store.add_record(
            self.lesion,
            "2026-01-01T12:00:00",
            photo,
            Image.fromarray(mask),
            {"mask_reviewed": True},
        )
        self.b = self.store.add_record(
            self.lesion,
            "2026-02-01T12:00:00",
            photo,
            Image.fromarray(mask),
            {"mask_reviewed": True},
        )
        self.result = {
            "mode": "visual",
            "comparable": False,
            "visual_available": True,
            "visual_index": 0.0,
            "change_level": "Baja",
            "previous_date": "2026-01-01T12:00:00",
            "current_date": "2026-02-01T12:00:00",
            "warnings": ["Comparación experimental"],
        }
        self.c = self.store.save_comparison(self.a, self.b, self.result, photo)

    def tearDown(self):
        self.temp.cleanup()

    def test_photo_trash_restores_dependencies(self):
        self.store.move_to_trash("record", self.a)
        self.assertEqual(len(self.store.records(self.lesion)), 1)
        self.assertEqual(self.store.comparisons(self.lesion), [])
        self.store.restore_trash("record", self.a)
        self.assertEqual(len(self.store.records(self.lesion)), 2)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)

    def test_comparison_trash_preserves_photos(self):
        self.store.move_to_trash("comparison", self.c)
        self.assertEqual(len(self.store.records(self.lesion)), 2)
        self.store.restore_trash("comparison", self.c)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)

    def test_dependency_must_be_restored_first(self):
        self.store.move_to_trash("record", self.a)
        with self.assertRaises(ValueError):
            self.store.restore_trash("comparison", self.c)

    def test_purge_removes_related_files_and_keeps_other_photo(self):
        photo = self.store.path(self.store.record(self.a)["image"])
        self.store.move_to_trash("record", self.a)
        self.store.purge_trash("record", self.a)
        self.assertFalse(photo.exists())
        self.assertEqual(len(self.store.records(self.lesion)), 1)
        self.assertEqual(self.store.trash_items(), [])
        with self.assertRaises(ValueError):
            self.store.record(self.a)

    def test_complete_backup_restore_elsewhere_with_trash(self):
        self.store.save_record_analysis(
            self.a,
            {"state": "accepted", "label": "benign", "score": 0.1, "raw_score": 0.1},
            Image.new("RGB", (100, 100), "red"),
        )
        self.store.move_to_trash("record", self.a)
        target = self.store.backup(self.root / "portable.zip")
        other = LongitudinalStore(self.root / "restored")
        recovery = other.restore_backup(target)
        self.assertTrue(recovery.exists())
        self.assertEqual(len(other.trash_items()), 2)
        other.restore_trash("record", self.a)
        self.assertEqual(len(other.records(self.lesion)), 2)
        other.load_images(other.record(self.a))
        self.assertEqual(other.load_explanation(self.a).getpixel((0, 0)), (255, 0, 0))
        self.assertTrue(
            other.path(other.comparisons(self.lesion)[0]["overlay"]).exists()
        )

    def test_corrupt_backup_leaves_database_unchanged(self):
        target = self.store.backup(self.root / "portable.zip")
        broken = self.root / "broken.zip"
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(broken, "w") as dest:
            for name in source.namelist():
                dest.writestr(
                    name, b"broken" if name == "history.sqlite3" else source.read(name)
                )
        with self.assertRaises(ValueError):
            self.store.restore_backup(broken)
        self.assertEqual(len(self.store.records(self.lesion)), 2)

    def test_duplicate_comparison_reuses_row(self):
        identifier = self.store.save_comparison(
            self.a, self.b, self.result, Image.new("RGB", (100, 100))
        )
        self.assertEqual(identifier, self.c)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)

    def test_report_and_audit(self):
        report = self.root / "report.pdf"
        pages = export_lesion_pdf(self.store, self.lesion, report, self.c)
        self.assertGreaterEqual(pages, 3)
        self.assertTrue(report.read_bytes().startswith(b"%PDF"))
        self.assertIn("Verificación pendiente", audit_lesion(self.store, self.lesion))

    def test_clear_history_can_be_restored_without_losing_photos(self):
        self.store.move_to_trash("history", lesion_id=self.lesion)
        self.assertEqual(len(self.store.records(self.lesion)), 2)
        self.assertEqual(self.store.comparisons(self.lesion), [])
        self.store.restore_trash("comparison", self.c)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)


class ManagementWindowTests(unittest.TestCase):
    def test_photo_removal_refreshes_history_and_pair_choices(self):
        import tkinter as tk
        from types import SimpleNamespace
        from unittest.mock import patch
        from calibration import ScoreCalibration
        from longitudinal_ui import EvolutionWindow

        case = LifecycleTests()
        case.setUp()
        root = tk.Tk()
        root.withdraw()
        app = SimpleNamespace(
            root=root,
            busy=False,
            model=None,
            domain_gate=None,
            calibration=ScoreCalibration(),
            reference_index=None,
            experiment_folder=case.root,
            refresh_actions=lambda: None,
        )
        window = EvolutionWindow(app, case.store)
        try:
            root.update()
            window.navigate(1)
            window.displayed_record_id = case.b
            window.history.selection_set(case.a)
            root.update()
            self.assertEqual(window.tabs.index("current"), 1)
            self.assertEqual(window.displayed_record_id, case.a)
            self.assertIn("open_history_photo", window.history.bind("<Double-1>"))
            with patch("longitudinal_actions.messagebox.askyesno", return_value=False):
                window.delete_photo()
            self.assertEqual(len(case.store.records(case.lesion)), 2)
            self.assertEqual(window.tabs.index("current"), 1)
            with patch("longitudinal_actions.messagebox.askyesno", return_value=True):
                window.delete_photo()
            root.update()
            self.assertEqual(window.tabs.index("current"), 1)
            self.assertEqual(case.store.records(case.lesion)[0]["id"], case.b)
            self.assertEqual(len(window.history.get_children()), 1)
            self.assertEqual(len(window.pair_records), 1)
            self.assertEqual(len(window.comparisons.get_children()), 0)
            self.assertIsNone(window.current_result)
            case.store.restore_trash("record", case.a)
            window.after_data_change()
            root.update()
            self.assertEqual(len(window.history.get_children()), 2)
            self.assertEqual(len(window.comparisons.get_children()), 1)
            window.history.selection_set(case.a)
            root.update()
            self.assertEqual(window.tabs.index("current"), 1)
            window.open_history_photo()
            root.update()
            self.assertEqual(window.tabs.index("current"), 0)
            self.assertEqual(window.displayed_record_id, case.a)
            window.navigate(1)
            window.lesion_id = None
            window.after_data_change()
            root.update()
        finally:
            window.close()
            root.destroy()
            case.tearDown()


if __name__ == "__main__":
    unittest.main()
