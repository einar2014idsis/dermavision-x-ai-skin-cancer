"""Seguimiento: hechos vigentes, motivos concretos y clasificación independiente."""

import copy
import tempfile
import unittest
import queue
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from PIL import Image

from longitudinal_insights import (
    comparison_validity,
    followup_summary,
    quality_guidance,
    quality_rows,
    trend_series,
)


def record(identifier, date):
    return dict(
        id=identifier,
        captured_at=date,
        sha256=identifier + "-photo",
        mask_sha256=identifier + "-mask",
        metadata=dict(mask_reviewed=True),
    )


def comparison(a, b, index=30.0, identifier="comparison", created="2026-10-01"):
    result = dict(
        previous_id=a["id"],
        current_id=b["id"],
        previous_date=a["captured_at"],
        current_date=b["captured_at"],
        previous_sha256=a["sha256"],
        current_sha256=b["sha256"],
        previous_mask_sha256=a["mask_sha256"],
        current_mask_sha256=b["mask_sha256"],
        mode="longitudinal",
        comparable=True,
        change_index=index,
        changes=dict(
            area=12.0, shape=0.2, asymmetry=0.03, border=0.1, color=8.0, texture=0.1
        ),
        index_components=dict(
            area=0.24, shape=0.2, asymmetry=0.1, border=0.2, color=0.4, texture=0.2
        ),
        registration=dict(
            accepted=True, overlap=0.9, lesion_retained=1.0, framing_accepted=True
        ),
        color_normalization=dict(
            accepted=True, offset=[1.0, 2.0, 3.0], residual_delta_e=2.0
        ),
    )
    return dict(
        id=identifier,
        previous_id=a["id"],
        current_id=b["id"],
        created=created,
        stale_dates=False,
        result=result,
        live_previous_date=a["captured_at"],
        live_current_date=b["captured_at"],
    )


class FollowupSummaryTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            record("A", "2026-01-01"),
            record("B", "2026-02-01"),
            record("C", "2026-03-01"),
        ]

    def test_summary_uses_latest_pair_with_common_origin_and_not_largest_index(self):
        a, b, c = self.records
        rows = [
            comparison(a, b, 90.0, "first"),
            comparison(a, c, 20.0, "latest"),
            comparison(b, c, 99.0, "other-origin"),
        ]
        body = followup_summary(rows, self.records)
        self.assertIn("3 fotografías", body)
        self.assertIn("3 comparaciones vigentes", body)
        self.assertIn("20.0 sobre 100", body)
        self.assertNotIn("99.0 sobre 100", body)
        self.assertIn("color", body)
        self.assertIn("no determina mejoría", body)

    def test_single_pair_does_not_claim_a_trend(self):
        a, b = self.records[:2]
        body = followup_summary([comparison(a, b)], [a, b])
        self.assertIn("Una sola comparación", body)
        self.assertIn("todavía no establecer una tendencia", body)

    def test_latest_saved_pair_is_counted_once(self):
        a, b = self.records[:2]
        old = comparison(a, b, 20.0, "old", "2026-09-01")
        recent = comparison(a, b, 45.0, "new", "2026-10-01")
        body = followup_summary([recent, old], [a, b])
        self.assertIn("Hay 1 comparación vigente", body)
        self.assertIn("45.0 sobre 100", body)
        self.assertEqual(
            trend_series([recent, old], [a, b], a["id"])["points"][0]["value"], 45.0
        )

    def test_timeline_does_not_resurrect_an_older_result_when_latest_is_invalid(self):
        a, b = self.records[:2]
        old = comparison(a, b, 20.0, "old", "2026-09-01")
        recent = comparison(a, b, 45.0, "new", "2026-10-01")
        recent["result"]["changes"]["color"] = float("inf")
        rows = [recent, old]
        self.assertFalse(trend_series(rows, [a, b], a["id"])["points"])
        self.assertIn("Hay 0 comparaciones vigentes", followup_summary(rows, [a, b]))

    def test_changed_dates_and_hashes_invalidate_summary_and_timeline(self):
        a, b = self.records[:2]
        row = comparison(a, b)
        cases = [
            ("captured_at", "2026-02-02", "fechas"),
            ("sha256", "changed", "contorno"),
            ("mask_sha256", "changed", "contorno"),
        ]
        for key, value, reason in cases:
            with self.subTest(key=key):
                live = copy.deepcopy([a, b])
                live[1][key] = value
                self.assertIn(reason, comparison_validity(row, live))
                self.assertFalse(trend_series([row], live, a["id"])["points"])
                text = followup_summary([row], live)
                self.assertIn("Hay 0 comparaciones vigentes", text)
                self.assertIn("Resultados excluidos", text)
                self.assertNotIn("30.0 sobre 100", text)

    def test_nonfinite_descriptor_cannot_be_presented_as_a_valid_index(self):
        a, b = self.records[:2]
        row = comparison(a, b)
        row["result"]["changes"]["color"] = float("nan")
        self.assertIn("medición inválida", comparison_validity(row, [a, b]))
        self.assertNotIn("30.0 sobre 100", followup_summary([row], [a, b]))
        self.assertFalse(trend_series([row], [a, b], a["id"])["points"])

    def test_classification_is_per_latest_photo_not_averaged(self):
        a, b = self.records[:2]
        a["metadata"]["classification"] = dict(
            state="accepted", label="benign", score=0.1
        )
        b["metadata"]["classification"] = dict(
            state="accepted", label="malignant", score=0.81
        )
        body = followup_summary([comparison(a, b)], [a, b])
        self.assertIn("Por separado", body)
        self.assertIn("clasificación experimental maligna", body)
        self.assertIn("81.0 %", body)
        self.assertIn("no es una probabilidad de tener cáncer", body)
        self.assertNotIn("45.5", body)

    def test_uncertain_classification_does_not_assign_a_binary_class(self):
        a, b = self.records[:2]
        b["metadata"]["classification"] = dict(
            state="uncertain", score=0.51, label="malignant"
        )
        body = followup_summary([comparison(a, b)], [a, b])
        self.assertIn("no concluyente", body)
        self.assertNotIn("clasificación experimental maligna", body)

    def test_missing_or_filtered_records_never_leak_into_scope(self):
        a, b, c = self.records
        body = followup_summary([comparison(a, c)], [a, b])
        self.assertIn("2 fotografías", body)
        self.assertNotIn("01/03/2026", body)
        self.assertIn("Hay 0 comparaciones vigentes", body)
        self.assertIn("Todavía no hay fotografías", followup_summary([], []))

    def test_color_failure_preserves_accepted_alignment_and_explains_limitation(self):
        a, b = self.records[:2]
        row = comparison(a, b)
        result = row["result"]
        result.update(mode="visual", comparable=False, visual_available=True)
        result["color_normalization"].update(accepted=False, residual_delta_e=25.0)
        rows = dict(quality_rows(result, [a, b]))
        self.assertEqual(rows["Alineación"], "Aceptada")
        self.assertEqual(rows["Encuadre después de alinear"], "Aceptado")
        self.assertIn("Control no aceptado", rows["Iluminación y color"])
        self.assertIn("Las fotos se alinearon", quality_guidance(result))
        self.assertIn("iluminación", quality_guidance(result))
        self.assertNotIn("No se encontraron", quality_guidance(result))
        self.assertIn("iluminación", followup_summary([row], [a, b]))

    def test_framing_failure_does_not_say_alignment_failed(self):
        a, b = self.records[:2]
        result = comparison(a, b)["result"]
        result.update(mode="visual", comparable=False, visual_available=True)
        result["registration"].update(overlap=0.4, framing_accepted=False)
        result.pop("color_normalization")
        self.assertIn("La alineación se obtuvo", quality_guidance(result))
        self.assertEqual(
            dict(quality_rows(result, [a, b]))["Encuadre después de alinear"],
            "Insuficiente",
        )

    def test_old_results_without_optional_quality_fields_remain_usable(self):
        a, b = self.records[:2]
        row = comparison(a, b)
        row["result"]["registration"].pop("framing_accepted")
        row["result"]["color_normalization"].pop("accepted")
        self.assertIsNone(comparison_validity(row, [a, b]))
        self.assertEqual(
            dict(quality_rows(row["result"], [a, b]))["Iluminación y color"],
            "Control de color aceptado",
        )

    def test_visual_fallback_retains_real_reason_without_claiming_alignment_failed(
        self,
    ):
        from longitudinal_analysis import compare_records

        a, b = self.records[:2]
        photo = Image.new("RGB", (32, 32), "tan")
        mask = Image.new("L", (32, 32), 255)
        failed = dict(
            comparable=False,
            visual_differences=dict(color=30.0),
            warnings=[
                "Diferencias de iluminación/color demasiado grandes para comparar de forma fiable."
            ],
            registration=dict(accepted=True, framing_accepted=True),
            color_normalization=dict(
                accepted=False, offset=[30.0, 0.0, 0.0], residual_delta_e=20.0
            ),
        )
        visual = dict(
            mode="visual",
            visual_available=True,
            comparable=False,
            warnings=[],
            visual_index=30.0,
        )
        store = SimpleNamespace(
            pair=lambda *args: (a, b),
            load_images=lambda r: (photo, mask),
            save_comparison=lambda *args: "saved",
        )
        with (
            patch(
                "longitudinal_analysis.classify_record",
                return_value=dict(state="unavailable"),
            ),
            patch(
                "longitudinal_analysis.compare_images",
                return_value=(failed, photo, photo),
            ),
            patch(
                "longitudinal_analysis.compare_visual_images",
                return_value=(visual, photo, photo),
            ),
        ):
            payload = compare_records(store, a["id"], b["id"], fallback_visual=True)
        self.assertTrue(payload["result"]["registration"]["accepted"])
        self.assertIn("iluminación", payload["result"]["warnings"][0])
        self.assertNotIn(
            "alineación longitudinal falló", payload["result"]["warnings"][0]
        )

    def test_pdf_summary_receives_only_included_records_and_pairs(self):
        from longitudinal_pdf import export_readable_pdf
        from longitudinal_reports import selected_followup_summary

        a, b, c = self.records
        rows = [comparison(a, b), comparison(a, c, 50.0, "outside")]
        photo = Image.new("RGB", (32, 32), "tan")
        mask = Image.new("L", (32, 32), 255)
        store = SimpleNamespace(
            lesions=lambda: [
                dict(id="lesion", person_id="person", name="Lesión", site="Brazo")
            ],
            records=lambda lesion: self.records,
            comparisons=lambda lesion: rows,
            person=lambda person: dict(name="Persona de prueba", code="DEMO"),
            load_images=lambda rec: (photo, mask),
        )
        with tempfile.TemporaryDirectory() as folder, patch(
            "longitudinal_pdf.selected_followup_summary", wraps=selected_followup_summary
        ) as summary:
            pages = export_readable_pdf(
                store,
                "lesion",
                Path(folder) / "report.pdf",
                record_ids=["A", "B"],
                include_explanations=False,
            )
            args = summary.call_args.args
            self.assertEqual([r["id"] for r in args[1]], ["A", "B"])
            self.assertEqual(len(args[0]), 1)
            self.assertGreaterEqual(pages, 2)


