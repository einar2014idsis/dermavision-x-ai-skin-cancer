"""Tres controles de aceptacion tecnica mostrados en la exposicion.

Usan datos sinteticos reproducibles. No representan validacion clinica ni
aceptacion formal por usuarios finales.
"""

import tempfile
import unittest
from pathlib import Path

from capstone_demo import prepare_demo


class AcceptanceTechnicalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.demo = prepare_demo(Path(cls.temp.name) / "aceptacion_tecnica")
        cls.rotation, cls.change, cls.unusable = cls.demo["checks"]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_pa_05_rotation_does_not_create_false_growth(self):
        """Una rotacion conocida mantiene comparable la misma lesion."""
        self.assertTrue(self.rotation["comparable"])
        self.assertLess(abs(self.rotation["changes"]["area"]), 2.0)

    def test_pa_05_known_change_is_detected(self):
        """El aumento sintetico de radio produce el cambio de area esperado."""
        self.assertTrue(self.change["comparable"])
        expected_area_change = 100 * ((55 / 45) ** 2 - 1)
        self.assertAlmostEqual(
            self.change["changes"]["area"], expected_area_change, delta=2
        )

    def test_pa_03_unusable_capture_is_rejected(self):
        """Una captura desenfocada queda como no evaluable."""
        self.assertFalse(self.unusable["comparable"])
        self.assertFalse(self.unusable["changes"])
        self.assertTrue(self.unusable["warnings"])


if __name__ == "__main__":
    unittest.main()
