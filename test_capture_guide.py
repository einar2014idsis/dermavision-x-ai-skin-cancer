import unittest
from unittest.mock import Mock, patch
import numpy as np
import cv2
from PIL import Image
from capture_guide import CaptureGuide, Assessment
import tkinter as tk
from interfaz import App
from semantic_gate import DomainDecision


class QualityTests(unittest.TestCase):
    def test_high_sharpness_is_not_rejected(self):
        rng = np.random.default_rng(55)
        image = Image.fromarray(rng.integers(70, 190, (224, 224, 3), dtype=np.uint8))
        result = CaptureGuide().evaluate(image, static=True)
        self.assertGreater(result.sharpness, 1000)
        self.assertTrue(result.ready, result.message)

    def test_phone_brightness_and_small_hand_motion_allow_capture(self):
        rng = np.random.default_rng(12)
        pixels = rng.normal(150, 6, (224, 224))
        yy, xx = np.mgrid[:224, :224]
        pixels[(xx - 112) ** 2 + (yy - 112) ** 2 < 35**2] -= 65
        pixels = pixels.astype("uint8")
        guide = CaptureGuide(hold_seconds=0.45, warmup_seconds=0)
        for i in range(9):
            jitter = cv2.warpAffine(
                pixels,
                np.float32([[1, 0, i % 2], [0, 1, 0]]),
                (224, 224),
                borderMode=cv2.BORDER_REFLECT,
            )
            frame = Image.fromarray(jitter + (i % 2) * 8).convert("RGB")
            result = guide.evaluate(frame, i * 0.1)
        self.assertTrue(result.ready, result.message)
        moved = cv2.warpAffine(
            pixels,
            np.float32([[1, 0, 14], [0, 1, 0]]),
            (224, 224),
            borderMode=cv2.BORDER_REFLECT,
        )
        result = guide.evaluate(Image.fromarray(moved).convert("RGB"), 0.9)
        self.assertFalse(result.ready)
        self.assertFalse(result.checks[-1])

    def test_dark_bright_and_blur_block_capture(self):
        for color in (0, 128, 255):
            guide = CaptureGuide()
            for t in (0, 0.1, 0.2, 2):
                result = guide.evaluate(Image.new("RGB", (300, 300), (color,) * 3), t)
                self.assertFalse(result.ready)

    def test_centered_contrast_requires_hold_and_resets_on_failure(self):
        rng = np.random.default_rng(12)
        pixels = np.clip(rng.normal(160, 6, (224, 224)), 0, 255)
        yy, xx = np.mgrid[:224, :224]
        pixels[(xx - 112) ** 2 + (yy - 112) ** 2 < 35**2] -= 65
        sample = Image.fromarray(pixels.astype("uint8")).convert("RGB")
        guide = CaptureGuide(hold_seconds=0.3, warmup_seconds=0)
        self.assertFalse(guide.evaluate(sample, 0).ready)
        self.assertFalse(guide.evaluate(sample, 0.1).ready)
        self.assertTrue(guide.evaluate(sample, 0.45).ready)
        self.assertFalse(guide.evaluate(Image.new("RGB", (224, 224)), 0.5).ready)
        self.assertFalse(guide.evaluate(sample, 0.6).ready)


class GuidedInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)
        if self.app.autoload_job is not None:
            self.root.after_cancel(self.app.autoload_job)
            self.app.autoload_job = None

    def tearDown(self):
        self.app.close()

    def test_unverified_image_never_calls_classifier(self):
        self.app.model = Mock()
        self.app.activation_model = Mock()
        self.app.update_frame(Image.new("RGB", (640, 480), "gray"))
        self.app.analyze()
        self.app.activation_model.assert_not_called()
        self.assertIn("Sin clasificación", self.app.result.get())

    def test_capture_requires_ready_and_releases_camera(self):
        self.app.analyze = Mock()
        cap = Mock()
        self.app.cap = cap
        self.app.assessment = Assessment(False, "Espere", 120, 80)
        self.app.capture()
        cap.release.assert_not_called()
        self.app.assessment = Assessment(True, "Lista", 120, 80)
        self.app.capture()
        cap.release.assert_called_once()
        self.assertTrue(self.app.captured)
        self.app.analyze.assert_not_called()
        self.assertEqual(str(self.app.analyze_button["state"]), "disabled")

    def test_video_auto_captures_once_and_does_not_schedule_again(self):
        self.app.auto_capture.set(True)
        self.app.model = Mock()
        self.app.domain_gate = Mock()
        self.app.analyze = Mock()
        cap = Mock()
        cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
        self.app.cap = cap
        ready = Assessment(True, "Lista", 120, 80, progress=1, checks=(True,) * 4)
        with patch.object(self.app.guide, "evaluate", return_value=ready):
            self.app.tick()
        cap.release.assert_called_once()
        self.assertIsNone(self.app.camera_job)
        self.assertTrue(self.app.captured)
        self.assertIn("Captura tomada", self.app.instruction.get())

    def test_auto_disabled_keeps_video_running(self):
        self.app.model = Mock()
        self.app.domain_gate = Mock()
        cap = Mock()
        cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
        self.app.cap = cap
        self.app.auto_capture.set(False)
        ready = Assessment(True, "Lista", 120, 80, progress=1, checks=(True,) * 4)
        with patch.object(self.app.guide, "evaluate", return_value=ready):
            self.app.tick()
        cap.release.assert_not_called()
        self.assertIsNotNone(self.app.camera_job)
        self.assertEqual(str(self.app.capture_button["state"]), "normal")

    def test_redesign_has_no_network_canvas(self):
        self.assertFalse(hasattr(self.app, "network"))
        self.assertEqual(len(self.app.check_labels), 4)

    def prepare_inference(self, accepted):
        self.app.model = Mock()
        self.app.model.return_value.numpy.return_value = np.array([[0.8]])
        self.app.domain_gate = Mock()
        self.app.domain_gate.assess.return_value = DomainDecision(
            "accepted" if accepted else "rejected", "Mensaje", 0.1 if accepted else -0.1
        )
        self.app.update_frame(Image.new("RGB", (300, 300), "gray"))
        self.app.captured = True
        self.app.assessment = Assessment(True, "Lista", 120, 80, checks=(True,) * 4)
        self.app.work = lambda f: self.app.messages.put(("ok", f()))

    def test_rejected_object_never_reaches_malignancy_model(self):
        self.prepare_inference(False)
        self.app.analyze()
        self.app.poll()
        self.app.model.assert_not_called()
        self.assertIn("rechazada", self.app.result.get().casefold())
        self.assertNotIn("Puntuación", self.app.result.get())

    def test_accepted_image_reaches_classifier(self):
        self.prepare_inference(True)
        with patch(
            "interfaz.occlusion_explanation",
            return_value=(Image.new("RGB", (224, 224)), np.zeros((224, 224))),
        ) as explanation:
            self.app.analyze()
            explanation.assert_called_once()
        self.app.poll()
        self.app.poll()
        self.app.model.assert_called_once()
        self.assertIn("patrón maligno", self.app.result.get())

    def test_reframing_discards_old_inference(self):
        self.prepare_inference(True)
        self.app.analyze()
        self.app.update_frame(Image.new("RGB", (300, 300), "white"))
        self.app.poll()
        self.app.poll()
        self.assertIn("descartado", self.app.status.get())
        self.assertNotIn("maligna", self.app.result.get())

    def test_region_can_move_without_changing_crop_size(self):
        self.app.frame = Image.new("RGB", (640, 480))
        self.app.center = (0.9, 0.1)
        self.assertEqual(self.app.region().size, (360, 360))
        self.assertEqual(self.app.region_bounds(), (280, 0, 640, 360))

    def test_uncertain_skin_never_reaches_classifier(self):
        self.prepare_inference(False)
        self.app.domain_gate.assess.return_value = DomainDecision(
            "uncertain", "No concluyente", 0
        )
        self.app.analyze()
        self.app.poll()
        self.app.model.assert_not_called()
        self.assertIn("no concluyente", self.app.result.get().casefold())

    def test_default_is_automatic_and_capture_requires_review(self):
        self.assertTrue(self.app.auto_capture.get())
        self.app.model = Mock()
        self.app.domain_gate = Mock()
        self.app.cap = Mock()
        self.app.assessment = Assessment(True, "Lista", 120, 80, checks=(True,) * 4)
        self.app.capture()
        self.app.model.assert_not_called()
        self.app.domain_gate.assess.assert_not_called()
        self.assertEqual(str(self.app.analyze_button["state"]), "normal")

    def test_small_roi_can_be_reframed_after_quality_failure(self):
        self.app.model = Mock()
        self.app.domain_gate = Mock()
        self.app.full_image = False
        self.app.selection = (0.1, 0.1, 0.2, 0.2)
        rng = np.random.default_rng(5)
        self.app.frame = Image.fromarray(
            rng.integers(80, 180, (480, 640, 3), dtype="uint8")
        )
        self.app.refresh_selection()
        self.assertEqual(str(self.app.analyze_button["state"]), "disabled")
        self.app.reset_selection()
        self.assertTrue(self.app.captured)
        self.assertEqual(self.app.region().size, (640, 480))
        self.assertEqual(str(self.app.analyze_button["state"]), "normal")

    def test_drag_selection_preserves_aspect_and_pixels(self):
        self.app.frame = Image.new("RGB", (640, 480))
        self.app.full_image = False
        self.app.selection = (0.1, 0.25, 0.6, 0.75)
        self.assertEqual(self.app.region_bounds(), (64, 120, 384, 360))
        self.assertEqual(self.app.region().size, (320, 240))


class CaptureTimingTests(unittest.TestCase):
    def test_camera_warms_up_then_waits_two_seconds(self):
        rng = np.random.default_rng(12)
        sample = Image.fromarray(rng.integers(80, 180, (224, 224, 3), dtype="uint8"))
        guide = CaptureGuide()
        for step in range(50):
            self.assertFalse(guide.evaluate(sample, step / 10).ready)
        self.assertTrue(guide.evaluate(sample, 5.1).ready)
        guide.reset()
        self.assertFalse(guide.evaluate(sample, 5.2).ready)

    def test_static_file_does_not_wait_for_camera_stability(self):
        rng = np.random.default_rng(12)
        sample = Image.fromarray(rng.integers(80, 180, (224, 224, 3), dtype="uint8"))
        result = CaptureGuide().evaluate(sample, 0, static=True)
        self.assertTrue(result.ready)
        self.assertTrue(all(result.checks))


if __name__ == "__main__":
    unittest.main()
