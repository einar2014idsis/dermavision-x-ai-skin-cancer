import csv
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from longitudinal_store import LongitudinalStore
from longitudinal_analysis import compare_images, compare_records, suggest_mask
from longitudinal_ui import EvolutionWindow, RecordEditor


def sample(radius=45, seed=5):
    rng = np.random.default_rng(seed)
    # Piel sintética texturada, compartida entre fechas salvo la lesión.
    texture = rng.normal(0, 13, (400, 400, 1))
    rgb = np.uint8(np.clip(np.full((400, 400, 3), (185, 145, 120)) + texture, 0, 255))
    for _ in range(150):
        point = tuple(int(v) for v in rng.integers(18, 382, 2))
        cv2.circle(rgb, point, 2, (120, 90, 65), -1)
    mask = np.zeros((400, 400), "uint8")
    cv2.circle(mask, (200, 200), radius, 255, -1)
    rgb[mask > 0] = (85, 58, 40)
    return Image.fromarray(rgb), Image.fromarray(mask)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(self.temp.name)
        self.lesion = self.store.create_lesion("P01", "L01", "Brazo")
        self.photo, self.mask = sample()

    def tearDown(self):
        self.temp.cleanup()

    def add(self, date="2026-01-01", lesion=None):
        return self.store.add_record(
            lesion or self.lesion, date, self.photo, self.mask, dict(mask_reviewed=True)
        )

    def test_persistence_and_chronological_labels(self):
        later = self.add("2026-02-01")
        earlier = self.add("2026-01-01")
        reopened = LongitudinalStore(self.temp.name)
        rows = reopened.records(self.lesion)
        self.assertEqual([r["id"] for r in rows], [earlier, later])
        self.assertEqual([r["label"] for r in rows], ["T0", "T1"])
        images = reopened.load_images(rows[0])
        np.testing.assert_array_equal(images[0], self.photo)

    def test_reject_cross_lesion_same_date_reverse_and_self(self):
        first = self.add()
        second = self.add("2026-02-01")
        other = self.add("2026-03-01", self.store.create_lesion("P02", "L01"))
        equal_date = self.add()
        for a, b in [
            (first, other),
            (second, first),
            (first, first),
            (first, equal_date),
        ]:
            with self.assertRaises(ValueError):
                self.store.pair(a, b)

    def test_requires_review_and_valid_mask_date(self):
        for date, mask, meta in [
            ("bad", self.mask, dict(mask_reviewed=True)),
            ("2026-01-01", self.mask, {}),
            ("2026-01-01", Image.new("L", self.photo.size), dict(mask_reviewed=True)),
        ]:
            with self.assertRaises(ValueError):
                self.store.add_record(self.lesion, date, self.photo, mask, meta)
        self.assertEqual(self.store.records(self.lesion), [])

    def test_integrity_and_path_traversal(self):
        row = self.store.record(self.add())
        self.store.path(row["image"]).write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            self.store.load_images(row)
        with self.assertRaises(ValueError):
            self.store.path("../outside.png")

    def test_comparison_and_export_keep_ground_truth_empty(self):
        first = self.add()
        second = self.add("2026-02-01")
        output = compare_records(self.store, first, second)
        self.assertTrue(output["result"]["comparable"])
        destination = Path(self.temp.name) / "export"
        self.assertEqual(self.store.export(destination), (2, 1))
        with (destination / "pairs.csv").open(encoding="utf-8-sig") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual(row["reference_diagnosis"], "")
        self.assertEqual(row["model_b_trained"], "False")
        self.assertEqual(row["patient_id"], "P01")
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)


