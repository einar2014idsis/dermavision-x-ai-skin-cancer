"""Pruebas de mediciones reales, referencia única y exportación con alcance explícito."""

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from longitudinal_store import LongitudinalStore
from longitudinal_analysis import compare_records
from longitudinal_reports import export_lesion_pdf
from longitudinal_insights import (
    trend_series,
    measurement_rows,
    comparison_narrative,
    quality_rows,
    comparison_readiness,
)
from longitudinal_insights import trend_direction, trend_figure
from datetime import datetime
from longitudinal_ui import EvolutionWindow
from test_longitudinal import sample
from test_visit_workflow import FixedModel, Gate
from calibration import ScoreCalibration


class InsightsTests(unittest.TestCase):
    def test_readiness_distinguishes_temporal_and_visual_results(self):
        title, detail = comparison_readiness(dict(mode="longitudinal", comparable=True))
        self.assertEqual(title, "COMPARABLE")
        self.assertIn("imagen", detail)
        title, detail = comparison_readiness(
            dict(
                mode="visual",
                comparable=False,
                visual_available=True,
                fallback_reason="Iluminación distinta.",
                registration=dict(accepted=True, framing_accepted=True),
                color_normalization=dict(accepted=False),
            )
        )
        self.assertEqual(title, "SOLO DIFERENCIAS VISUALES")
        self.assertIn("Iluminación distinta.", detail)
        self.assertEqual(
            comparison_readiness(
                dict(mode="longitudinal", comparable=True), stale=True
            )[0],
            "RECALCULAR",
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(Path(self.temp.name) / "data")
        self.lesion = self.store.create_lesion("DEMO", "Lesión sintética")
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

    def tearDown(self):
        self.temp.cleanup()

    def test_evolution_excludes_other_references_visual_and_stale(self):
        first = compare_records(self.store, self.ids[0], self.ids[1])
        compare_records(self.store, self.ids[1], self.ids[2])
        compare_records(self.store, self.ids[0], self.ids[2], mode="visual")
        series = trend_series(
            self.store.comparisons(self.lesion),
            self.store.records(self.lesion),
            self.ids[0],
            "area",
        )
        self.assertEqual(len(series["points"]), 1)
        self.assertEqual(series["points"][0]["target"], self.ids[1])
        self.assertAlmostEqual(
            series["points"][0]["value"], first["result"]["changes"]["area"]
        )
        self.assertEqual(series["excluded"]["other_reference"], 1)
        self.assertEqual(series["excluded"]["visual"], 1)
        self.store.update_record_date(self.ids[0], "2025-12-01")
        series = trend_series(
            self.store.comparisons(self.lesion),
            self.store.records(self.lesion),
            self.ids[0],
        )
        self.assertFalse(series["points"])
        self.assertEqual(series["excluded"]["stale"], 1)
        self.assertEqual(series["excluded"]["visual"], 1)

    def test_before_after_uses_aligned_features_and_explains_units(self):
        result = compare_records(self.store, *self.ids[:2])["result"]
        rows = measurement_rows(result)
        self.assertAlmostEqual(
            float(rows[0][1]), result["features_previous"]["area_px"]
        )
        self.assertIn("%", rows[0][3])
        self.assertIn("mm²", rows[0][4])
        self.assertNotEqual(rows[4][1], "—")
        self.assertIn("H=", rows[5][1])
        self.assertIn("área aparente", comparison_narrative(result))
        self.assertIn("Recalcula", comparison_narrative(result, True))

    def test_visual_area_remains_coverage_and_quality_retains_failure(self):
        with patch(
            "longitudinal_analysis.align",
            return_value=(None, dict(accepted=False, matches=3)),
        ):
            result = compare_records(self.store, *self.ids[:2], fallback_visual=True)[
                "result"
            ]
        self.assertEqual(result["mode"], "visual")
        self.assertEqual(result["registration"]["matches"], 3)
        self.assertIn("pp", measurement_rows(result)[0][3])
        self.assertIn("%", measurement_rows(result)[0][1])
        self.assertIn("no se confirmó", comparison_narrative(result))
        quality = dict(quality_rows(result, self.store.records(self.lesion)))
        self.assertEqual(quality["Correspondencias en la piel"], "3")

    def test_pdf_comparison_cannot_export_unselected_photographs(self):
        saved = compare_records(self.store, *self.ids[:2])
        target = Path(self.temp.name) / "report.pdf"
        with self.assertRaisesRegex(ValueError, "dos fotografías"):
            export_lesion_pdf(
                self.store, self.lesion, target, saved["id"], record_ids=[self.ids[0]]
            )
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError, "referencia"):
            export_lesion_pdf(
                self.store,
                self.lesion,
                target,
                record_ids=self.ids[:2],
                reference_id=self.ids[2],
            )

    def test_pdf_failure_preserves_existing_file(self):
        target = Path(self.temp.name) / "report.pdf"
        target.write_bytes(b"original")
        self.store.save_record_analysis(
            self.ids[0],
            dict(state="accepted", score=0.8, label="malignant"),
            Image.new("RGB", (224, 224), "orange"),
        )
        record = self.store.record(self.ids[0])
        self.store.path(
            record["metadata"]["classification"]["explanation"]["path"]
        ).write_bytes(b"corrupt")
        with self.assertRaises(ValueError):
            export_lesion_pdf(self.store, self.lesion, target, record_ids=[self.ids[0]])
        self.assertEqual(target.read_bytes(), b"original")

    def test_direction_describes_visual_distance_without_clinical_labels(self):
        points = [
            dict(value=20.0, date=datetime(2026, 2, 1)),
            dict(value=30.0, date=datetime(2026, 3, 1)),
        ]
        series = dict(points=points)
        self.assertIn("Aumentó índice descriptivo", trend_direction(series))
        points[-1]["value"] = 10.0
        self.assertIn("Disminuyó índice descriptivo", trend_direction(series))
        points[-1]["value"] = 20.01
        self.assertIn("Mismo valor mostrado para índice descriptivo", trend_direction(series))
        for forbidden in ("mejoró", "empeoró", "benigna", "maligna"):
            self.assertNotIn(forbidden, trend_direction(series))

    def test_timeline_is_a_line_and_does_not_bridge_missing_measurements(self):
        saved = compare_records(self.store, self.ids[0], self.ids[2])
        series = trend_series(
            self.store.comparisons(self.lesion),
            self.store.records(self.lesion),
            self.ids[0],
            "index",
        )
        figure = trend_figure(series)
        ax = figure.axes[0]
        self.assertFalse(ax.patches)  # no bars
        self.assertEqual(
            len(
                [
                    line
                    for line in ax.lines
                    if len(line.get_xdata()) > 1 and line.get_color() == "#635bdb"
                ]
            ),
            0,
        )
        self.assertIn("Sin medición", [label.get_text() for label in ax.texts])
        self.assertEqual(
            len(series["points"]), 1
        )  # the origin is not a measured comparison
        compare_records(self.store, self.ids[0], self.ids[1])
        figure = trend_figure(
            trend_series(
                self.store.comparisons(self.lesion),
                self.store.records(self.lesion),
                self.ids[0],
                "index",
            )
        )
        self.assertEqual(
            len(
                [line for line in figure.axes[0].lines if line.get_color() == "#635bdb"]
            ),
            2,
        )

    def test_timeline_keeps_visits_when_no_measurement_is_valid(self):
        series = trend_series(
            [], self.store.records(self.lesion), self.ids[0], "index"
        )
        figure = trend_figure(series)
        labels = [label.get_text() for label in figure.axes[0].texts]
        self.assertIn("Inicio", labels)
        self.assertGreaterEqual(labels.count("Sin medición"), 2)
        self.assertEqual(len(figure.timeline_points), 3)


