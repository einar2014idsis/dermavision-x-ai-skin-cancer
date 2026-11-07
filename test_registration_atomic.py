"""El registro inicial conserva fotografía y análisis como una sola operación."""

import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path
from longitudinal_store import LongitudinalStore
from test_longitudinal import sample


class InitialRegistrationTests(unittest.TestCase):
    def test_failed_explanation_does_not_leave_a_partial_record(self):
        with tempfile.TemporaryDirectory() as folder:
            store = LongitudinalStore(folder)
            lesion = store.create_lesion("P01", "Brazo")
            image, mask = sample()
            explanation = Mock()
            explanation.convert.return_value.save.side_effect = OSError(
                "No se pudo escribir el mapa"
            )
            with self.assertRaises(OSError):
                store.add_record(
                    lesion,
                    "2026-10-14",
                    image,
                    mask,
                    {"mask_reviewed": True},
                    analysis={"state": "accepted", "label": "benign", "score": 0.2},
                    explanation=explanation,
                )
            self.assertEqual(store.records(lesion), [])
            self.assertEqual(list(Path(folder).rglob("image.png")), [])

    def test_initial_analysis_and_map_are_available_after_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            store = LongitudinalStore(folder)
            lesion = store.create_lesion("P01", "Brazo")
            image, mask = sample()
            identifier = store.add_record(
                lesion,
                "2026-10-14",
                image,
                mask,
                {"mask_reviewed": True},
                analysis={"state": "accepted", "label": "benign", "score": 0.2},
                explanation=image,
            )
            reopened = LongitudinalStore(folder)
            self.assertEqual(
                reopened.record(identifier)["metadata"]["classification"]["label"],
                "benign",
            )
            self.assertEqual(reopened.load_explanation(identifier).size, image.size)
