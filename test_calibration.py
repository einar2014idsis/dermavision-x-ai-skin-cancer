import json
import tempfile
import unittest
from pathlib import Path

from calibration import ScoreCalibration


class CalibrationTests(unittest.TestCase):
    def test_load_apply_and_abstain(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "calibration.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": "dermavision-calibration-v1",
                        "fit_split": "validation",
                        "slope": 1.0,
                        "intercept": 0.0,
                        "threshold": 0.4,
                        "uncertain_low": 0.35,
                        "uncertain_high": 0.45,
                    }
                ),
                encoding="utf-8",
            )
            calibration = ScoreCalibration.load(path)
            self.assertAlmostEqual(calibration.apply(0.2), 0.2)
            self.assertEqual(calibration.decision(0.3), "benign")
            self.assertEqual(calibration.decision(0.4), "uncertain")
            self.assertEqual(calibration.decision(0.6), "malignant")

    def test_rejects_calibration_fitted_on_test(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "calibration.json"
            path.write_text(
                json.dumps(
                    {"schema": "dermavision-calibration-v1", "fit_split": "test"}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                ScoreCalibration.load(path)


if __name__ == "__main__":
    unittest.main()