class MeasurementTests(unittest.TestCase):
    def test_identical_pair_has_near_zero_change(self):
        image, mask = sample()
        result, _, _ = compare_images(image, image, mask, mask)
        self.assertTrue(result["comparable"], result)
        self.assertLess(result["change_index"], 1)

    def test_detects_growth_without_using_lesion_for_alignment(self):
        old, mask0 = sample(40)
        new, mask1 = sample(52)
        result, _, _ = compare_images(old, new, mask0, mask1)
        self.assertTrue(result["comparable"], result)
        self.assertGreater(result["changes"]["area"], 60)
        self.assertLess(result["changes"]["area"], 80)

    def test_translation_rotation_and_scale_not_reported_as_growth(self):
        image, mask = sample()
        transform = cv2.getRotationMatrix2D((200, 200), 8, 1.08)
        transform[:, 2] += (4, -5)
        shifted = Image.fromarray(
            cv2.warpAffine(np.asarray(image), transform, (400, 400))
        )
        shifted_mask = Image.fromarray(
            cv2.warpAffine(
                np.asarray(mask), transform, (400, 400), flags=cv2.INTER_NEAREST
            )
        )
        result, _, _ = compare_images(image, shifted, mask, shifted_mask)
        self.assertTrue(result["comparable"], result)
        self.assertLess(abs(result["changes"]["area"]), 4)

    def test_no_skin_correspondence_abstains(self):
        image, mask = sample()
        plain = Image.new("RGB", image.size, (150, 110, 95))
        result, _, _ = compare_images(image, plain, mask, mask)
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["change_index"])

    def test_unreviewed_and_rejected_never_get_index(self):
        image, mask = sample()
        for options in [
            dict(reviewed=False),
            dict(current_classification=dict(state="rejected", score=None)),
        ]:
            result, _, _ = compare_images(image, image, mask, mask, **options)
            self.assertFalse(result["comparable"])
            self.assertIsNone(result["change_index"])

    def test_deep_features_recorded_separately(self):
        image, mask = sample()

        def extractor(images, training=False):
            return SimpleNamespace(
                numpy=lambda: np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]])
            )

        result, _, _ = compare_images(
            image, image, mask, mask, extractor=extractor, model_sha256="test"
        )
        self.assertLess(result["deep_cosine_distance"], 1e-10)
        self.assertEqual(len(result["embeddings"]), 2)
        self.assertEqual(result["model_sha256"], "test")

    def test_mask_suggestion_preserves_size(self):
        image, _ = sample()
        mask = suggest_mask(image)
        self.assertEqual(mask.size, image.size)
        self.assertGreater(np.asarray(mask).sum(), 0)


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(self.temp.name)
        self.app = SimpleNamespace(
            root=self.root,
            busy=False,
            model=None,
            domain_gate=None,
            reference_index=None,
            experiment_folder=Path("runs/functional-02"),
            refresh_actions=lambda: None,
        )
        from calibration import ScoreCalibration

        self.app.calibration = ScoreCalibration()
        self.window = EvolutionWindow(self.app, self.store)

    def test_single_comparison_and_large_map_are_explained(self):
        lesion = self.store.create_lesion("P01", "L01")
        ids = []
        for date, radius in [("2026-01-01", 45), ("2026-02-01", 58)]:
            image, mask = sample(radius)
            ids.append(
                self.store.add_record(
                    lesion, date, image, mask, dict(mask_reviewed=True)
                )
            )
        output = compare_records(self.store, *ids)
        self.assertTrue(output["result"]["comparable"])
        self.window.refresh_lesions()
        self.window.comparisons.selection_set(output["id"])
        self.window.restore_comparison()
        self.root.update()
        self.assertEqual(
            self.window.chart_heading.cget("text"), "Resultado de una comparación"
        )
        self.assertIn("Otra captura evaluable", self.window.trend_status.cget("text"))
        series = self.window.selected_trend_series()
        self.assertEqual(series["reference"]["id"], ids[0])
        self.assertEqual(series["points"][0]["target"], ids[1])
        self.assertEqual(len(self.window.photos), 3)
        self.assertGreater(self.window.photos[2].width(), 250)
        self.assertGreater(self.window.photos[2].height(), 250)
        self.assertNotIn("anterior si", self.window.picture_widgets[2][0].cget("text"))
        self.assertEqual(self.window.image_sources[2].size, output["overlay"].size)
        self.window.map_zoom.set(False)
        self.window.render_images()
        self.assertEqual(
            self.window.difference_map_image().size, output["overlay"].size
        )

    def test_navigation_and_empty_state(self):
        self.root.update()
        self.assertNotIn("Inicio", self.window.nav_buttons)
        self.assertEqual(self.window.tabs.index("current"), 2)
        self.assertIn("primera", self.window.flow_hint.cget("text"))
        self.window.navigate(0)
        self.assertEqual(self.window.tabs.index("current"), 2)
        self.assertFalse(self.window.result_cards[0].winfo_ismapped())
        self.window.navigate(2)
        self.assertEqual(self.window.heading.cget("text"), "Personas y lesiones")
        self.assertIn("códigos", self.window.subtitle.cget("text"))
        self.window.open_individual()
        self.root.update()
        self.assertEqual(self.window.window.state(), "withdrawn")
        self.assertEqual(self.root.state(), "normal")

    def tearDown(self):
        self.window.running = False
        self.window.close()
        self.root.destroy()
        self.temp.cleanup()

    def test_history_comparison_restore_and_visible_widgets(self):
        lesion = self.store.create_lesion("P01", "L01")
        image, mask = sample()
        ids = [
            self.store.add_record(
                lesion, f"2026-0{i+1}-01", image, mask, dict(mask_reviewed=True)
            )
            for i in range(2)
        ]
        output = compare_records(self.store, *ids)
        self.window.refresh_lesions()
        self.root.update()
        self.assertEqual(len(self.window.history.get_children()), 2)
        self.assertEqual(len(self.window.comparisons.get_children()), 1)
        self.window.comparisons.selection_set(output["id"])
        self.window.restore_comparison()
        self.root.update()
        self.assertIn("Índice de cambio", self.window.report.get("1.0", "end"))
        self.assertEqual(len(self.window.photos), 3)

    def test_record_editor_manual_contour_and_save(self):
        image, _ = sample()
        saved = []
        editor = RecordEditor(
            self.window.window, image, lambda *args: saved.append(args)
        )
        editor.clear()
        editor.points = [(150, 150), (250, 150), (250, 250), (150, 250)]
        editor.finish()
        self.assertIsNotNone(editor.mask)
        editor.reviewed.set(True)
        editor.commit()
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0][3]["mask_reviewed"])

    def test_background_comparison_finishes_and_restores_app(self):
        lesion = self.store.create_lesion("P01", "L01")
        image, mask = sample()
        for date in ("2026-01-01", "2026-02-01"):
            self.store.add_record(lesion, date, image, mask, dict(mask_reviewed=True))
        self.window.refresh_lesions()
        with patch("longitudinal_ui.messagebox.showerror") as error:
            self.window.set_workspace_mode("compare")
            for side, record in enumerate(self.store.records(lesion)):
                self.window.choose_comparison_photo(side, record["id"])
            deadline = time.monotonic() + 15
            while (
                self.window.running or self.window.auto_compare_job
            ) and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            error.assert_not_called()
        self.assertFalse(self.window.running)
        self.assertFalse(self.app.busy)
        self.assertEqual(len(self.window.saved_comparisons), 1)
        self.assertEqual(len(self.window.photos), 3)
        self.assertIn("Índice de cambio", self.window.report.get("1.0", "end"))

    def test_patient_filter_keeps_lesions_separate(self):
        a = self.store.create_lesion("P01", "L01")
        b = self.store.create_lesion("P02", "L02")
        self.window.refresh_lesions()
        self.window.patient_choice.set("P02")
        self.window.filter_patient()
        self.assertEqual(self.window.lesion_id, b)
        self.assertEqual(len(self.window.visible_lesions), 1)
        person = next(p for p in self.store.persons() if p["code"] == "P01")
        self.window.person_list.selection_set(person["id"])
        self.window.select_person()
        self.window.people.selection_set(a)
        self.window.choose_person_lesion()
        self.assertEqual(self.window.lesion_id, a)
        self.assertEqual(self.window.patient_choice.get(), "P01")

    def dialog_widgets(self, title):
        dialog = next(
            w
            for w in self.window.window.winfo_children()
            if isinstance(w, tk.Toplevel) and w.title() == title
        )
        entries = [w for w in dialog.winfo_children() if w.winfo_class() == "TEntry"]
        save = next(
            w
            for w in dialog.winfo_children()
            if w.winfo_class() == "Button" and w.cget("text").startswith("Guardar")
        )
        return dialog, entries, save

    def test_person_dialog_save_edit_and_associate_lesion(self):
        self.window.create_person()
        dialog, entries, save = self.dialog_widgets("Registrar persona")
        for entry, value in zip(entries, ["P01", "Persona prueba", "Observacion"]):
            entry.insert(0, value)
        save.invoke()
        self.root.update()
        person = self.store.persons()[0]
        self.assertEqual(person["name"], "Persona prueba")
        self.assertEqual(person["lesion_count"], 0)
        self.assertIsNone(self.window.lesion_id)
        self.assertEqual(self.window.person_list.get_children(), (person["id"],))
        self.window.create_lesion()
        dialog, entries, save = self.dialog_widgets("Registrar lesión")
        entries[0].insert(0, "L01")
        entries[1].insert(0, "Brazo")
        save.invoke()
        self.root.update()
        lesion = self.store.lesions(person["id"])[0]
        self.assertEqual(self.window.lesion_id, lesion["id"])
        self.window.edit_person()
        dialog, entries, save = self.dialog_widgets("Editar persona")
        entries[0].delete(0, "end")
        entries[0].insert(0, "P02")
        save.invoke()
        self.root.update()
        self.assertEqual(self.store.person(person["id"])["code"], "P02")
        self.assertEqual(self.store.lesions()[0]["id"], lesion["id"])
        self.assertEqual(self.window.patient_choice.get(), "P02")
        self.assertEqual(self.window.person_list.item(person["id"], "values")[2], "1")

    def test_person_without_lesions_clears_other_history_and_syncs_selection(self):
        lesion = self.store.create_lesion("P01", "L01")
        image, mask = sample()
        self.store.add_record(
            lesion, "2026-01-01", image, mask, dict(mask_reviewed=True)
        )
        empty = self.store.create_person("P02")
        self.window.refresh_lesions()
        self.root.update()
        self.assertEqual(len(self.window.records), 1)
        self.window.patient_choice.set("P02")
        self.window.filter_patient()
        self.root.update()
        self.assertEqual(self.window.person_list.selection(), (empty,))
        self.assertIsNone(self.window.lesion_id)
        self.assertEqual(self.window.records, [])
        self.assertEqual(self.window.people.get_children(), ())
        self.assertEqual(self.window.history.get_children(), ())
        self.assertIsNone(self.window.current_result)

    def test_unevaluable_pair_explains_reason_and_is_not_zero_change(self):
        reason = "No se encontró suficiente correspondencia en la piel alrededor. No se cuantifica el cambio."
        result = dict(
            comparable=False,
            change_index=None,
            change_level="No evaluable",
            current_classification=dict(state="unavailable", score=None),
            warnings=[reason],
        )
        self.window.saved_comparisons = [
            dict(
                id="invalid-test",
                previous_id="missing-a",
                current_id="missing-b",
                result=result,
            )
        ]
        self.window.update_dashboard_result(result)
        self.window.draw_timeline()
        self.assertEqual(self.window.change_values["area"].cget("text"), "No medido")
        self.assertIn(reason, self.window.comparison_note.cget("text"))
        self.assertIn("no significa", self.window.comparison_note.cget("text"))
        self.assertEqual(self.window.overlay_check.cget("state"), "disabled")
        self.assertFalse(self.window.overlay_mode.get())
        self.assertIn(
            "Sin mediciones temporales válidas", self.window.trend_status.cget("text")
        )
        self.assertFalse(self.window.selected_trend_series()["points"])
        self.assertEqual(self.window.selected_trend_series()["excluded"]["invalid"], 1)

    def test_unaligned_visual_differences_are_displayed_with_distinct_units(self):
        result = dict(
            comparable=False,
            change_index=None,
            change_level="No evaluable",
            current_classification=dict(state="unavailable", score=None),
            warnings=["Falta alineación."],
            visual_differences=dict(
                area_coverage_pp=8.17,
                shape=0.322,
                asymmetry=0.046,
                border=0.345,
                color=21.5,
                texture=0.144,
            ),
        )
        self.window.update_dashboard_result(result)
        self.assertIn("8.17 pp", self.window.change_values["area"].cget("text"))
        self.assertEqual(self.window.change_values["shape"].cget("text"), "0.322")
        self.assertEqual(self.window.index_value.cget("text"), "Sin alineación")
        self.assertIn("no crecimiento", self.window.comparison_note.cget("text"))

    def test_cards_show_results_and_clear_when_pair_changes(self):
        lesion = self.store.create_lesion("P01", "L01")
        image, mask = sample()
        ids = [
            self.store.add_record(lesion, date, image, mask, dict(mask_reviewed=True))
            for date in ["2026-01-01", "2026-02-01"]
        ]
        output = compare_records(self.store, *ids)
        output["result"]["current_classification"] = dict(state="accepted", score=0.8)
        self.window.refresh_lesions()
        self.window.show_result(output["result"])
        self.window.navigate(0)
        self.root.update()
        self.assertEqual(self.window.malignant_value.cget("text"), "80.0 %")
        self.assertEqual(self.window.benign_value.cget("text"), "20.0 %")
        self.assertIn("/ 100", self.window.index_value.cget("text"))
        later = self.store.add_record(
            lesion, "2026-03-01", image, mask, dict(mask_reviewed=True)
        )
        self.window.refresh_history()
        self.window.choose_comparison_photo(1, later)
        self.root.update()
        self.assertIsNone(self.window.current_result)
        self.assertEqual(self.window.malignant_value.cget("text"), "— %")
        self.assertEqual(len(self.window.photos), 2)

    def test_similarity_search_removed_from_followup(self):
        self.assertFalse(hasattr(self.window, "reference_cards"))
        self.assertFalse(hasattr(self.window, "search_similar"))
        self.assertTrue(hasattr(self.window, "open_analysis_detail"))

    def test_result_finishes_without_waiting_for_similarity_search(self):
        lesion = self.store.create_lesion("P01", "L01")
        image, mask = sample()
        ids = [
            self.store.add_record(lesion, date, image, mask, dict(mask_reviewed=True))
            for date in ["2026-01-01", "2026-02-01"]
        ]
        payload = compare_records(self.store, *ids)
        payload["references_pending"] = True
        payload["result"]["current_classification"] = dict(state="accepted", score=0.8)
        self.window.active_lesion_id = lesion
        self.window.queue.put(("ok", payload))
        self.window.poll()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.window.malignant_value.cget("text"), "80.0 %")
        self.assertFalse(self.window.running)
        self.assertIsNotNone(self.window.current_result)


if __name__ == "__main__":
    unittest.main()
