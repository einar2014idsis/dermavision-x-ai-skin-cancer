"""Reports must not revive invalid values or overcount repeated analyses."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image

from longitudinal_reports import report_comparison_state, report_overview, report_photo_state, selected_followup_summary
from longitudinal_pdf import ReportPages, export_readable_pdf
from longitudinal_insights import trend_series
from test_followup_summary import record, comparison
from types import SimpleNamespace


class ReportSafeguardsTests(unittest.TestCase):
    def setUp(self):
        self.records = [record("A", "2026-01-01"), record("B", "2026-02-01")]
        self.row = comparison(*self.records)

    def test_rejected_result_never_reuses_residual_index(self):
        self.row["result"].update(comparable=False, warnings=["Enfoque insuficiente."])
        state = report_comparison_state(self.row, self.records)
        self.assertEqual(state["kind"], "rejected")
        self.assertIsNone(state["value"])
        self.assertFalse(state["show_map"])
        self.assertIn("Enfoque", state["reason"])

    def test_visual_index_is_not_a_temporal_measurement(self):
        self.row["result"].update(mode="visual", comparable=False, visual_available=True, visual_index=65)
        state = report_comparison_state(self.row, self.records)
        self.assertEqual(state["kind"], "visual")
        self.assertIsNone(state["value"])
        self.assertTrue(state["show_map"])

    def test_visual_fallback_has_consistent_visit_and_report_labels(self):
        from longitudinal_review import visit_review_rows
        self.row["result"].update(mode="visual", comparable=False, visual_available=True,
                                  visual_index=65, fallback_reason="No se pudo alinear.")
        visit = visit_review_rows([self.row], self.records)[1]
        state = report_comparison_state(self.row, self.records)
        self.assertEqual(visit["title"], state["label"])
        self.assertEqual(visit["state"], "invalid")
        self.assertIsNone(state["value"])
        self.assertIn("No se pudo alinear", visit["reason"])

    def test_changed_contour_and_wrong_chronology_hide_values_and_maps(self):
        self.records[1]["mask_sha256"] = "changed"
        state = report_comparison_state(self.row, self.records)
        self.assertEqual(state["kind"], "outdated")
        self.assertIsNone(state["value"])
        self.assertFalse(state["show_map"])
        self.records[1]["captured_at"] = self.records[0]["captured_at"]
        self.row = comparison(*self.records)
        state = report_comparison_state(self.row, self.records)
        self.assertIn("fechas", state["label"])
        self.assertIsNone(state["value"])

    def test_latest_rejection_wins_and_scope_excludes_other_records(self):
        old = copy.deepcopy(self.row)
        old.update(id="old", created="2026-01-01")
        self.row["result"]["comparable"] = False
        third = record("C", "2026-03-01")
        outside = comparison(self.records[0], third, identifier="outside")
        overview = report_overview([self.row, old, outside], self.records)
        self.assertEqual(overview["pairs"], 1)
        self.assertEqual(overview["attempts"], 2)
        self.assertEqual(overview["counts"], {"rejected": 1})

    def test_selected_summary_does_not_report_rejected_residual_value(self):
        self.row["result"].update(comparable=False, change_index=99.8765, warnings=["Enfoque insuficiente."])
        summary = selected_followup_summary([self.row], self.records)
        self.assertIn("no evaluables: 1", summary)
        self.assertNotIn("99.9", summary)
        self.assertIn("no gravedad", summary)

    def test_stale_classification_cannot_publish_its_explanation(self):
        self.records[0]["metadata"]["classification"] = dict(
            state="accepted", label="malignant", score=.9, image_sha256="old")
        label, action, show = report_photo_state(self.records[0])
        self.assertEqual(label, "Requiere actualizarse")
        self.assertFalse(show)
        self.assertIn("Vuelve a analizar", action)

    def test_changed_classifier_snapshot_invalidates_saved_comparison(self):
        self.records[0]["metadata"]["classification"] = dict(state="accepted", raw_score=.2, label="benign")
        self.row["result"]["previous_classification"] = dict(state="accepted", raw_score=.8, label="malignant")
        state = report_comparison_state(self.row, self.records)
        self.assertEqual(state["kind"], "outdated")
        self.assertIsNone(state["value"])
        self.assertIn("clasificación", state["reason"])

    def test_pdf_omits_rejected_metrics_and_names_originals_and_status(self):
        self.row["result"].update(comparable=False, change_index=99.8765, warnings=["Enfoque insuficiente."])
        photo = Image.new("RGB", (32, 32), "tan")
        mask = Image.new("L", (32, 32), 255)
        store = SimpleNamespace(
            lesions=lambda: [dict(id="lesion", person_id="person", name="Lesión", site="Brazo")],
            records=lambda lesion: self.records,
            comparisons=lambda lesion: [self.row],
            person=lambda person: dict(name="Persona de prueba", code="DEMO"),
            load_images=lambda rec: (photo, mask),
        )
        rendered = []
        original = ReportPages.text
        def capture(report, body, *args, **kwargs):
            rendered.append(str(body))
            return original(report, body, *args, **kwargs)
        with tempfile.TemporaryDirectory() as folder, patch.object(ReportPages, "text", capture):
            target = Path(folder) / "report.pdf"
            pages = export_readable_pdf(store, "lesion", target, comparison_id=self.row["id"], include_explanations=False)
            self.assertTrue(target.read_bytes().startswith(b"%PDF"))
            self.assertGreaterEqual(pages, 3)
        text = "\n".join(rendered)
        self.assertIn("No evaluables: 1", text)
        self.assertIn("Siguiente paso:", text)
        self.assertIn("Mediciones omitidas", text)
        self.assertIn("Enfoque insuficiente", text)
        self.assertNotIn("99.8765", text)

    def test_pdf_passes_current_metric_and_consecutive_mode_to_timeline(self):
        photo = Image.new("RGB", (32, 32), "tan")
        mask = Image.new("L", (32, 32), 255)
        store = SimpleNamespace(
            lesions=lambda: [dict(id="lesion", person_id="person", name="Lesión", site="Brazo")],
            records=lambda lesion: self.records,
            comparisons=lambda lesion: [self.row],
            person=lambda person: dict(name="Persona de prueba", code="DEMO"),
            load_images=lambda rec: (photo, mask),
        )
        with tempfile.TemporaryDirectory() as folder, patch("longitudinal_pdf.trend_series", wraps=trend_series) as series:
            target = Path(folder) / "report.pdf"
            export_readable_pdf(store, "lesion", target, include_explanations=False, metric="area", trend_mode="consecutive")
            self.assertTrue(any(call.args[-1] == "area" and call.kwargs["mode"] == "consecutive" for call in series.call_args_list))
            self.assertTrue(target.read_bytes().startswith(b"%PDF"))

    def test_simple_report_omits_empty_graph_and_technical_graphs(self):
        self.row["result"].update(comparable=False, warnings=["Enfoque insuficiente."])
        photo = Image.new("RGB", (32, 32), "tan")
        store = SimpleNamespace(
            lesions=lambda: [dict(id="lesion", person_id="person", name="Lesión", site="Brazo")],
            records=lambda lesion: self.records,
            comparisons=lambda lesion: [self.row],
            load_images=lambda rec: (photo, Image.new("L", (32, 32), 255)),
        )
        with tempfile.TemporaryDirectory() as folder, patch("longitudinal_pdf.trend_figure") as timeline, patch("followup_charts.followup_figure") as dashboard:
            export_readable_pdf(store, "lesion", Path(folder) / "simple.pdf", include_explanations=False)
            timeline.assert_not_called()
            dashboard.assert_not_called()


if __name__ == "__main__":
    unittest.main()
