import tempfile
import unittest
from pathlib import Path
import cv2
from PIL import Image, ImageDraw
from longitudinal_store import LongitudinalStore
from evolution_video import export_video


class VideoTests(unittest.TestCase):
    def test_video_contains_visits_and_preserves_existing_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LongitudinalStore(Path(directory) / "data")
            lesion = store.create_lesion("TEST", "Sintética")
            for date, color in (("2026-01-01", "brown"), ("2026-02-01", "tan")):
                mask = Image.new("L", (200, 150))
                ImageDraw.Draw(mask).ellipse((70, 45, 130, 105), fill=255)
                store.add_record(lesion, date, Image.new("RGB", (200, 150), color), mask, {"mask_reviewed": True})
            records = store.records(lesion)
            target = Path(directory) / "video.mp4"
            progress = []
            scenes = export_video(store, records, [], target, progress=lambda n, t: progress.append((n, t)), size=(640, 360), fps=2, seconds=.5)
            self.assertEqual(scenes, 6)
            self.assertEqual(progress[-1], (6, 6))
            video = cv2.VideoCapture(str(target))
            self.assertTrue(video.isOpened())
            self.assertGreaterEqual(video.get(cv2.CAP_PROP_FRAME_COUNT), 6)
            video.release()
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                export_video(store, records[:1], [], target)
            self.assertEqual(before, target.read_bytes())
