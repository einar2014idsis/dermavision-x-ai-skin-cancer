"""End-to-end persistence, classification states and saved-visit UI checks."""

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
from longitudinal_store import LongitudinalStore
from longitudinal_analysis import classify_record, compare_records, classification_text
from longitudinal_ui import EvolutionWindow, RecordEditor
from test_longitudinal import sample


class FixedModel:
    def __init__(self, score):
        self.score = score
        self.calls = 0

    def __call__(self, batch, training=False):
        self.calls += 1
        values = np.full((len(batch), 1), self.score)
        return SimpleNamespace(numpy=lambda: values)


class Gate:
    def __init__(self, state="accepted"):
        self.state = state

    def assess(self, image):
        return SimpleNamespace(state=self.state, message="Control de contenido")


class VisitWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(self.temp.name)
        self.lesion = self.store.create_lesion("P01", "L01")
        self.image, self.mask = sample()
        self.record = self.store.add_record(
            self.lesion,
            "2026-01-01",
            self.image,
            self.mask,
            dict(mask_reviewed=True, note="Nota original"),
        )
        self.calibration = ScoreCalibration(uncertain_low=0.45, uncertain_high=0.55)

    def tearDown(self):
        self.temp.cleanup()

    def test_benign_malignant_and_uncertain_saved_without_changing_note(self):
        for score, expected in ((0.2, "benign"), (0.8, "malignant"), (0.5, None)):
            with self.subTest(score=score):
                result = classify_record(
                    self.store, self.record, FixedModel(score), Gate(), self.calibration
                )
                self.assertEqual(result.get("label"), expected)
                self.assertEqual(
                    result["state"], "accepted" if expected else "uncertain"
                )
                reopened = LongitudinalStore(self.temp.name)
                stored = reopened.record(self.record)["metadata"]
                self.assertEqual(stored["note"], "Nota original")
                self.assertTrue(stored["mask_reviewed"])
                self.assertAlmostEqual(stored["classification"]["score"], score)
                if expected:
                    self.assertEqual(
                        reopened.load_explanation(self.record).size, (224, 224)
                    )
                else:
                    self.assertNotIn("explanation", result)
                    self.assertIn("abstiene", classification_text(result))
                    with self.assertRaises(ValueError):
                        reopened.load_explanation(self.record)

    def test_previous_explanation_survives_comparison_and_snapshot_reanalysis(self):
        old = classify_record(
            self.store, self.record, FixedModel(0.8), Gate(), self.calibration
        )
        later = self.store.add_record(
            self.lesion, "2026-02-01", self.image, self.mask, dict(mask_reviewed=True)
        )
        output = compare_records(
            self.store,
            self.record,
            later,
            FixedModel(0.8),
            Gate(),
            calibration=self.calibration,
        )
        self.assertEqual(
            self.store.record(self.record)["metadata"]["classification"]["explanation"],
            old["explanation"],
        )
        snapshot = output["result"]["current_classification"]
        classify_record(self.store, later, FixedModel(0.2), Gate(), self.calibration)
        self.assertEqual(self.store.load_explanation(later, snapshot).size, (224, 224))

    def test_quality_and_domain_block_prediction(self):
        dark = Image.new("RGB", self.image.size, "black")
        bad = self.store.add_record(
            self.lesion, "2026-02-01", dark, self.mask, dict(mask_reviewed=True)
        )
        model = FixedModel(0.8)
        self.assertEqual(
            classify_record(self.store, bad, model, Gate())["state"], "quality_failed"
        )
        self.assertEqual(model.calls, 0)
        for state in ("rejected", "uncertain"):
            result = classify_record(self.store, self.record, model, Gate(state))
            self.assertEqual(result["state"], state)
            self.assertIsNone(result["score"])
            self.assertNotIn("explanation", result)
        self.assertEqual(model.calls, 0)

    def test_unavailable_model_never_fabricates_prediction(self):
        result = classify_record(self.store, self.record)
        self.assertEqual(result["state"], "unavailable")
        self.assertIsNone(result["score"])
        self.assertNotIn("classification", self.store.record(self.record)["metadata"])

    def test_verified_saved_prediction_available_after_reopening(self):
        result = classify_record(self.store, self.record, FixedModel(0.8), Gate())
        reopened = LongitudinalStore(self.temp.name)
        self.assertEqual(classify_record(reopened, self.record), result)
        row = reopened.record(self.record)
        reopened.path(row["image"]).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            classify_record(reopened, self.record)

    def test_explanation_integrity_and_failure_preserves_classification(self):
        result = classify_record(self.store, self.record, FixedModel(0.8), Gate())
        self.store.path(result["explanation"]["path"]).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.store.load_explanation(self.record)
        with patch(
            "explainability.occlusion_explanation",
            side_effect=RuntimeError("explanation failed"),
        ):
            result = classify_record(self.store, self.record, FixedModel(0.8), Gate())
        self.assertEqual(result["state"], "accepted")
        self.assertIn("explanation_error", result)
        self.assertNotIn("explanation", result)
        self.assertEqual(
            self.store.record(self.record)["metadata"]["classification"]["state"],
            "accepted",
        )

    def test_nonfinite_prediction_does_not_replace_saved_result(self):
        saved = classify_record(self.store, self.record, FixedModel(0.2), Gate())
        with self.assertRaises(ValueError):
            classify_record(self.store, self.record, FixedModel(float("nan")), Gate())
        self.assertEqual(
            self.store.record(self.record)["metadata"]["classification"], saved
        )

    def test_uncertain_classification_allows_descriptive_comparison_and_reopen(self):
        later = self.store.add_record(
            self.lesion, "2026-02-01", self.image, self.mask, dict(mask_reviewed=True)
        )
        output = compare_records(
            self.store,
            self.record,
            later,
            FixedModel(0.5),
            Gate(),
            calibration=self.calibration,
        )
        self.assertTrue(output["result"]["comparable"])
        self.assertEqual(
            output["result"]["current_classification"]["state"], "uncertain"
        )
        self.assertAlmostEqual(output["result"]["change_index"], 0, places=4)
        reopened = LongitudinalStore(self.temp.name)
        comparison = reopened.comparisons(self.lesion)[0]
        self.assertEqual(comparison["id"], output["id"])
        self.assertEqual(comparison["result"], output["result"])
        self.assertTrue(reopened.path(comparison["overlay"]).exists())
        self.assertEqual(len(reopened.records(self.lesion)), 2)

    def test_alignment_failure_still_reports_visual_descriptors_without_growth_index(
        self,
    ):
        image, mask = sample(radius=65)
        later = self.store.add_record(
            self.lesion, "2026-02-01", image, mask, dict(mask_reviewed=True)
        )
        with patch(
            "longitudinal_analysis.align",
            return_value=(None, dict(accepted=False, matches=3)),
        ):
            output = compare_records(self.store, self.record, later)
        result = output["result"]
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["change_index"])
        self.assertGreater(result["visual_differences"]["area_coverage_pp"], 0)
        self.assertNotIn("changes", result)
        self.assertEqual(
            self.store.comparisons(self.lesion)[0]["result"]["visual_differences"],
            result["visual_differences"],
        )

    def test_edit_date_reorders_history_preserves_assets_and_marks_comparison_stale(
        self,
    ):
        later = self.store.add_record(
            self.lesion, "2026-02-01", self.image, self.mask, dict(mask_reviewed=True)
        )
        output = compare_records(self.store, self.record, later)
        original = self.store.record(self.record)
        self.store.update_record_date(self.record, "2026-03-01 12:30:00")
        reopened = LongitudinalStore(self.temp.name)
        updated = reopened.record(self.record)
        self.assertEqual(updated["captured_at"], "2026-03-01T12:30:00")
        self.assertEqual(updated["image"], original["image"])
        self.assertEqual(updated["sha256"], original["sha256"])
        self.assertEqual(updated["metadata"]["note"], "Nota original")
        self.assertEqual(
            [r["id"] for r in reopened.records(self.lesion)], [later, self.record]
        )
        self.assertTrue(reopened.comparisons(self.lesion)[0]["stale_dates"])
        self.assertEqual(
            reopened.comparisons(self.lesion)[0]["result"], output["result"]
        )
        with self.assertRaises(ValueError):
            reopened.pair(self.record, later)
        new = compare_records(reopened, later, self.record)
        self.assertAlmostEqual(new["result"]["elapsed_days"], 28 + 12.5 / 24)
        self.assertFalse(reopened.comparisons(self.lesion)[-1]["stale_dates"])

    def test_invalid_date_keeps_existing_record_unchanged(self):
        original = self.store.record(self.record)
        for value in ("2026-02-30", "", "2026-01-01T12:00:00+03:00"):
            with self.assertRaises(ValueError):
                self.store.update_record_date(self.record, value)
            self.assertEqual(self.store.record(self.record), original)

    def test_rejected_visit_saves_reason_without_change_index(self):
        later = self.store.add_record(
            self.lesion, "2026-02-01", self.image, self.mask, dict(mask_reviewed=True)
        )
        output = compare_records(
            self.store, self.record, later, FixedModel(0.8), Gate("rejected")
        )
        self.assertFalse(output["result"]["comparable"])
        self.assertIsNone(output["result"]["change_index"])
        self.assertTrue(output["result"]["warnings"])
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)


class VisitWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(self.temp.name)
        self.lesion = self.store.create_lesion("P01", "L01")
        self.app = SimpleNamespace(
            root=self.root,
            busy=False,
            model=FixedModel(0.8),
            domain_gate=Gate(),
            reference_index=None,
            calibration=ScoreCalibration(),
            experiment_folder=Path(self.temp.name),
            refresh_actions=lambda: None,
            verified_capture=lambda: sample()[0],
            registration_analysis=lambda: None,
            end_registration=lambda: None,
        )
        self.window = EvolutionWindow(self.app, self.store)
        self.window.capture_review = SimpleNamespace(
            matches=lambda image: image.size == sample()[0].size
            and image.tobytes() == sample()[0].tobytes(),
            snapshot=lambda image: None,
            clear=lambda: None,
        )

    def tearDown(self):
        self.window.running = False
        self.window.close()
        self.root.destroy()
        self.temp.cleanup()

    def wait_operation(self):
        deadline = time.monotonic() + 15
        while (
            self.window.running or self.window.auto_compare_job is not None
        ) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.window.running)
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.window.auto_compare_job)

    def choose_pair(self, previous, current):
        # Populate the two public slots; hidden selectors no longer pick defaults.
        with patch.object(self.window, "request_auto_comparison"):
            self.window.set_workspace_mode("compare")
            self.window.clear_photo_selection()
            self.assertTrue(self.window.choose_comparison_photo(0, previous))
            self.assertTrue(self.window.choose_comparison_photo(1, current))

    def test_save_visit_classify_once_and_restore_explanation(self):
        image, mask = sample()
        self.window.editor(image)
        dialog = next(
            w for w in self.window.window.winfo_children() if isinstance(w, tk.Toplevel)
        )
        # Exercise the actual editor callback, not a simulated database insert.
        save_button = next(
            w
            for container in dialog.winfo_children()
            for w in container.winfo_children()
            if w.winfo_class() == "Button"
            and w.cget("text").startswith("Guardar registro")
        )
        # Retrieve the bound RecordEditor commit method.
        command = dialog.tk.call("info", "commands", save_button.cget("command"))
        self.assertTrue(command)
        # The editor suggests a mask; confirm it using its checkbutton variable.
        check = next(
            w
            for container in dialog.winfo_children()
            for w in container.winfo_children()
            if w.winfo_class() == "Checkbutton"
        )
        check.select()
        with patch("longitudinal_ui.messagebox.showerror") as error:
            save_button.invoke()
            error.assert_not_called()
        self.assertEqual(len(self.store.records(self.lesion)), 1)
        self.window.classify_visit()
        with patch("longitudinal_ui.messagebox.showerror") as error:
            self.wait_operation()
            error.assert_not_called()
        row = self.store.records(self.lesion)[0]
        self.assertEqual(row["metadata"]["classification"]["label"], "malignant")
        self.assertEqual(self.window.malignant_value.cget("text"), "80.0 %")
        self.assertIn("maligna", self.window.report.get("1.0", "end"))
        self.window.show_visit_explanation()
        self.root.update()
        explanation = next(
            w
            for w in self.window.window.winfo_children()
            if isinstance(w, tk.Toplevel)
            and w.title() == "Explicación visual por oclusión"
        )
        explanation.destroy()
        self.window.close()
        self.window = EvolutionWindow(self.app, LongitudinalStore(self.temp.name))
        self.window.show_visit(row["id"])
        self.assertIn("maligna", self.window.report.get("1.0", "end"))

    def test_date_editor_saves_capture_date_and_refreshes_selectors(self):
        image, mask = sample()
        identifier = self.store.add_record(
            self.lesion, "2026-10-09", image, mask, dict(mask_reviewed=True)
        )
        self.window.refresh_history()
        self.window.show_visit(identifier)
        self.window.edit_visit_date()
        dialog = next(
            w
            for w in self.window.window.winfo_children()
            if isinstance(w, tk.Toplevel) and w.title() == "Editar fecha de captura"
        )
        for key, value in dict(
            year="2025", month="06", day="15", hour="09", minute="30", second="00"
        ).items():
            dialog.date_fields.values[key].set(value)
        save = next(
            w
            for w in dialog.winfo_children()
            if w.winfo_class() == "Button" and w.cget("text") == "Guardar fecha"
        )
        with patch("longitudinal_ui.messagebox.showerror") as error:
            save.invoke()
            error.assert_not_called()
        self.assertEqual(
            self.store.record(identifier)["captured_at"], "2025-06-15T09:30:00"
        )
        self.assertEqual(self.window.photo_selection_id, identifier)
        self.assertEqual(self.window.comparison_pair, [None, None])
        self.assertEqual(self.window.current.get(), "")
        self.assertIn("15/06/2025", self.window.result_explanation.cget("text"))
        self.assertIn("09:30:00", self.window.report.get("1.0", "end"))

    def test_selection_stays_on_same_photos_after_date_edit_and_history_refresh(self):
        image, mask = sample()
        first = self.store.add_record(
            self.lesion, "2026-05-09", image, mask, dict(mask_reviewed=True)
        )
        second = self.store.add_record(
            self.lesion, "2026-08-07", image, mask, dict(mask_reviewed=True)
        )
        self.store.add_record(
            self.lesion, "2026-10-09", image, mask, dict(mask_reviewed=True)
        )
        self.window.refresh_history()
        self.choose_pair(first, second)
        self.store.update_record_date(first, "2026-12-09")
        self.window.refresh_history()
        self.assertEqual(self.window.comparison_pair, [second, first])
        self.assertEqual(
            self.window.pair_records[self.window.previous.current()]["id"], second
        )
        self.assertEqual(
            self.window.pair_records[self.window.current.current()]["id"], first
        )
        self.assertEqual(
            [r["captured_at"] for r in self.window.pair_records],
            sorted(r["captured_at"] for r in self.window.pair_records),
        )
        self.assertIn(
            "A es anterior y B es posterior", self.window.pair_summary.cget("text")
        )

    def test_followup_alignment_failure_automatically_displays_visual_result(self):
        from test_visual_comparison import distinct_sample

        image, mask = sample()
        other, contour = distinct_sample()
        identifiers = []
        for date, im, ma in [
            ("2026-05-09", image, mask),
            ("2026-08-07", other, contour),
        ]:
            identifiers.append(
                self.store.add_record(
                    self.lesion, date, im, ma, dict(mask_reviewed=True)
                )
            )
        self.window.refresh_history()
        with patch(
            "longitudinal_analysis.align",
            return_value=(None, dict(accepted=False, matches=3)),
        ), patch("longitudinal_ui.messagebox.showerror") as error:
            self.window.choose_comparison_photo(0, identifiers[0])
            self.window.choose_comparison_photo(1, identifiers[1])
            self.wait_operation()
            error.assert_not_called()
        result = self.window.current_result
        self.assertEqual(result["mode"], "visual")
        self.assertEqual(result["requested_mode"], "longitudinal")
        self.assertGreater(result["visual_index"], 0)
        self.assertEqual(self.window.index_value.cget("text"), "No disponible")
        self.assertEqual(self.window.index_heading.cget("text"), "Medición longitudinal")
        self.assertEqual(len(self.window.photos), 3)
        self.assertIn(
            "No se confirmó una medición temporal",
            self.window.comparison_note.cget("text"),
        )
        self.assertEqual(self.window.comparison_mode_key(), "longitudinal")
        self.assertIn("Línea de tiempo", self.window.chart_heading.cget("text"))
        self.assertIn(
            "No demuestra evolución", self.window.comparison_note.cget("text")
        )

    def test_four_visits_keep_followup_after_fallback_and_saved_result_restore(self):
        def add(date, radius):
            image, mask = sample(radius=radius)
            return self.store.add_record(
                self.lesion, date, image, mask, dict(mask_reviewed=True)
            )

        first = add("2026-01-01", 45)
        second = add("2026-02-01", 50)
        other_lesion = self.store.create_lesion("P01", "L02")
        image, mask = sample()
        unrelated = self.store.add_record(
            other_lesion, "2026-02-15", image, mask, dict(mask_reviewed=True)
        )
        self.window.refresh_lesions()

        def select_pair(a, b):
            self.choose_pair(a, b)

        with patch("longitudinal_ui.messagebox.showerror") as error:
            select_pair(first, second)
            self.window.compare()
            self.wait_operation()
            self.assertTrue(self.window.current_result["comparable"])
            self.assertEqual(self.window.comparison_mode_key(), "longitudinal")
            third = add("2026-03-01", 55)
            self.window.refresh_history()
            select_pair(second, third)
            with patch(
                "longitudinal_analysis.align",
                return_value=(None, dict(accepted=False, matches=3)),
            ):
                self.window.compare()
                self.wait_operation()
            self.assertEqual(self.window.current_result["mode"], "visual")
            self.assertEqual(self.window.comparison_mode_key(), "longitudinal")
            self.assertNotIn(unrelated, {r["id"] for r in self.window.pair_records})
            fallback = next(
                c
                for c in self.store.comparisons(self.lesion)
                if c["current_id"] == third
            )
            self.window.comparisons.selection_set(fallback["id"])
            self.window.restore_comparison()
            self.root.update()
            self.assertEqual(self.window.comparison_mode_key(), "longitudinal")
            fourth = add("2026-04-01", 60)
            self.window.refresh_history()
            self.assertEqual(
                {r["id"] for r in self.window.pair_records},
                {first, second, third, fourth},
            )
            # Any stored visit can be selected; reverse choice is ordered by capture date.
            select_pair(fourth, second)
            self.window.compare()
            self.wait_operation()
            self.assertEqual(self.window.comparison_mode_key(), "longitudinal")
            self.assertEqual(self.window.current_result["previous_id"], second)
            self.assertEqual(self.window.current_result["current_id"], fourth)
            self.assertTrue(self.window.current_result["comparable"])
            self.assertEqual(len(self.store.comparisons(self.lesion)), 3)
            series = self.window.selected_trend_series()
            self.assertEqual(len(series["points"]), 1)
            self.assertEqual(series["points"][0]["target"], second)
            self.assertEqual(series["excluded"]["other_reference"], 1)
            error.assert_not_called()

    def test_date_fields_reject_invalid_dates_and_allow_leap_day(self):
        from longitudinal_ui import DateTimeFields

        fields = DateTimeFields(self.root, "2024-02-29T10:00:00")
        self.assertEqual(fields.get(), "2024-02-29T10:00:00")
        fields.values["year"].set("2025")
        with self.assertRaises(ValueError):
            fields.get()
        fields.destroy()

    def test_uncertain_visit_hides_scores_without_binary_class(self):
        image, mask = sample()
        identifier = self.store.add_record(
            self.lesion, "2026-01-01", image, mask, dict(mask_reviewed=True)
        )
        self.app.model = FixedModel(0.5)
        self.app.calibration = ScoreCalibration(uncertain_low=0.45, uncertain_high=0.55)
        self.window.refresh_lesions()
        self.window.show_visit(identifier)
        self.window.classify_visit()
        self.wait_operation()
        self.assertEqual(
            self.window.class_label.cget("text"), "Resultado no concluyente"
        )
        self.assertEqual(self.window.malignant_value.cget("text"), "— %")
        self.assertNotIn(
            "label", self.store.record(identifier)["metadata"]["classification"]
        )

    def test_background_result_for_another_lesion_does_not_replace_current_view(self):
        image, mask = sample()
        identifier = self.store.add_record(
            self.lesion, "2026-01-01", image, mask, dict(mask_reviewed=True)
        )
        result = classify_record(self.store, identifier, FixedModel(0.8), Gate())
        other = self.store.create_lesion("P02", "L01")
        self.window.lesion_id = other
        self.window.refresh_lesions()
        self.window.running = True
        self.app.busy = True
        self.window.queue.put(("visit_analysis", (identifier, result)))
        self.window.poll()
        self.assertEqual(self.window.lesion_id, other)
        self.assertIsNone(self.window.displayed_record_id)
        self.assertEqual(self.window.records, [])


if __name__ == "__main__":
    unittest.main()