class FollowupWorkerTests(unittest.TestCase):
    def window(self):
        from longitudinal_detail_ui import DetailMixin

        class FakeWindow(DetailMixin):
            pass

        window = FakeWindow()
        window.records = [
            record("A", "2026-01-01"),
            record("B", "2026-02-01"),
            record("C", "2026-03-01"),
        ]
        window.lesion_id = "lesion"
        window.running = False
        window.saved_comparisons = []
        window.selected_photo_ids = ["B", "C"]
        window.current_result = dict(previous_id="B", current_id="C")
        window.app = SimpleNamespace(
            busy=False,
            model=None,
            domain_gate=None,
            reference_index=None,
            experiment_folder=Path("."),
            calibration=None,
            refresh_actions=lambda: None,
        )
        window.store = SimpleNamespace(
            record=lambda identifier: next(
                r for r in window.records if r["id"] == identifier
            )
        )
        window.status = SimpleNamespace(set=lambda text: None)
        window.trend_origin = SimpleNamespace(configure=lambda **kwargs: None)
        window.cancel_auto_comparison = lambda: None
        window.refresh_thumbnails = lambda: None
        window.queue = queue.Queue()
        window.cached_followup = lambda a, b: None
        return window

    def test_followup_worker_preserves_selected_pair_and_result(self):
        window = self.window()
        current = window.current_result
        with patch(
            "longitudinal_analysis.compare_records", return_value=dict(id="saved")
        ) as compare:
            window.compare_reference_followup()
            kind, payload = window.queue.get(timeout=5)
        self.assertEqual(kind, "followup_done")
        self.assertEqual(payload["count"], 2)
        self.assertFalse(payload["failures"])
        self.assertEqual(window.selected_photo_ids, ["B", "C"])
        self.assertIs(window.current_result, current)
        self.assertTrue(window.running)
        self.assertTrue(window.app.busy)
        self.assertEqual(
            [(call.args[1], call.args[2]) for call in compare.call_args_list],
            [("A", "B"), ("A", "C")],
        )
        self.assertFalse(hasattr(window, "followup_pending"))

    def test_worker_reuses_current_cache_and_reports_individual_errors(self):
        window = self.window()
        a, b = window.records[:2]
        cached = comparison(a, b)
        window.cached_followup = lambda previous, current: (
            cached if current == "B" else None
        )
        with patch(
            "longitudinal_analysis.compare_records",
            side_effect=ValueError("Fotografía dañada"),
        ) as compare:
            window.compare_reference_followup()
            kind, payload = window.queue.get(timeout=5)
        self.assertEqual(kind, "followup_done")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["failures"], [dict(record_id="C", reason="Fotografía dañada")]
        )
        self.assertEqual(compare.call_args.args[2], "C")
        self.assertEqual(window.selected_photo_ids, ["B", "C"])

    def test_followup_series_keeps_real_pending_captures(self):
        window = self.window()
        a, _, c = window.records
        window.saved_comparisons = [comparison(a, c)]
        series = window.selected_trend_series()
        self.assertEqual(
            [capture["target"] for capture in series["captures"]], ["A", "B", "C"]
        )
        self.assertEqual([point["target"] for point in series["points"]], ["C"])


if __name__ == "__main__":
    unittest.main()
