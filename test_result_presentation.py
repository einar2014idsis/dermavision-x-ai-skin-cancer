"""UI results separate decision guidance from model scores and clear stale details."""

import tkinter as tk
import unittest

from PIL import Image

from calibration import ScoreCalibration
from interfaz import App, describe_result


class ResultPresentationTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, autoload_model=False)

    def tearDown(self):
        self.app.close()

    def visible_result(self):
        return self.app.result_text.get("1.0", "end")

    def test_percentages_require_details_and_clear_with_new_image(self):
        self.app.result.set(describe_result(0.8))
        self.assertIn("CONTENIDO ACEPTADO", self.visible_result())
        self.assertIn("patrón maligno", self.visible_result())
        self.assertIn("Siguiente paso", self.visible_result())
        self.assertNotIn("%", self.visible_result())
        self.assertEqual(self.app.details_button.cget("state"), "normal")
        self.app.show_result_details()
        windows = [child for child in self.root.winfo_children()
                   if isinstance(child, tk.Toplevel)]
        self.assertEqual(len(windows), 1)
        detail = next(child for child in windows[0].winfo_children()
                      if isinstance(child, tk.Text))
        self.assertIn("Maligna: 80.0 %", detail.get("1.0", "end"))
        self.assertIn("sin calibrar", detail.get("1.0", "end"))
        windows[0].destroy()
        self.app.update_frame(Image.new("RGB", (224, 224)))
        self.assertEqual(self.app.details_button.cget("state"), "disabled")
        self.assertNotIn("patrón maligno", self.visible_result())

    def test_abstention_explains_content_accepted_but_no_class(self):
        calibration = ScoreCalibration(uncertain_low=0.4, uncertain_high=0.6)
        self.app.result.set(describe_result(0.5, calibration))
        self.assertIn("RESULTADO NO CONCLUYENTE", self.visible_result())
        self.assertIn("No se emite una clase", self.visible_result())
        self.assertNotIn("%", self.visible_result())
        self.assertNotIn("patrón maligno", self.visible_result())
        self.assertEqual(self.app.details_button.cget("state"), "normal")

    def test_rejection_has_action_and_no_old_technical_score(self):
        self.app.result.set(describe_result(0.8))
        self.app.messages.put(("ok", ("analysis", {
            "accepted": False, "state": "rejected", "message": "Objeto ajeno",
        }, self.app.revision)))
        self.app.poll()
        self.assertIn("IMAGEN RECHAZADA", self.visible_result())
        self.assertIn("Siguiente paso", self.visible_result())
        self.assertNotIn("%", self.app.result.get())
        self.assertEqual(self.app.details_button.cget("state"), "disabled")


if __name__ == "__main__":
    unittest.main()
