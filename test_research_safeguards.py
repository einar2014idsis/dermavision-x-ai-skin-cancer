import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageFilter
from longitudinal_analysis import compare_images
from research_evaluation import validate, digest
from test_longitudinal import sample


class QualitySafeguards(unittest.TestCase):
    def test_bad_quality_blocks_comparison_even_without_classifier(self):
        image, mask = sample()
        for invalid in (Image.new('RGB', image.size, 'black'),
                        image.filter(ImageFilter.GaussianBlur(15))):
            result, _, _ = compare_images(image, invalid, mask, mask)
            self.assertFalse(result['comparable'])
            self.assertIsNone(result['change_index'])
            self.assertFalse(result['capture_quality'][-1]['accepted'])
            self.assertIn('Foto actual:', result['warnings'][-1])

    def test_quality_evidence_recorded_for_both_photos(self):
        image, mask = sample()
        result, _, _ = compare_images(image, image, mask, mask)
        self.assertTrue(result['comparable'])
        self.assertEqual([r['photo'] for r in result['capture_quality']], ['anterior', 'actual'])
        self.assertTrue(all(r['accepted'] for r in result['capture_quality']))


class ResearchIntegrity(unittest.TestCase):
    def test_dates_patient_split_and_lesion_identity_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder)/'image.png'
            mask = Path(folder)/'mask.png'
            Image.new('RGB', (128, 128)).save(image)
            Image.new('L', (128, 128)).save(mask)
            row = dict(record_id='a', person_id='p1', lesion_id='l1', split='development',
                       captured_at='2026-01-01', image=str(image), mask=str(mask),
                       image_sha256=digest(image), mask_sha256=digest(mask))
            validate([row])
            for change in (dict(record_id='b', split='test'),
                           dict(record_id='b', person_id='p2'),
                           dict(record_id='b', captured_at='bad')):
                with self.assertRaises(ValueError):
                    validate([row, dict(row, **change)])


if __name__ == '__main__':
    unittest.main()