class DetailWindowTests(InsightsTests):
    # Inherits the data cases too; these UI cases verify the actual entry points.
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = SimpleNamespace(
            root=self.root,
            busy=False,
            model=None,
            domain_gate=None,
            reference_index=None,
            calibration=ScoreCalibration(),
            experiment_folder=Path(self.temp.name),
            refresh_actions=lambda: None,
        )
        self.window = EvolutionWindow(self.app, self.store)
        self.window.navigate(0)
        self.root.update()

    def tearDown(self):
        self.window.close()
        self.root.destroy()
        super().tearDown()

    def test_playback_stays_in_followup_and_stops_on_navigation(self):
        self.window.set_workspace_mode("followup")
        self.window.toggle_evolution_playback()
        self.root.update()
        self.assertTrue(self.window.evolution_playing)
        self.assertEqual(self.window.workspace_mode, "followup")
        self.assertTrue(self.window.playback_preview.cget("image"))
        self.window.set_workspace_mode("photos")
        self.assertFalse(self.window.evolution_playing)
        self.assertIsNone(self.window.evolution_job)

    def test_entering_followup_calculates_pending_pairs(self):
        self.window.set_workspace_mode("followup")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            self.root.update()
            if len(self.store.comparisons(self.lesion)) == 2 and not self.window.running:
                break
            time.sleep(.01)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 2)
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 2)

    def test_detailed_graphs_are_optional_and_comparison_has_conclusion(self):
        self.window.set_workspace_mode("followup")
        self.root.update()
        self.assertFalse(self.window.followup_graph.winfo_ismapped())
        self.window.toggle_followup_graph()
        self.root.update()
        self.assertTrue(self.window.followup_graph.winfo_ismapped())
        self.window.toggle_followup_graph()
        saved = compare_records(self.store, *self.ids[:2])
        self.window.refresh_history()
        self.window.show_result(saved["result"])
        self.root.update()
        self.assertTrue(self.window.conclusion_card.winfo_ismapped())
        self.assertIn("Estado:", self.window.conclusion_text.cget("text"))

    def test_heatmap_is_visible_on_selection_and_can_be_amplified(self):
        self.store.save_record_analysis(
            self.ids[0],
            dict(state="accepted", score=0.8, label="malignant"),
            Image.new("RGB", (224, 224), "orange"),
        )
        self.window.refresh_history()
        self.window.select_photo(self.ids[0])
        self.root.update()
        self.assertTrue(self.window.photo_analysis_card.winfo_ismapped())
        self.assertEqual(len(self.window.heatmap_sources), 2)
        self.assertIn("80.0", self.window.result_explanation.cget("text"))
        self.window.open_photo_explanation()
        self.root.update()
        self.assertTrue(
            any(
                isinstance(w, tk.Toplevel)
                and w.title() == "Explicación visual por oclusión"
                for w in self.window.window.winfo_children()
            )
        )

    def test_missing_map_offers_generation_without_fabrication(self):
        self.window.select_photo(self.ids[0])
        self.root.update()
        self.assertEqual(len(self.window.heatmap_sources), 1)
        self.assertIn("Generar", self.window.heatmap_button.cget("text"))
        self.assertIn("No hay mapa", self.window.heatmap_text.cget("text"))
        with patch.object(self.window, "classify_visit") as classify:
            self.window.generate_photo_explanation()
            classify.assert_called_once_with(self.ids[0])

    def test_common_reference_batch_saves_two_comparisons_and_opens_detail(self):
        self.window.set_workspace_mode("followup")
        self.window.compare_reference_followup()
        deadline = time.monotonic() + 25
        with patch("longitudinal_ui.messagebox.showerror") as error:
            while (
                self.window.running or getattr(self.window, "followup_pending", [])
            ) and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(self.window.running)
            error.assert_not_called()
        rows = self.store.comparisons(self.lesion)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["previous_id"] for r in rows}, {self.ids[0]})
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 2)
        self.assertEqual(self.window.comparison_pair, [None, None])
        self.assertIsNone(self.window.current_result)
        self.assertEqual(self.window.workspace_mode, "followup")
        self.window.comparisons.selection_set(rows[0]["id"])
        self.window.restore_comparison()
        self.window.open_analysis_detail()
        self.root.update()
        self.assertEqual(
            self.window.analysis_dialog.title(), "DermaVision-X · Análisis detallado"
        )

    def test_graph_opens_capture_and_keeps_reference_and_history(self):
        for target in self.ids[1:]:
            compare_records(self.store, self.ids[0], target)
        self.window.refresh_history()
        self.window.set_workspace_mode("followup")
        self.window.chart_toggle.set(True)
        self.window.toggle_chart()
        self.root.update()
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 2)
        self.assertIn(
            "Se registraron 3 fotografías", self.window.period_summary.cget("text")
        )
        self.assertIn(
            "Mediciones disponibles: 2", self.window.period_summary.cget("text")
        )
        left, right, top, bottom, target = self.window.trend_hit_regions[-1]
        self.window.open_trend_capture(
            SimpleNamespace(x=(left + right) / 2, y=(top + bottom) / 2)
        )
        self.root.update()
        self.assertEqual(self.window.selected_photo_ids, [target])
        self.assertEqual(
            self.window.selected_trend_series()["reference"]["id"], self.ids[0]
        )
        self.assertEqual(len(self.window.selected_trend_series()["points"]), 2)
        self.assertEqual(self.window.workspace_mode, "photos")
        self.assertFalse(self.window.lower_results.winfo_ismapped())
        self.assertTrue(self.window.photo_analysis_card.winfo_ismapped())
        self.assertTrue(hasattr(self.window, "trend_metric"))
        self.assertEqual(self.window.selected_trend_series()["metric"], "index")

    def test_heatmap_toggle_does_not_change_saved_artifact(self):
        self.store.save_record_analysis(
            self.ids[0],
            dict(state="accepted", score=0.8, label="malignant"),
            Image.new("RGB", (224, 224), "yellow"),
        )
        before = self.store.record(self.ids[0])["metadata"]["classification"][
            "explanation"
        ]
        self.window.refresh_history()
        self.window.select_photo(self.ids[0])
        self.root.update()
        self.window.heatmap_overlay.set(False)
        self.window.render_photo_analysis()
        self.assertIn("desactivada", self.window.heatmap_captions[1].cget("text"))
        self.assertEqual(
            before,
            self.store.record(self.ids[0])["metadata"]["classification"]["explanation"],
        )

    def test_individual_selection_preserves_pair_and_observations_are_optional(self):
        saved = compare_records(self.store, *self.ids[:2])
        self.window.refresh_history()
        self.window.show_result(saved["result"])
        self.root.update()
        self.assertEqual(self.window.comparison_pair, self.ids[:2])
        period = self.window.period_summary.cget("text")
        self.window.show_visit(self.ids[2])
        self.root.update()
        self.assertEqual(self.window.comparison_pair, self.ids[:2])
        self.assertEqual(self.window.photo_selection_id, self.ids[2])
        self.assertEqual(self.window.period_summary.cget("text"), period)
        self.assertFalse(self.window.report.winfo_ismapped())
        self.window.toggle_report_details()
        self.root.update()
        self.assertTrue(self.window.report.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
