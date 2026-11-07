"""Visual comparison is descriptive, independent of chronology and registration."""

import csv
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from calibration import ScoreCalibration
from longitudinal_analysis import compare_visual_images, compare_records
from longitudinal_store import LongitudinalStore
from longitudinal_ui import EvolutionWindow
from test_longitudinal import sample


def distinct_sample():
    image, mask = sample()
    array = np.asarray(image).copy()
    array[np.asarray(mask) > 0] = (45, 25, 20)
    contour = np.zeros((400, 400), "uint8")
    import cv2

    cv2.ellipse(contour, (200, 200), (70, 35), 25, 0, 360, 255, -1)
    return Image.fromarray(array), Image.fromarray(contour)


class VisualComparisonTests(unittest.TestCase):
    def test_identical_regions_have_zero_index_and_no_temporal_measure(self):
        image, mask = sample()
        result, _, overlay = compare_visual_images(image, image, mask, mask)
        self.assertEqual(result["visual_index"], 0)
        self.assertEqual(result["mode"], "visual")
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["change_index"])
        self.assertEqual(overlay.size, (384, 384))
        self.assertEqual(
            set(result["visual_components"]),
            {"shape", "asymmetry", "border", "color", "texture"},
        )

    def test_distinct_regions_have_finite_index_and_different_silhouette_pixels(self):
        image, mask = sample()
        other, contour = distinct_sample()
        with patch(
            "longitudinal_analysis.align", side_effect=AssertionError("must not align")
        ):
            result, _, overlay = compare_visual_images(image, other, mask, contour)
        self.assertGreater(result["visual_index"], 0)
        self.assertLessEqual(result["visual_index"], 100)
        self.assertTrue(np.isfinite(list(result["visual_components"].values())).all())
        colors = set(map(tuple, np.asarray(overlay).reshape(-1, 3)))
        self.assertIn((0, 220, 220), colors)
        self.assertIn((255, 170, 0), colors)

    def test_invalid_or_unreviewed_contours_do_not_create_results(self):
        image, mask = sample()
        with self.assertRaises(ValueError):
            compare_visual_images(image, image, mask, mask, reviewed=False)
        with self.assertRaises(ValueError):
            compare_visual_images(image, image, Image.new("L", image.size), mask)

    def test_visual_history_accepts_equal_dates_different_lesions_and_survives_reopen(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            store = LongitudinalStore(directory)
            a = store.create_lesion("P01", "L01")
            b = store.create_lesion("P01", "L02")
            image, mask = sample()
            other, contour = distinct_sample()
            first = store.add_record(
                a, "2026-01-01", image, mask, dict(mask_reviewed=True)
            )
            second = store.add_record(
                b, "2026-01-01", other, contour, dict(mask_reviewed=True)
            )
            output = compare_records(store, first, second, mode="visual")
            reopened = LongitudinalStore(directory)
            saved = reopened.comparisons(b)[0]
            self.assertEqual(saved["result"], output["result"])
            self.assertTrue(reopened.path(saved["overlay"]).exists())
            reopened.update_record_date(first, "2026-12-01")
            self.assertFalse(reopened.comparisons(b)[0]["stale_dates"])
            with self.assertRaises(ValueError):
                compare_records(reopened, first, second)
            target = Path(directory) / "export"
            reopened.export(target)
            with (target / "pairs.csv").open(encoding="utf-8-sig") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["mode"], "visual")
            self.assertTrue(row["visual_index"])
            self.assertEqual(row["change_index"], "")
            self.assertEqual(row["comparable"], "False")


class VisualWindowTests(unittest.TestCase):
    def test_visual_mode_shows_pair_map_without_turning_followup_into_bars(self):
        with tempfile.TemporaryDirectory() as directory:
            root = tk.Tk()
            root.withdraw()
            store = LongitudinalStore(directory)
            lesion = store.create_lesion("P01", "L01")
            image, mask = sample()
            other, contour = distinct_sample()
            second_lesion = store.create_lesion("P01", "L02")
            ids = [
                store.add_record(target, "2026-01-01", im, ma, dict(mask_reviewed=True))
                for target, im, ma in (
                    (lesion, image, mask),
                    (second_lesion, other, contour),
                )
            ]
            unrelated = store.create_lesion("P02", "L01")
            store.add_record(
                unrelated, "2026-01-01", image, mask, dict(mask_reviewed=True)
            )
            app = SimpleNamespace(
                root=root,
                busy=False,
                model=None,
                domain_gate=None,
                calibration=ScoreCalibration(),
                reference_index=None,
                experiment_folder=Path(directory),
                refresh_actions=lambda: None,
            )
            window = EvolutionWindow(app, store)
            try:
                window.comparison_mode.current(1)
                window.change_comparison_mode()
                self.assertTrue(window.chart_toggle.get())
                self.assertIn("Línea de tiempo", window.chart_heading.cget("text"))
                self.assertEqual({r["id"] for r in window.pair_records}, set(ids))
                for widget, identifier in zip((window.previous, window.current), ids):
                    widget.current(
                        next(
                            n
                            for n, r in enumerate(window.pair_records)
                            if r["id"] == identifier
                        )
                    )
                with patch("longitudinal_ui.messagebox.showerror") as error:
                    window.compare()
                    deadline = time.monotonic() + 15
                    while window.running and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.01)
                    self.assertFalse(window.running)
                    error.assert_not_called()
                self.assertEqual(window.current_result["mode"], "visual")
                self.assertIn("/ 100", window.index_value.cget("text"))
                root.update()
                self.assertEqual(len(window.photos), 3)
                self.assertEqual(
                    {
                        window.current_result["previous_id"],
                        window.current_result["current_id"],
                    },
                    set(ids),
                )
                window.set_workspace_mode("followup")
                window.chart_toggle.set(True)
                window.toggle_chart()
                root.update()
                self.assertEqual(window.selected_trend_series()["metric"], "index")
                self.assertFalse(window.selected_trend_series()["points"])
                rectangles = [
                    i
                    for i in window.chart.find_all()
                    if window.chart.type(i) == "rectangle"
                ]
                self.assertEqual(rectangles, [])
                self.assertIn("Línea de tiempo", window.chart_heading.cget("text"))
                saved = window.saved_comparisons[0]
                window.clear_output()
                window.comparisons.selection_set(saved["id"])
                window.restore_comparison()
                root.update()
                self.assertEqual(window.current_result["mode"], "visual")
                self.assertEqual(len(window.photos), 3)
                self.assertIn("COMPARACIÓN VISUAL", window.report.get("1.0", "end"))
                self.assertIn("Siluetas normalizadas", window.map_note.cget("text"))
            finally:
                window.running = False
                window.close()
                root.destroy()


if __name__ == "__main__":
    unittest.main()
