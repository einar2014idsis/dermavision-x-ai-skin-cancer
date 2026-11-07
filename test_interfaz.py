import unittest
import tkinter as tk
from unittest.mock import patch, MagicMock
import numpy as np
from PIL import Image
from interfaz import App, describe_result


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)
        if self.app.autoload_job is not None:
            self.root.after_cancel(self.app.autoload_job)
            self.app.autoload_job = None

    def tearDown(self):
        self.app.close()

    def test_no_fabricated_prediction(self):
        with patch("interfaz.messagebox.showinfo") as notice:
            self.app.analyze()
            notice.assert_called_once()
        self.assertEqual(self.app.result.get(), "Sin predicción")

    def test_region_and_reset(self):
        self.app.full_image = False
        self.app.update_frame(Image.new("RGB", (640, 480), "white"))
        self.assertEqual(self.app.region().size, (360, 360))
        self.assertIn("255/255", self.app.quality.get())
        self.assertIn("Sin predicción", self.app.result.get())

    def test_file_uses_full_image(self):
        self.app.full_image = (
            True  # Solo para comprobaciones offline, no hay botón de carga.
        )
        self.app.update_frame(Image.new("RGB", (640, 480), "white"))
        self.assertEqual(self.app.region().size, (640, 480))

    def test_camera_stop_cancels_scheduled_capture(self):
        self.app.camera_job = self.root.after(10000, lambda: None)
        self.app.stop_camera()
        self.assertIsNone(self.app.camera_job)

    def test_camera_capture_and_release(self):
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, np.zeros((240, 320, 3), dtype=np.uint8))
        with patch("cv2.VideoCapture", return_value=capture):
            self.app.camera()
            self.assertEqual(self.app.frame.size, (320, 240))
            self.assertTrue(self.app.full_image)
            self.assertEqual(self.app.region().size, (320, 240))
            self.app.stop_camera()
        capture.release.assert_called_once()

    def test_camera_unavailable(self):
        capture = MagicMock()
        capture.isOpened.return_value = False
        with patch("cv2.VideoCapture", return_value=capture), patch(
            "interfaz.messagebox.showerror"
        ) as notice:
            self.app.camera()
            notice.assert_called_once()
        self.assertIsNone(self.app.cap)

    def test_stale_prediction_discarded(self):
        self.app.update_frame(Image.new("RGB", (100, 100)))
        self.app.messages.put(("ok", ("prediction", 0.9, 0)))
        self.app.poll()
        self.assertIn("descartado", self.app.status.get())
        self.assertIn("Sin predicción", self.app.result.get())

    def test_score_references_and_reset(self):
        match = dict(
            image=Image.new("RGB", (80, 70)),
            label="Benigna",
            source="train/benign/example.jpg",
        )
        self.app.messages.put(
            (
                "ok",
                (
                    "analysis",
                    dict(accepted=True, score=0.18, matches=[match]),
                    self.app.revision,
                ),
            )
        )
        self.app.poll()
        self.assertIn("Benigna: 82.0 %", self.app.result.get())
        self.assertIn("Maligna: 18.0 %", self.app.result.get())
        self.assertIn("Descripción:", self.app.result.get())
        self.assertIn("no son probabilidades clínicas", self.app.result.get())
        self.assertEqual(len(self.app.reference_cards.winfo_children()), 1)
        self.app.update_frame(Image.new("RGB", (224, 224)))
        self.assertEqual(len(self.app.reference_cards.winfo_children()), 0)
        self.assertNotIn("82.0 %", self.app.result.get())

    def test_malignant_percentage_and_invalid_score(self):
        self.assertIn("patrón maligno", describe_result(0.8))
        self.assertIn("Maligna: 80.0 %", describe_result(0.8))
        self.assertIn("Benigna: 20.0 %", describe_result(0.8))
        with self.assertRaises(ValueError):
            describe_result(float("nan"))

    def test_auto_analysis_after_capture_and_reframe(self):
        from types import SimpleNamespace

        self.app.frame = Image.new("RGB", (224, 224))
        self.app.captured = True
        self.app.assessment = SimpleNamespace(checks=(True,) * 4)
        callbacks = []
        with patch.object(
            self.root,
            "after",
            side_effect=lambda ms, callback: callbacks.append(callback) or "pending",
        ), patch.object(self.app, "analyze") as analyze:
            self.app.schedule_analysis()
            callbacks.pop()()
            analyze.assert_called_once()
            self.app.schedule_analysis()
            self.app.revision += 1
            callbacks.pop()()
            analyze.assert_called_once()

    def test_explanation_failure_preserves_binary_result(self):
        self.app.busy = True
        self.app.messages.put(
            (
                "ok",
                (
                    "analysis",
                    dict(
                        accepted=True,
                        score=0.8,
                        decision="malignant",
                        explanation=None,
                        explanation_error="fallo de explicación",
                        matches=[],
                        reference_error=None,
                    ),
                    self.app.revision,
                ),
            )
        )
        with patch("interfaz.messagebox.showerror") as error:
            self.app.poll()
            error.assert_not_called()
        self.assertIn("Maligna: 80.0 %", self.app.result.get())
        self.assertIn("Explicación visual no disponible", self.app.status.get())
        self.assertIsNone(self.app.last_explanation)

    def test_score_visible_while_explanation_is_loading(self):
        self.app.busy = True
        self.app.messages.put(
            ("score", ({"score": 0.8, "decision": "malignant"}, self.app.revision))
        )
        self.app.poll()
        self.assertTrue(self.app.busy)
        self.assertIn("Maligna: 80.0 %", self.app.result.get())
        self.assertIn("Preparando explicación visual", self.app.status.get())

    def test_clean_layout_at_supported_sizes(self):
        self.root.deiconify()
        for width, height in ((1050, 720), (1220, 800), (1360, 900)):
            self.root.geometry(f"{width}x{height}")
            self.root.update()
            self.assertFalse(self.app.reference_cards.winfo_ismapped())
            self.assertIn("Sin captura", self.app.region_preview.cget("text"))
            self.assertGreater(self.app.region_preview.winfo_height(), 90)
            self.assertGreater(self.app.preview.winfo_width(), 500)
            for widget in (
                self.app.analyze_button,
                self.app.explain_button,
                self.app.result_text,
            ):
                self.assertTrue(widget.winfo_ismapped())
                self.assertLessEqual(
                    widget.winfo_rooty() + widget.winfo_height(),
                    self.root.winfo_rooty() + self.root.winfo_height(),
                )


if __name__ == "__main__":
    unittest.main()
