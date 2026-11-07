"""Controles del arranque aislado y resultados conocidos de la demostración."""

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from capstone_demo import prepare_demo
from longitudinal_store import LongitudinalStore


class DemoControlsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "demo"
        cls.demo = prepare_demo(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_controls_separate_rotation_change_and_unusable_capture(self):
        rotation, change, blur = self.demo["checks"]
        self.assertTrue(rotation["comparable"])
        self.assertLess(abs(rotation["changes"]["area"]), 2.0)
        self.assertTrue(change["comparable"])
        # Pixel counts of rasterized circles approximate the analytical area ratio.
        self.assertAlmostEqual(change["changes"]["area"], 100 * ((55 / 45) ** 2 - 1), delta=2)
        self.assertFalse(blur["comparable"])
        self.assertFalse(blur["changes"])
        self.assertTrue(blur["warnings"])

    def test_reopening_does_not_duplicate_visits_or_comparisons(self):
        self.assertEqual(prepare_demo(self.root), self.demo)
        store = LongitudinalStore(self.root)
        self.assertEqual(len(store.persons()), 1)
        self.assertEqual(len(store.records(self.demo["lesion_id"])), 4)
        self.assertEqual(len(store.comparisons(self.demo["lesion_id"])), 3)
        self.assertTrue(all(r["metadata"]["synthetic"] for r in store.records(self.demo["lesion_id"])))

    def test_refuses_existing_non_demo_folder_without_changing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "existing"
            store = LongitudinalStore(target)
            store.create_person("PRESERVAR")
            before = store.db.read_bytes()
            with self.assertRaises(ValueError):
                prepare_demo(target)
            self.assertEqual(store.db.read_bytes(), before)


class DemoStartupTests(unittest.TestCase):
    def test_opens_isolated_case_without_loading_models(self):
        from interfaz import App

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "demo"
            demo = prepare_demo(path)
            root = tk.Tk()
            root.withdraw()
            app = App(root, store_root=path, autoload_model=False, demo=True)
            try:
                app.show_evolution()
                root.update()
                window = app.evolution_window
                self.assertEqual(window.store.root, path.resolve())
                self.assertIsNone(app.autoload_job)
                self.assertIsNone(app.model)
                self.assertIn("SINTÉTICA", window.window.title())
                window.open_person()
                window.people.selection_set(demo["lesion_id"])
                window.choose_person_lesion()
                root.update()
                self.assertEqual(window.tabs.index("current"), 0)
                self.assertEqual(len(window.records), 4)
                self.assertEqual(len(window.saved_comparisons), 3)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
