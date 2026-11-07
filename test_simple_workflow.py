"""Regresiones del recorrido persona → lesión → selección explícita."""

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from calibration import ScoreCalibration
from longitudinal_store import LongitudinalStore
from longitudinal_analysis import compare_records
from longitudinal_ui import EvolutionWindow, DateTimeFields
from longitudinal_reports import export_lesion_pdf
from test_longitudinal import sample


class SimpleWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(Path(self.temp.name) / "data")
        self.lesion = self.store.create_lesion("P01", "Brazo", "Brazo derecho")
        self.ids = []
        for month, radius in ((1, 45), (2, 50), (3, 55)):
            image, mask = sample(radius)
            self.ids.append(
                self.store.add_record(
                    self.lesion,
                    f"2026-0{month}-01",
                    image,
                    mask,
                    dict(mask_reviewed=True),
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
        self.window.set_workspace_mode("compare")
        self.root.update()

    def tearDown(self):
        self.window.running = False
        self.app.busy = False
        self.window.close()
        self.root.destroy()
        self.temp.cleanup()

    def test_person_file_opens_lesion_and_keeps_visible_context(self):
        self.assertEqual(self.window.tabs.index("current"), 2)
        self.window.open_person()
        self.root.update()
        self.assertFalse(self.window.person_panel.winfo_ismapped())
        self.assertTrue(self.window.lesion_panel.winfo_ismapped())
        self.window.people.selection_set(self.lesion)
        self.window.choose_person_lesion()
        self.root.update()
        self.assertEqual(self.window.tabs.index("current"), 0)
        self.assertIn("P01", self.window.context_label.cget("text"))
        self.assertIn("Brazo", self.window.context_label.cget("text"))

    def test_photo_selection_keeps_management_actions_and_explicit_pair_spaces(self):
        self.window.navigate(0)
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[0])
        self.assertEqual(self.window.selected_photo_ids, [self.ids[0]])
        self.assertEqual(self.window.photo_buttons["delete"].cget("state"), "normal")
        self.assertEqual(self.window.compare_button.cget("state"), "disabled")
        self.window.set_workspace_mode("compare")
        self.window.choose_comparison_photo(0, self.ids[0])
        self.window.choose_comparison_photo(1, self.ids[1])
        self.assertEqual(self.window.compare_button.cget("state"), "normal")
        self.assertEqual(self.window.photo_buttons["delete"].cget("state"), "disabled")
        self.window.select_photo(self.ids[2])
        self.assertEqual(self.window.comparison_pair, [self.ids[0], self.ids[1]])
        self.assertEqual(self.window.tabs.index("current"), 0)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 0)
        self.window.choose_comparison_photo(1, self.ids[2])
        self.assertEqual(self.window.comparison_pair, [self.ids[0], self.ids[2]])
        self.assertEqual(self.window.photo_selection_id, self.ids[0])

    def wait_for_automatic_result(self):
        deadline = time.monotonic() + 25
        while (
            self.window.auto_compare_job or self.window.running
        ) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.window.running)
        self.assertIsNone(self.window.auto_compare_job)
        self.assertNotIn("No se pudo completar", self.window.status.get())

    def test_selection_automatically_compares_and_extends_timeline(self):
        self.window.navigate(0)
        self.window.choose_comparison_photo(0, self.ids[0])
        self.window.choose_comparison_photo(1, self.ids[1])
        self.wait_for_automatic_result()
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)
        self.assertEqual(self.window.current_result["current_id"], self.ids[1])
        self.assertFalse(hasattr(self.window, "trend_reference"))
        self.assertEqual(self.window.automatic_reference_id(), self.ids[0])
        self.window.choose_comparison_photo(1, self.ids[2])
        self.wait_for_automatic_result()
        self.assertEqual(self.window.selected_photo_ids, [self.ids[0], self.ids[2]])
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 2)
        self.assertEqual(self.window.current_result["current_id"], self.ids[2])

    def test_existing_pair_is_reused_and_single_photo_remains_deletable(self):
        compare_records(self.store, *self.ids[:2])
        self.window.refresh_history()
        self.window.navigate(0)
        with patch("longitudinal_analysis.compare_records") as analyze:
            self.window.choose_comparison_photo(0, self.ids[0])
            self.window.choose_comparison_photo(1, self.ids[1])
            self.wait_for_automatic_result()
            self.window.set_workspace_mode("photos")
            self.window.select_photo(self.ids[1])
            self.wait_for_automatic_result()
            analyze.assert_not_called()
        self.assertEqual(self.window.selected_photo_ids, [self.ids[1]])
        self.assertEqual(self.window.photo_buttons["delete"].cget("state"), "normal")
        self.assertIsNone(self.window.current_result)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)

    def test_two_noninitial_photos_compare_without_an_unselected_origin(self):
        self.window.navigate(0)
        self.window.choose_comparison_photo(0, self.ids[1])
        self.window.choose_comparison_photo(1, self.ids[2])
        self.wait_for_automatic_result()
        pairs = {
            (row["previous_id"], row["current_id"])
            for row in self.store.comparisons(self.lesion)
        }
        self.assertEqual(pairs, {(self.ids[1], self.ids[2])})
        self.assertEqual(self.window.current_result["previous_id"], self.ids[1])
        self.assertEqual(self.window.current_result["current_id"], self.ids[2])
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 0)

    def test_photo_management_is_single_selection_without_background_comparison(self):
        self.window.set_workspace_mode("photos")
        self.window.navigate(0)
        self.window.select_photo(self.ids[0])
        self.window.select_photo(self.ids[1])
        self.root.update()
        self.assertEqual(self.window.selected_photo_ids, [self.ids[1]])
        self.assertIsNone(self.window.auto_compare_job)
        self.assertEqual(self.store.comparisons(self.lesion), [])
        self.assertTrue(self.window.photo_analysis_card.winfo_ismapped())
        self.assertFalse(self.window.map_holder.winfo_ismapped())
        self.assertFalse(self.window.lower_results.winfo_ismapped())
        self.assertNotIn("view", self.window.photo_buttons)
        self.assertIn("Análisis individual sin guardar", self.window.nav_buttons)

    def test_tabs_separate_pair_maps_from_full_followup(self):
        self.window.navigate(0)
        self.window.choose_comparison_photo(0, self.ids[1])
        self.window.choose_comparison_photo(1, self.ids[2])
        self.wait_for_automatic_result()
        self.root.update()
        self.assertTrue(self.window.map_holder.winfo_ismapped())
        self.assertFalse(self.window.lower_results.winfo_ismapped())
        self.assertEqual(
            self.window.selected_trend_series()["captures"],
            [
                dict(
                    target=identifier,
                    date=__import__("datetime").datetime.fromisoformat(
                        self.store.record(identifier)["captured_at"]
                    ),
                )
                for identifier in self.ids
            ],
        )
        self.window.set_workspace_mode("followup")
        self.root.update()
        self.assertTrue(self.window.lower_results.winfo_ismapped())
        self.assertFalse(self.window.map_holder.winfo_ismapped())
        self.window.compare_reference_followup()
        self.wait_for_automatic_result()
        self.assertFalse(self.window.running)
        self.assertEqual(self.window.workspace_mode, "followup")
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 2)
        self.assertEqual(self.window.comparison_pair, [self.ids[1], self.ids[2]])
        self.assertEqual(self.window.current_result["previous_id"], self.ids[1])
        self.assertEqual(self.window.current_result["current_id"], self.ids[2])

    def test_uploading_two_photos_registers_them_without_a_hidden_comparison(self):
        lesion = self.store.create_lesion("P01", "Nueva lesión")
        self.window.lesion_id = lesion
        self.window.refresh_history()
        self.window.navigate(0)
        image, mask = sample()
        with patch("longitudinal_ui.RecordEditor") as editor:
            self.window.editor(image)
            save = editor.call_args.args[2]
            save("2026-01-01", image, mask, dict(mask_reviewed=True))
            save("2026-02-01", image, mask, dict(mask_reviewed=True))
        self.wait_for_automatic_result()
        self.assertEqual(len(self.store.records(lesion)), 2)
        self.assertEqual(self.store.comparisons(lesion), [])
        self.assertIsNone(self.window.current_result)
        self.assertEqual(self.window.workspace_mode, "photos")
        self.assertEqual(self.window.comparison_pair, [None, None])

    def test_same_capture_time_does_not_fabricate_temporal_measurements(self):
        self.store.update_record_date(self.ids[1], "2026-01-01")
        self.window.refresh_history()
        self.window.navigate(0)
        self.window.choose_comparison_photo(0, self.ids[0])
        self.window.choose_comparison_photo(1, self.ids[1])
        self.wait_for_automatic_result()
        self.assertEqual(self.window.current_result["mode"], "visual")
        self.assertIsNone(self.window.current_result["change_index"])
        self.assertFalse(self.window.selected_trend_series()["points"])
        self.assertIn("Misma fecha", self.window.pair_summary.cget("text"))

    def test_plain_classification_reports_score_without_a_cancer_probability(self):
        from longitudinal_analysis import classification_summary

        explanation = classification_summary(
            dict(state="accepted", label="malignant", score=0.81)
        )
        self.assertIn("81.0 %", explanation)
        self.assertIn("patrón maligno", explanation)
        self.assertIn("no la probabilidad de tener cáncer", explanation)
        uncertain = classification_summary(dict(state="uncertain", score=0.51))
        self.assertIn("no es concluyente", uncertain)
        self.assertNotIn("clasificó esta fotografía", uncertain)
        self.assertNotIn("51.0 %", uncertain)

    def test_cache_is_invalidated_when_dates_or_model_artifact_change(self):
        from test_visit_workflow import FixedModel, Gate
        import hashlib

        self.app.model = FixedModel(0.8)
        self.app.domain_gate = Gate()
        model_path = self.app.experiment_folder / "model.keras"
        model_path.write_bytes(b"test-model-version-1")
        saved = compare_records(
            self.store,
            *self.ids[:2],
            self.app.model,
            self.app.domain_gate,
            model_path=model_path,
            calibration=self.app.calibration,
        )
        self.assertIsNotNone(self.window.cached_followup(*self.ids[:2]))
        model_path.write_bytes(b"test-model-version-2")
        self.assertIsNone(self.window.cached_followup(*self.ids[:2]))
        self.window.navigate(0)
        self.window.choose_comparison_photo(0, self.ids[0])
        self.window.choose_comparison_photo(1, self.ids[1])
        self.wait_for_automatic_result()
        self.assertEqual(
            self.window.current_result["model_sha256"],
            hashlib.sha256(model_path.read_bytes()).hexdigest(),
        )
        self.store.update_record_date(self.ids[1], "2026-02-02")
        self.assertIsNone(self.window.cached_followup(*self.ids[:2]))

    def test_compare_then_explicitly_replace_photo_preserves_longitudinal_mode(self):
        self.window.navigate(0)
        self.window.choose_comparison_photo(0, self.ids[0])
        self.window.choose_comparison_photo(1, self.ids[1])
        with patch("longitudinal_ui.messagebox.showerror") as error:
            self.window.compare_selected()
            deadline = time.monotonic() + 15
            while self.window.running and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(self.window.running)
            error.assert_not_called()
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)
        self.window.choose_comparison_photo(0, self.ids[2])
        self.wait_for_automatic_result()
        self.assertEqual(self.window.comparison_mode_key(), "longitudinal")
        self.assertEqual(
            self.window.pair_records[self.window.previous.current()]["id"], self.ids[1]
        )
        self.assertEqual(
            self.window.pair_records[self.window.current.current()]["id"], self.ids[2]
        )

    def test_delete_from_photo_selection_without_opening_history_and_restore(self):
        output = compare_records(self.store, *self.ids[:2])
        self.window.refresh_history()
        self.window.navigate(0)
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[0])
        with patch("longitudinal_actions.messagebox.askyesno", return_value=False):
            self.window.selected_photo_action("delete")
        self.assertEqual(len(self.store.records(self.lesion)), 3)
        with patch("longitudinal_actions.messagebox.askyesno", return_value=True):
            self.window.selected_photo_action("delete")
        self.root.update()
        self.assertEqual(self.window.tabs.index("current"), 0)
        self.assertEqual(len(self.store.records(self.lesion)), 2)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 0)
        self.store.restore_trash("record", self.ids[0])
        self.window.after_data_change()
        self.assertEqual(len(self.store.records(self.lesion)), 3)
        self.assertEqual(self.store.comparisons(self.lesion)[0]["id"], output["id"])

    def test_history_comparison_selection_is_passive(self):
        output = compare_records(self.store, *self.ids[:2])
        self.window.refresh_history()
        self.window.navigate(1)
        self.window.comparisons.selection_set(output["id"])
        self.root.update()
        self.assertEqual(self.window.tabs.index("current"), 1)
        self.assertIsNone(self.window.current_result)
        self.assertEqual(self.window.view_comparison_button.cget("state"), "normal")
        self.window.view_comparison_button.invoke()
        self.root.update()
        self.assertEqual(self.window.tabs.index("current"), 0)
        self.assertIsNotNone(self.window.current_result)

    def test_edit_history_date_stays_in_history_and_reorders_records(self):
        self.window.navigate(1)
        self.window.history.selection_set(self.ids[0])
        self.root.update()
        self.window.edit_history_date()
        dialog = next(
            w for w in self.window.window.winfo_children() if isinstance(w, tk.Toplevel)
        )
        dialog.date_fields.date_text.set("01/04/2026")
        button = next(
            w
            for w in dialog.winfo_children()
            if w.winfo_class() == "Button" and w.cget("text") == "Guardar fecha"
        )
        button.invoke()
        self.root.update()
        self.assertEqual(self.window.tabs.index("current"), 1)
        self.assertEqual(self.store.records(self.lesion)[-1]["id"], self.ids[0])
        self.assertEqual(self.window.history.selection(), (self.ids[0],))

    def test_table_includes_visual_and_stale_results_without_false_trend(self):
        first = compare_records(self.store, *self.ids[:2])
        compare_records(self.store, *self.ids[1:], mode="visual")
        self.store.update_record_date(self.ids[0], "2025-12-01")
        self.window.refresh_history()
        states = [
            self.window.timeline_table.item(i, "values")[2]
            for i in self.window.timeline_table.get_children()
        ]
        self.assertEqual(set(states), {"Requiere actualizarse", "Solo diferencias visuales"})
        self.assertTrue(self.window.chart_toggle.get())
        self.window.comparisons.selection_set(first["id"])
        self.assertTrue(self.store.comparisons(self.lesion)[0]["stale_dates"])

    def test_person_search_and_new_person_form_open_correct_file(self):
        self.window.person_search.set("inexistente")
        self.assertEqual(self.window.person_list.get_children(), ())
        self.window.create_person()
        dialog = next(
            w for w in self.window.window.winfo_children() if isinstance(w, tk.Toplevel)
        )
        fields = [w for w in dialog.winfo_children() if w.winfo_class() == "TEntry"]
        fields[0].insert(0, "P02")
        fields[1].insert(0, "Ana")
        button = next(w for w in dialog.winfo_children() if w.winfo_class() == "Button")
        with patch("longitudinal_ui.messagebox.showerror") as error:
            button.invoke()
            self.root.update()
            error.assert_not_called()
        self.assertEqual(self.window.patient_choice.get(), "P02")
        self.assertIsNone(self.window.lesion_id)
        self.assertEqual(self.window.records, [])
        self.assertIn("Ana", self.window.person_heading.cget("text"))
        self.assertTrue(self.window.lesion_panel.winfo_ismapped())

    def test_pdf_selected_photos_excludes_other_visits(self):
        target = Path(self.temp.name) / "selected.pdf"
        with patch.object(
            self.store, "load_images", wraps=self.store.load_images
        ) as loaded:
            pages = export_lesion_pdf(
                self.store,
                self.lesion,
                target,
                record_ids=[self.ids[0]],
                include_explanations=False,
                detailed=False,
            )
        self.assertEqual(
            [call.args[0]["id"] for call in loaded.call_args_list], [self.ids[0]]
        )
        self.assertEqual(pages, 2)
        self.assertGreater(target.stat().st_size, 1000)
        with self.assertRaises(ValueError):
            export_lesion_pdf(self.store, self.lesion, target, record_ids=["unknown"])

    def test_simple_date_entry_and_optional_hour_validate(self):
        fields = DateTimeFields(self.root, "2026-01-01")
        fields.date_text.set("29/02/2024")
        self.assertEqual(fields.get(), "2024-02-29T00:00:00")
        fields.date_text.set("29/02/2025")
        with self.assertRaises(ValueError):
            fields.get()
        fields.date_text.set("fecha inválida")
        with self.assertRaises(ValueError):
            fields.get()
        fields.destroy()

    def test_add_lesion_from_person_file_opens_empty_photo_gallery(self):
        self.window.open_person()
        self.window.create_lesion()
        dialog = next(
            w for w in self.window.window.winfo_children() if isinstance(w, tk.Toplevel)
        )
        fields = [w for w in dialog.winfo_children() if w.winfo_class() == "TEntry"]
        fields[0].insert(0, "Lesión nueva")
        fields[1].insert(0, "Espalda")
        button = next(w for w in dialog.winfo_children() if w.winfo_class() == "Button")
        with patch("longitudinal_ui.messagebox.showerror") as error:
            button.invoke()
            self.root.update()
            error.assert_not_called()
        self.assertNotEqual(self.window.lesion_id, self.lesion)
        self.assertEqual(self.window.tabs.index("current"), 0)
        self.assertEqual(self.window.records, [])
        self.assertIn("Lesión nueva", self.window.context_label.cget("text"))
        self.assertEqual(self.window.selected_photo_ids, [])

    def test_edit_person_keeps_lesion_and_its_photos(self):
        self.window.open_person()
        self.window.edit_current_person()
        dialog = next(
            w for w in self.window.window.winfo_children() if isinstance(w, tk.Toplevel)
        )
        fields = [w for w in dialog.winfo_children() if w.winfo_class() == "TEntry"]
        fields[1].insert(0, "Nombre editado")
        button = next(w for w in dialog.winfo_children() if w.winfo_class() == "Button")
        button.invoke()
        self.root.update()
        self.assertEqual(self.window.lesion_id, self.lesion)
        self.assertEqual(len(self.window.records), 3)
        self.assertIn("Nombre editado", self.window.person_heading.cget("text"))
        self.assertEqual(self.window.tabs.index("current"), 2)

    def test_camera_registration_waits_for_running_analysis(self):
        self.app.busy = True
        with patch("longitudinal_capture.FollowupCaptureDialog") as dialog:
            self.window.capture_in_lesion()
            dialog.assert_not_called()
        self.assertEqual(len(self.store.records(self.lesion)), 3)
        self.app.busy = False

    def test_camera_capture_uses_dedicated_review_before_editor(self):
        with patch(
            "longitudinal_capture.FollowupCaptureDialog"
        ) as dialog, patch.object(self.window, "editor") as editor:
            self.window.capture_in_lesion()
            editor.assert_not_called()
            dialog.assert_called_once_with(self.window, "camera", None, None)

    def test_pdf_dialog_exports_selected_photo_with_explicit_scope(self):
        self.window.navigate(0)
        self.window.set_workspace_mode("photos")
        self.window.select_photo(self.ids[0])
        self.window.export_pdf()
        dialog = next(
            w for w in self.window.window.winfo_children() if isinstance(w, tk.Toplevel)
        )
        radio = next(
            w
            for w in dialog.winfo_children()
            if w.winfo_class() == "TRadiobutton" and w.cget("value") == "selected"
        )
        radio.invoke()
        button = next(
            w for w in dialog.winfo_children() if w.winfo_class() == "TButton"
        )
        target = Path(self.temp.name) / "ui-report.pdf"
        with patch(
            "longitudinal_actions.filedialog.asksaveasfilename",
            return_value=str(target),
        ), patch("longitudinal_actions.messagebox.showinfo") as info:
            button.invoke()
            self.assertIn("2 páginas", info.call_args.args[1])
        self.assertTrue(target.exists())

    def test_chart_is_optional_and_can_be_shown_and_hidden(self):
        result = compare_records(self.store, *self.ids[:2])
        self.window.refresh_history()
        self.window.comparisons.selection_set(result["id"])
        self.window.restore_comparison()
        self.window.set_workspace_mode("followup")
        self.root.update()
        self.assertTrue(self.window.chart.winfo_ismapped())
        self.window.chart_toggle.set(True)
        self.window.toggle_chart()
        self.root.update()
        self.assertTrue(self.window.chart.winfo_ismapped())
        self.assertIn("Resultado", self.window.chart_heading.cget("text"))
        self.window.chart_toggle.set(False)
        self.window.toggle_chart()
        self.root.update()
        self.assertFalse(self.window.chart.winfo_ismapped())
        self.assertIn("referencia", self.window.chart_note.cget("text"))


if __name__ == "__main__":
    unittest.main()
