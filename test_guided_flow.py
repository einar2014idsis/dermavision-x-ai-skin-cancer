"""Acceptance checks for independent photo, two-photo and follow-up workflows.

All records and images are synthetic and live in a temporary SQLite store.
The tests verify software behaviour, not diagnostic accuracy.
"""

import copy
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from calibration import ScoreCalibration
from longitudinal_store import LongitudinalStore
from longitudinal_ui import EvolutionWindow
from longitudinal_insights import date_label
from test_longitudinal import sample
from test_visit_workflow import FixedModel, Gate


class GuidedFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(Path(self.temp.name) / "records")
        self.lesion = self.store.create_lesion("PRUEBA", "Lesión sintética", "Brazo")
        self.ids = []
        for month, radius in ((1, 45), (2, 50), (3, 55), (4, 60)):
            image, mask = sample(radius)
            self.ids.append(
                self.store.add_record(
                    self.lesion,
                    f"2026-0{month}-01",
                    image,
                    mask,
                    dict(
                        mask_reviewed=True,
                        note="Registro sintético para pruebas de software",
                    ),
                )
            )
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = SimpleNamespace(
            root=self.root,
            busy=False,
            model=None,
            domain_gate=None,
            reference_index=None,
            experiment_folder=Path(self.temp.name),
            calibration=ScoreCalibration(),
            refresh_actions=lambda: None,
        )
        self.window = EvolutionWindow(self.app, self.store)
        self.window.lesion_id = self.lesion
        self.window.refresh_history()
        self.window.navigate(0)
        self.root.update()

    def tearDown(self):
        # Normally every test waits for the worker before closing its window.
        self.window.cancel_auto_comparison()
        self.window.running = False
        self.window.followup_pending = []
        self.window.followup_batch = False
        self.app.busy = False
        self.window.close()
        self.root.destroy()
        self.temp.cleanup()

    def wait_for_operation(self):
        deadline = time.monotonic() + 40
        with patch("longitudinal_ui.messagebox.showerror") as error:
            while time.monotonic() < deadline:
                self.root.update()
                pending = (
                    self.window.running
                    or self.app.busy
                    or getattr(self.window, "auto_compare_job", None)
                    or getattr(self.window, "followup_pending", [])
                    or getattr(self.window, "followup_batch", False)
                )
                if not pending:
                    self.root.update()
                    break
                time.sleep(0.01)
            self.assertFalse(self.window.running, "The analysis worker did not finish")
            self.assertFalse(self.app.busy)
            self.assertIsNone(getattr(self.window, "auto_compare_job", None))
            self.assertFalse(getattr(self.window, "followup_pending", []))
            self.assertFalse(getattr(self.window, "followup_batch", False))
            error.assert_not_called()

    def choose_pair(self, previous, current):
        self.window.set_workspace_mode("compare")
        self.window.choose_comparison_photo(0, previous)
        self.window.choose_comparison_photo(1, current)
        self.wait_for_operation()
        self.assertIsNotNone(self.window.current_result)
        self.assertEqual(self.window.current_result["previous_id"], previous)
        self.assertEqual(self.window.current_result["current_id"], current)
        self.root.update()
        for (caption, picture), identifier in zip(
            self.window.picture_widgets[:2], (previous, current)
        ):
            self.assertTrue(
                picture.cget("image"), "A selected photograph was not rendered"
            )
            self.assertIn(
                date_label(self.store.record(identifier)["captured_at"]),
                caption.cget("text"),
            )

    def test_graph_is_optional_and_individual_photo_has_its_own_selection(self):
        self.assertTrue(self.window.chart_toggle.get())
        self.assertEqual(self.window.comparison_pair, [None, None])
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[2])
        self.root.update()
        self.assertEqual(self.window.photo_selection_id, self.ids[2])
        self.assertEqual(self.window.comparison_pair, [None, None])
        self.assertEqual(self.store.comparisons(self.lesion), [])
        self.assertIsNone(self.window.auto_compare_job)

    def test_comparison_uses_exactly_the_two_slots_without_initial_photo(self):
        self.choose_pair(self.ids[1], self.ids[3])
        rows = self.store.comparisons(self.lesion)
        self.assertEqual(
            [(r["previous_id"], r["current_id"]) for r in rows],
            [(self.ids[1], self.ids[3])],
        )
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[3]])
        self.assertEqual(self.window.comparison_result_id, rows[0]["id"])
        self.assertNotIn(self.ids[0], self.window.heatmap_ids)

    def test_third_thumbnail_does_not_silently_replace_either_slot(self):
        self.choose_pair(self.ids[0], self.ids[1])
        result_id = self.window.comparison_result_id
        result = copy.deepcopy(self.window.current_result)
        self.window.select_photo(self.ids[2])
        self.root.update()
        self.assertEqual(self.window.comparison_pair, [self.ids[0], self.ids[1]])
        self.assertEqual(self.window.comparison_result_id, result_id)
        self.assertEqual(self.window.current_result, result)
        self.assertIsNone(self.window.auto_compare_job)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)

    def test_explicit_slot_change_only_replaces_the_chosen_photo(self):
        self.choose_pair(self.ids[0], self.ids[1])
        self.window.choose_comparison_photo(1, self.ids[3])
        self.wait_for_operation()
        self.assertEqual(self.window.comparison_pair, [self.ids[0], self.ids[3]])
        self.assertEqual(self.window.current_result["previous_id"], self.ids[0])
        self.assertEqual(self.window.current_result["current_id"], self.ids[3])
        pairs = {
            (r["previous_id"], r["current_id"])
            for r in self.store.comparisons(self.lesion)
        }
        self.assertEqual(
            pairs, {(self.ids[0], self.ids[1]), (self.ids[0], self.ids[3])}
        )

    def test_tabs_preserve_individual_photo_and_the_selected_pair(self):
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[0])
        self.choose_pair(self.ids[1], self.ids[2])
        result_id = self.window.comparison_result_id
        for mode in ("followup", "photos", "compare"):
            self.window.set_workspace_mode(mode)
            self.root.update()
            self.assertEqual(self.window.workspace_mode, mode)
            self.assertEqual(self.window.photo_selection_id, self.ids[0])
            self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[2]])
            self.assertEqual(self.window.comparison_result_id, result_id)
        self.assertEqual(self.window.current_result["previous_id"], self.ids[1])
        self.assertEqual(self.window.current_result["current_id"], self.ids[2])

    def test_followup_worker_preserves_the_user_pair_and_photo(self):
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[3])
        self.choose_pair(self.ids[1], self.ids[2])
        result_id = self.window.comparison_result_id
        result = copy.deepcopy(self.window.current_result)
        self.window.set_workspace_mode("followup")
        self.window.compare_reference_followup()
        self.wait_for_operation()
        self.assertEqual(self.window.workspace_mode, "followup")
        self.assertEqual(self.window.photo_selection_id, self.ids[3])
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[2]])
        self.assertEqual(self.window.comparison_result_id, result_id)
        self.assertEqual(self.window.current_result, result)
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 3)
        self.assertTrue(self.window.chart_toggle.get())

    def test_occlusion_reanalysis_of_photo_b_keeps_comparison_open(self):
        self.app.model = FixedModel(0.8)
        self.app.domain_gate = Gate()
        self.choose_pair(self.ids[1], self.ids[2])
        result_id = self.window.comparison_result_id
        self.window.classify_visit(self.ids[2])
        self.wait_for_operation()
        self.assertEqual(self.window.workspace_mode, "compare")
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[2]])
        self.assertIsNotNone(self.window.comparison_result_id)
        self.assertEqual(self.window.current_result["previous_id"], self.ids[1])
        self.assertEqual(self.window.current_result["current_id"], self.ids[2])
        self.assertIn(
            "explanation", self.store.record(self.ids[2])["metadata"]["classification"]
        )

    def test_date_edit_retains_the_pair_ids_and_refreshes_its_result(self):
        self.choose_pair(self.ids[1], self.ids[2])
        original_id = self.window.comparison_result_id
        self.window.edit_visit_date(self.ids[1])
        dialog = next(
            w
            for w in self.window.window.winfo_children()
            if isinstance(w, tk.Toplevel) and hasattr(w, "date_fields")
        )
        dialog.date_fields.date_text.set("02/02/2026")
        save = next(
            w
            for w in dialog.winfo_children()
            if w.winfo_class() in ("Button", "TButton")
            and w.cget("text") == "Guardar fecha"
        )
        save.invoke()
        self.wait_for_operation()
        self.assertEqual(self.window.workspace_mode, "compare")
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[2]])
        self.assertEqual(self.window.current_result["previous_id"], self.ids[1])
        self.assertEqual(self.window.current_result["current_id"], self.ids[2])
        self.assertEqual(
            self.window.current_result["previous_date"], "2026-02-02T00:00:00"
        )
        self.assertNotEqual(self.window.comparison_result_id, original_id)
        previous_row = next(
            r for r in self.store.comparisons(self.lesion) if r["id"] == original_id
        )
        self.assertTrue(previous_row["stale_dates"])

    def test_delete_an_unrelated_photo_preserves_both_pair_slots(self):
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[0])
        self.choose_pair(self.ids[1], self.ids[2])
        result_id = self.window.comparison_result_id
        with patch("longitudinal_actions.messagebox.askyesno", return_value=True):
            self.window.delete_photo(self.ids[3])
        self.root.update()
        self.assertEqual(self.window.photo_selection_id, self.ids[0])
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[2]])
        self.assertEqual(self.window.comparison_result_id, result_id)
        self.assertEqual(len(self.store.records(self.lesion)), 3)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)

    def test_delete_a_pair_photo_preserves_the_other_slot_without_a_false_result(self):
        self.choose_pair(self.ids[1], self.ids[2])
        with patch("longitudinal_actions.messagebox.askyesno", return_value=True):
            self.window.delete_photo(self.ids[2])
        self.root.update()
        self.assertEqual(self.window.comparison_pair, [self.ids[1], None])
        self.assertIsNone(self.window.comparison_result_id)
        self.assertIsNone(self.window.current_result)
        self.assertIsNone(self.window.auto_compare_job)
        self.assertEqual(self.store.comparisons(self.lesion), [])

    def test_opening_saved_comparison_does_not_replace_individual_photo(self):
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[0])
        self.choose_pair(self.ids[1], self.ids[2])
        result_id = self.window.comparison_result_id
        self.window.navigate(1)
        self.window.comparisons.selection_set(result_id)
        self.window.restore_comparison()
        self.root.update()
        self.assertEqual(self.window.workspace_mode, "compare")
        self.assertEqual(self.window.photo_selection_id, self.ids[0])
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[2]])
        self.assertEqual(self.window.comparison_result_id, result_id)

    def test_equal_dates_offer_a_visual_map_without_a_temporal_point(self):
        self.store.update_record_date(self.ids[1], "2026-01-01")
        self.window.refresh_history()
        self.window.set_workspace_mode("compare")
        self.window.choose_comparison_photo(0, self.ids[0])
        self.window.choose_comparison_photo(1, self.ids[1])
        self.wait_for_operation()
        result = self.window.current_result
        self.assertIsNotNone(result)
        self.assertEqual(
            {result["previous_id"], result["current_id"]}, set(self.ids[:2])
        )
        self.assertEqual(result["mode"], "visual")
        self.assertIsNone(result["change_index"])
        self.assertIsNotNone(result["visual_index"])
        self.assertFalse(self.window.selected_trend_series()["points"])
        self.root.update()
        self.assertTrue(self.window.picture_widgets[2][1].cget("image"))
        self.assertIn("Misma fecha", self.window.pair_summary.cget("text"))

    def test_reverse_selection_is_normalized_before_the_worker_starts(self):
        self.window.set_workspace_mode("compare")
        self.window.choose_comparison_photo(0, self.ids[3])
        self.window.choose_comparison_photo(1, self.ids[1])
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[3]])
        self.assertEqual(
            self.window.pair_records[self.window.previous.current()]["id"], self.ids[1]
        )
        self.assertEqual(
            self.window.pair_records[self.window.current.current()]["id"], self.ids[3]
        )
        self.wait_for_operation()
        self.assertEqual(self.window.current_result["previous_id"], self.ids[1])
        self.assertEqual(self.window.current_result["current_id"], self.ids[3])
        rows = self.store.comparisons(self.lesion)
        self.assertEqual(
            [(r["previous_id"], r["current_id"]) for r in rows],
            [(self.ids[1], self.ids[3])],
        )
        self.root.update()
        self.assertTrue(self.window.picture_widgets[2][1].cget("image"))

    def test_changing_lesion_clears_photo_pair_and_visible_result(self):
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[0])
        self.choose_pair(self.ids[1], self.ids[2])
        other = self.store.create_lesion("PRUEBA", "Otra lesión", "Espalda")
        self.window.refresh_lesions()
        position = next(
            n
            for n, lesion in enumerate(self.window.visible_lesions)
            if lesion["id"] == other
        )
        self.window.lesion_choice.current(position)
        self.window.select_lesion()
        self.root.update()
        self.assertEqual(self.window.lesion_id, other)
        self.assertIsNone(self.window.photo_selection_id)
        self.assertEqual(self.window.comparison_pair, [None, None])
        self.assertIsNone(self.window.comparison_result_id)
        self.assertIsNone(self.window.current_result)
        self.assertIsNone(self.window.auto_compare_job)
        self.assertEqual(self.window.records, [])


if __name__ == "__main__":
    unittest.main()
