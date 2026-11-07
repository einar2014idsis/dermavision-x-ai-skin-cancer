import unittest
import numpy as np
from PIL import Image
from longitudinal_views import comparison_summary, aligned_detail


class ViewPreparationTests(unittest.TestCase):
    def test_counts_exclude_visual_stale_and_unavailable_results(self):
        def result(index, mode="longitudinal"):
            return dict(
                mode=mode,
                comparable=index is not None,
                change_index=index,
                previous_id="a",
                current_id="b",
                previous_date="2026-01-01",
                current_date="2026-02-01",
            )

        rows = [
            dict(result=result(25)),
            dict(result=result(None, "visual")),
            dict(result=result(35), stale_dates=True),
            dict(result=result(None)),
        ]
        summary = comparison_summary(
            rows, [dict(id="a", label="T0"), dict(id="b", label="T1")]
        )
        self.assertEqual(len(summary["points"]), 1)
        self.assertEqual(summary["points"][0]["pair"], "T0 → T1")
        self.assertEqual(
            (summary["visual"], summary["stale"], summary["invalid"]), (1, 1, 1)
        )

    def test_dates_are_sorted_and_reference_changes_are_identified(self):
        rows = []
        for a, b, date in [("a", "c", "2026-04-01"), ("b", "d", "2026-02-01")]:
            rows.append(
                dict(
                    result=dict(
                        mode="longitudinal",
                        comparable=True,
                        change_index=20,
                        previous_id=a,
                        current_id=b,
                        previous_date="2026-01-01",
                        current_date=date,
                    )
                )
            )
        summary = comparison_summary(rows, [])
        self.assertFalse(summary["common_reference"])
        self.assertEqual(summary["points"][0]["date"].month, 2)

    def test_zoom_contains_both_aligned_contours_and_preserves_original(self):
        overlay = Image.new("RGB", (400, 400), "white")
        a = np.zeros((400, 400), dtype="uint8")
        a[175:225, 175:225] = 255
        b = np.zeros_like(a)
        b[175:225, 165:245] = 255
        preview = aligned_detail(
            overlay, Image.fromarray(a), Image.fromarray(b), [[1, 0, 0], [0, 1, 0]]
        )
        self.assertLess(preview.width, overlay.width)
        self.assertGreater(preview.width, 80)
        self.assertEqual(overlay.size, (400, 400))


if __name__ == "__main__":
    unittest.main()
