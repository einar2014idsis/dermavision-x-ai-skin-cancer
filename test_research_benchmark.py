import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from research_evaluation import benchmark, digest, read_csv, rejection_codes, summarize_rows, validate, write_csv
from research_synthetic import synthetic_benchmark, synthetic_original, perturbations


class ResearchMetricsTests(unittest.TestCase):
    def test_unlabelled_data_never_receive_correctness_metrics(self):
        summary = summarize_rows([
            dict(status='accepted', reference_comparable='unknown'),
            dict(status='rejected', reference_comparable='unknown', reason_codes='registration')])
        self.assertEqual(summary['coverage'], 0.5)
        for field in ('false_acceptance_rate', 'false_rejection_rate', 'selective_risk_labelled',
                      'incorrect_acceptances', 'incorrect_rejections'):
            self.assertIsNone(summary[field])
        self.assertEqual(summary['rejection_reasons'], {'registration': 1})

    def test_unknown_acceptances_do_not_dilute_labelled_risk(self):
        rows = [dict(status='accepted', reference_comparable='no'),
                dict(status='accepted', reference_comparable='yes'),
                dict(status='error', reference_comparable='yes', reason_codes='execution_error')]
        rows.extend(dict(status='accepted', reference_comparable='unknown') for _ in range(20))
        summary = summarize_rows(rows)
        self.assertEqual(summary['selective_risk_labelled'], 0.5)
        self.assertEqual(summary['accepted_unknown'], 20)
        self.assertEqual(summary['false_acceptance_rate'], 1)
        self.assertEqual(summary['incorrect_rejections'], 0)
        self.assertEqual(summary['statuses']['error'], 1)

    def test_reason_codes_use_recorded_evidence(self):
        result = dict(comparable=False, capture_quality=[dict(resolution_ok=True, lighting_ok=False, focus_ok=False)])
        self.assertEqual(rejection_codes(result), ['quality_focus', 'quality_lighting'])
        result = dict(comparable=False, registration=dict(accepted=True, framing_accepted=False))
        self.assertEqual(rejection_codes(result), ['framing'])
        self.assertEqual(rejection_codes(dict(comparable=True, warnings=['warning'])), [])

    def test_augmented_original_cannot_cross_splits_even_with_distinct_hashes(self):
        with tempfile.TemporaryDirectory() as folder:
            rows = []
            for index, split in enumerate(('development', 'test')):
                image = Path(folder) / f'{index}.png'
                mask = Path(folder) / f'{index}-mask.png'
                Image.new('RGB', (128, 128), (index * 50, 0, 0)).save(image)
                Image.new('L', (128, 128), 255).save(mask)
                rows.append(dict(record_id=str(index), person_id=f'p{index}', lesion_id=f'l{index}',
                                 captured_at='2026-01-01', split=split, image=str(image), mask=str(mask),
                                 image_sha256=digest(image), mask_sha256=digest(mask),
                                 source_original_id='shared-original'))
            with self.assertRaisesRegex(ValueError, 'derivatives'):
                validate(rows)

    def test_unreadable_images_are_execution_errors_not_successful_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            image, mask = folder / 'bad.png', folder / 'mask.png'
            image.write_bytes(b'not an image')
            Image.new('L', (128, 128), 255).save(mask)
            row = dict(record_id='a', person_id='person', lesion_id='lesion',
                       captured_at='2026-01-01', split='development', image=str(image), mask=str(mask),
                       image_sha256=digest(image), mask_sha256=digest(mask))
            visits = [row, dict(row, record_id='b', captured_at='2026-02-01')]
            pair = dict(pair_id='pair', previous_id='a', current_id='b', reference_comparable='unknown',
                        capture_group='unknown', reviewer='')
            write_csv(folder / 'visits.csv', visits, list(row))
            write_csv(folder / 'pairs.csv', [pair], list(pair))
            summary = benchmark(folder / 'visits.csv', folder / 'pairs.csv', folder / 'output', 'development')
            self.assertEqual(summary['complete']['statuses'], {'error': 1})
            self.assertIsNone(summary['complete']['incorrect_rejections'])


class SyntheticBenchmarkTests(unittest.TestCase):
    def test_generator_and_transformations_are_repeatable(self):
        first, second = synthetic_original(9), synthetic_original(9)
        self.assertEqual(first[0].tobytes(), second[0].tobytes())
        self.assertNotEqual(first[0].tobytes(), synthetic_original(10)[0].tobytes())
        a, b = perturbations(*first), perturbations(*second)
        self.assertEqual([row[0] for row in a], [row[0] for row in b])
        for left, right in zip(a, b):
            self.assertEqual(left[1].tobytes(), right[1].tobytes())
            self.assertEqual(left[2].tobytes(), right[2].tobytes())
            self.assertEqual(left[3:], right[3:])

    def test_full_benchmark_saves_provenance_known_identity_and_separate_failure_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'benchmark'
            summary = synthetic_benchmark(output, originals=2, seed=5)
            self.assertEqual(summary['synthetic_pairs'], 12)
            self.assertEqual(summary['reference_scope'], 'synthetic_expectations')
            self.assertEqual(summary['complete']['total'], 12)
            self.assertEqual(summary['complete']['statuses'].get('error', 0), 0)
            groups = summary['by_capture_group']
            self.assertEqual(groups['unchanged']['complete']['statuses'], {'accepted': 2})
            self.assertEqual(groups['blur_severe']['complete']['statuses'], {'rejected': 2})
            self.assertEqual(groups['dark_severe']['complete']['statuses'], {'rejected': 2})
            self.assertIn('quality_lighting', summary['complete']['rejection_reasons'])
            pairs = read_csv(output / 'synthetic_pairs.csv')
            different = [row for row in pairs if row['reference_identity'] == 'different']
            self.assertEqual(len(different), 2)
            self.assertTrue(all(row['previous_original_id'] != row['current_original_id'] for row in different))
            self.assertTrue(all(row['reference_source'] == 'synthetic_construction' for row in pairs))
            self.assertEqual(len(validate(read_csv(output / 'visits.csv'))), 14)
            provenance = json.loads((output / 'provenance.json').read_text())
            self.assertEqual(provenance['pairs_sha256'], digest(output / 'synthetic_pairs.csv'))
            with self.assertRaisesRegex(ValueError, 'empty output'):
                synthetic_benchmark(output, originals=2)


if __name__ == '__main__':
    unittest.main()
