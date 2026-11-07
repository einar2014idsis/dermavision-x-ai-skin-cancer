import unittest
import numpy as np
from PIL import Image
from domain_gate import gate_pixels, gate_scores


class GateTests(unittest.TestCase):
    def test_preprocessing_consistent_between_low_and_high_resolution(self):
        source = Image.new("RGB", (32, 32), (120, 80, 70))
        np.testing.assert_array_equal(
            gate_pixels(source), gate_pixels(source.resize((640, 640)))
        )

    def test_invalid_features_fail_closed(self):
        with self.assertRaises(ValueError):
            gate_scores([[float("nan")]], {"weights": [1], "bias": 0})
        with self.assertRaises(ValueError):
            gate_scores([[1, 2]], {"weights": [1], "bias": 0})

    def test_score_is_monotonic_and_finite(self):
        scores = gate_scores([[-1000], [0], [1000]], {"weights": [1], "bias": 0})
        self.assertTrue(np.isfinite(scores).all())
        self.assertTrue(np.all(np.diff(scores) > 0))


if __name__ == "__main__":
    unittest.main()
