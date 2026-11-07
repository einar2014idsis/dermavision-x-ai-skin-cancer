"""Recover derived comparison files in a temporary SQLite store only."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageDraw

from longitudinal_store import LongitudinalStore, readable_comparison_map
from longitudinal_workflow import WorkflowMixin


class ComparisonMapRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(Path(self.temp.name) / "history")
        self.lesion = self.store.create_lesion("MAP-TEST", "Synthetic lesion", "Arm")
        photo = Image.new("RGB", (80, 80), (180, 140, 110))
        mask = Image.new("L", photo.size, 0)
        ImageDraw.Draw(mask).ellipse((20, 20, 60, 60), fill=255)
        metadata = dict(mask_reviewed=True)
        self.previous = self.store.add_record(
            self.lesion, "2026-01-01", photo, mask, metadata
        )
        self.current = self.store.add_record(
            self.lesion, "2026-02-01", photo, mask, metadata
        )
        a, b = self.store.record(self.previous), self.store.record(self.current)
        self.result = dict(
            mode="longitudinal",
            comparable=True,
            change_index=17.0,
            registration=dict(accepted=True, framing_accepted=True),
            color_normalization=dict(accepted=True),
            previous_id=self.previous,
            current_id=self.current,
            previous_date=a["captured_at"],
            current_date=b["captured_at"],
            previous_sha256=a["sha256"],
            current_sha256=b["sha256"],
            previous_mask_sha256=a["mask_sha256"],
            current_mask_sha256=b["mask_sha256"],
            previous_classification=dict(state="unavailable", score=None),
            current_classification=dict(state="unavailable", score=None),
        )
        # A deterministic image stands in for the newly computed map. These
        # checks exercise storage and cache recovery, not medical analysis.
        self.overlay = Image.new("RGB", (48, 48), (30, 160, 210))
        self.identifier = self.store.save_comparison(
            self.previous, self.current, self.result, self.overlay
        )
        self.row = self.store.comparisons(self.lesion)[0]
        self.map_path = self.store.path(self.row["overlay"])
        self.report_path = self.store.root / "comparisons" / f"{self.identifier}.json"
        self.flow = WorkflowMixin()
        self.flow.store = self.store
        self.flow.lesion_id = self.lesion
        self.flow.app = SimpleNamespace(model=None, domain_gate=None)

    def tearDown(self):
        self.temp.cleanup()

    def assert_restored(self):
        reused = self.store.save_comparison(
            self.previous, self.current, self.result, self.overlay
        )
        self.assertEqual(reused, self.identifier)
        self.assertEqual(len(self.store.comparisons(self.lesion)), 1)
        self.assertTrue(readable_comparison_map(self.map_path))
        with Image.open(self.map_path) as image:
            self.assertEqual(image.convert("RGB").tobytes(), self.overlay.tobytes())
        cached = self.flow.cached_followup(self.previous, self.current)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["id"], self.identifier)
        self.assertEqual(
            json.loads(self.report_path.read_text(encoding="utf-8")), self.result
        )

    def test_readable_map_remains_cached_without_rewriting_or_duplicating_it(self):
        original_map = self.map_path.read_bytes()
        original_time = self.map_path.stat().st_mtime_ns
        self.assertEqual(
            self.flow.cached_followup(self.previous, self.current)["id"],
            self.identifier,
        )
        self.assert_restored()
        self.assertEqual(self.map_path.read_bytes(), original_map)
        self.assertEqual(self.map_path.stat().st_mtime_ns, original_time)

    def test_missing_map_is_not_cached_and_is_rebuilt_with_the_same_comparison_id(self):
        self.map_path.unlink()
        self.report_path.unlink()
        self.assertIsNone(self.flow.cached_followup(self.previous, self.current))
        self.assert_restored()

    def test_corrupted_map_is_not_cached_and_is_rebuilt(self):
        self.map_path.write_bytes(b"not a PNG file")
        self.assertIsNone(self.flow.cached_followup(self.previous, self.current))
        self.assert_restored()

    def test_truncated_map_is_not_cached_and_is_rebuilt(self):
        self.map_path.write_bytes(self.map_path.read_bytes()[:45])
        self.assertIsNone(self.flow.cached_followup(self.previous, self.current))
        self.assert_restored()

    def test_corrupted_report_is_restored_from_the_sqlite_snapshot(self):
        self.report_path.write_text("{broken JSON", encoding="utf-8")
        self.assert_restored()

    def test_failed_map_recovery_preserves_the_row_and_cleans_the_temporary_file(self):
        self.map_path.write_bytes(b"broken map")
        with patch.object(
            self.overlay, "save", side_effect=OSError("Disk write failed")
        ):
            with self.assertRaisesRegex(OSError, "Disk write failed"):
                self.store.save_comparison(
                    self.previous, self.current, self.result, self.overlay
                )
        self.assertEqual(self.map_path.read_bytes(), b"broken map")
        self.assertEqual(
            [r["id"] for r in self.store.comparisons(self.lesion)], [self.identifier]
        )
        self.assertEqual(list(self.map_path.parent.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
