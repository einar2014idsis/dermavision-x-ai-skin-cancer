import tempfile
import unittest
from pathlib import Path
from PIL import Image
from longitudinal_store import LongitudinalStore
from professional_tools import wipe_images, comparison_confidence


class ProfessionalToolsTests(unittest.TestCase):
    def test_notes_survive_reopen_without_replacing_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            store = LongitudinalStore(Path(folder))
            lesion = store.create_lesion("DEMO", "Lesión")
            image = Image.new("RGB", (150, 150), "white")
            mask = Image.new("L", image.size)
            mask.paste(255, (40, 40, 110, 110))
            identifier = store.add_record(lesion, "2026-01-01", image, mask, dict(mask_reviewed=True, note="Original"))
            store.update_visit_notes(identifier, dict(itch="Sí", observation="Revisada", author="Profesional"))
            store.update_visit_notes(identifier, dict(itch="No", author="Revisor"))
            record = LongitudinalStore(Path(folder)).record(identifier)
            self.assertEqual(record["metadata"]["note"], "Original")
            self.assertEqual(record["metadata"]["visit_notes"]["itch"], "No")
            self.assertEqual(record["metadata"]["visit_audit"][-1]["previous"]["itch"], "Sí")
            with self.assertRaises(ValueError):
                store.update_visit_notes(identifier, dict(itch="inventado"))

    def test_wipe_endpoints_and_confidence_require_complete_controls(self):
        before = Image.new("RGB", (10, 10), "red")
        after = Image.new("RGB", (10, 10), "blue")
        self.assertEqual(wipe_images(before, after, 0).tobytes(), after.tobytes())
        self.assertEqual(wipe_images(before, after, 1).tobytes(), before.tobytes())
        self.assertEqual(comparison_confidence(dict(comparable=True))[0], "Media")
        self.assertEqual(comparison_confidence(dict(comparable=False))[0], "Baja")


if __name__ == "__main__":
    unittest.main()
