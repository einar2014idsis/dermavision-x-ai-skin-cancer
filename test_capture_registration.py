"""Follow-up capture cannot approve unrelated content or affect individual analysis."""

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
import numpy as np
from interfaz import App
from longitudinal_capture import CaptureReview, FollowupCaptureDialog
from longitudinal_ui import EvolutionWindow
from longitudinal_store import LongitudinalStore
from test_longitudinal import sample
from test_visit_workflow import FixedModel, Gate


class CaptureRegistrationTests(unittest.TestCase):
    def test_content_rejection_uncertainty_and_bad_quality_cannot_approve(self):
        review = CaptureReview()
        image, _ = sample()
        for analysis in (
            {"state": "rejected"},
            {"state": "uncertain", "reason": "domain"},
            {"state": "quality_failed"},
            {"state": "unavailable"},
            {"state": "accepted", "quality": {"checks": [True, False, True]}},
        ):
            self.assertFalse(review.approve(image, analysis))
            self.assertFalse(review.matches(image))
            with self.assertRaises(ValueError):
                review.snapshot(image)

    def test_approval_belongs_to_exact_image_and_can_be_revoked(self):
        review = CaptureReview()
        image, _ = sample()
        self.assertTrue(
            review.approve(
                image, {"state": "accepted", "quality": {"checks": [True] * 3}}
            )
        )
        self.assertTrue(review.matches(image.copy()))
        changed = image.copy()
        changed.putpixel((0, 0), (0, 0, 0))
        self.assertFalse(review.matches(changed))
        self.assertFalse(review.matches(image.crop((0, 0, 150, 150))))
        review.clear()
        self.assertFalse(review.matches(image))

    def test_classifier_abstention_can_be_saved_after_content_acceptance(self):
        review = CaptureReview()
        image, _ = sample()
        self.assertTrue(
            review.approve(
                image,
                dict(
                    state="uncertain",
                    reason="score_uncertainty",
                    quality={"checks": [True] * 3},
                ),
            )
        )
        self.assertEqual(review.snapshot(image)[0]["state"], "uncertain")


class CaptureRegistrationWindowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)
        if self.app.autoload_job:
            self.root.after_cancel(self.app.autoload_job)
            self.app.autoload_job = None
        self.app.model = FixedModel(0.8)
        self.app.domain_gate = Gate("accepted")
        self.temp = tempfile.TemporaryDirectory()
        self.store = LongitudinalStore(Path(self.temp.name) / "store")
        self.lesion = self.store.create_lesion("P01", "Brazo")
        self.owner = EvolutionWindow(self.app, self.store)
        self.app.evolution_window = self.owner
        self.owner.lesion_id = self.lesion
        self.owner.refresh_history()
        self.dialog = None
        self.explanation = patch(
            "explainability.occlusion_explanation",
            return_value=(sample()[0], np.ones((224, 224))),
        )
        self.explanation.start()

    def tearDown(self):
        if self.dialog and not self.dialog.closed:
            self.dialog.close()
        self.explanation.stop()
        self.app.closed = True
        if self.owner.poll_job:
            self.owner.window.after_cancel(self.owner.poll_job)
        for job in (self.app.poll_job, self.app.analysis_job):
            if job:
                self.root.after_cancel(job)
        self.app.stop_camera()
        self.root.destroy()
        self.temp.cleanup()

    def settle(self):
        deadline = time.monotonic() + 8
        while self.dialog.pending and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.dialog.pending)
        self.assertFalse(self.app.busy)

    def test_file_review_rejects_before_contour_and_preserves_individual_screen(self):
        individual = (
            self.app.frame,
            self.app.revision,
            self.app.capture_heading.cget("text"),
            tuple(
                w.cget("text")
                for w in self.app.root.winfo_children()
                if w.winfo_class() == "Button"
            ),
        )
        image, mask = sample()
        self.app.domain_gate = Gate("rejected")
        self.dialog = FollowupCaptureDialog(self.owner, image=image)
        self.assertEqual(len(self.dialog.check_labels), 4)
        self.assertFalse(self.dialog.capture_button.winfo_manager())
        with patch("longitudinal_ui.RecordEditor") as editor:
            self.settle()
            self.dialog.proceed()
            editor.assert_not_called()
            self.assertEqual(self.dialog.next_button.cget("state"), "disabled")
            self.assertEqual(self.store.records(self.lesion), [])
            self.app.domain_gate = Gate("uncertain")
            self.dialog.load_image(image)
            self.settle()
            self.assertEqual(self.dialog.next_button.cget("state"), "disabled")
            self.app.domain_gate = Gate("accepted")
            self.dialog.load_image(image)
            self.settle()
            self.assertEqual(self.dialog.next_button.cget("state"), "normal")
            self.dialog.proceed()
            editor.assert_called_once()
            save = editor.call_args.args[2]
            save("2026-10-11", image, mask, dict(mask_reviewed=True))
        record = self.store.records(self.lesion)[0]
        self.assertTrue(record["metadata"]["domain_verified"])
        self.assertEqual(record["metadata"]["classification"]["label"], "malignant")
        self.assertEqual(self.store.load_explanation(record["id"]).size, image.size)
        self.assertEqual(
            individual,
            (
                self.app.frame,
                self.app.revision,
                self.app.capture_heading.cget("text"),
                tuple(
                    w.cget("text")
                    for w in self.app.root.winfo_children()
                    if w.winfo_class() == "Button"
                ),
            ),
        )

    def test_dark_file_blocks_review_and_contour(self):
        with patch.object(
            self.app.domain_gate, "assess", wraps=self.app.domain_gate.assess
        ) as gate:
            self.dialog = FollowupCaptureDialog(
                self.owner, image=Image.new("RGB", (160, 160), "black")
            )
            self.assertFalse(self.dialog.pending)
            gate.assert_not_called()
            self.assertEqual(self.dialog.next_button.cget("state"), "disabled")

    def test_camera_checks_stability_before_capture_and_records_capture_time(self):
        from capture_guide import CaptureGuide

        image, _ = sample()
        camera = Mock()
        camera.isOpened.return_value = True
        camera.read.return_value = (True, np.asarray(image)[:, :, ::-1])
        with patch("cv2.VideoCapture", return_value=camera):
            self.dialog = FollowupCaptureDialog(self.owner, source="camera")
            self.dialog.auto_capture.set(False)
            self.assertEqual(self.dialog.capture_button.cget("state"), "disabled")
            self.dialog.take()
            self.assertFalse(self.dialog.pending)
            self.dialog.guide = CaptureGuide(hold_seconds=0.01, warmup_seconds=0)
            deadline = time.monotonic() + 2
            while (
                self.dialog.capture_button.cget("state") != "normal"
                and time.monotonic() < deadline
            ):
                self.root.update()
                time.sleep(0.02)
            self.assertEqual(self.dialog.capture_button.cget("state"), "normal")
            self.dialog.take()
            self.settle()
        camera.release.assert_called_once()
        self.assertEqual(self.dialog.metadata["source_kind"], "camera")
        self.assertIn("T", self.dialog.metadata["source_captured_at"])
        self.assertEqual(self.dialog.next_button.cget("state"), "normal")

    def test_camera_auto_capture_verifies_once_when_ready(self):
        from capture_guide import Assessment
        image, _ = sample()
        camera = Mock()
        camera.isOpened.return_value = True
        camera.read.return_value = (True, np.asarray(image)[:, :, ::-1])
        ready = Assessment(True, "Lista", 120, 80, progress=1, checks=(True,) * 4)
        with patch("cv2.VideoCapture", return_value=camera), patch("capture_guide.CaptureGuide.evaluate", return_value=ready):
            self.dialog = FollowupCaptureDialog(self.owner, source="camera")
            self.settle()
        camera.release.assert_called_once()
        self.assertEqual(self.dialog.metadata["source_kind"], "camera")
        self.assertEqual(self.dialog.next_button.cget("state"), "normal")

    def test_editor_rechecks_photo_approval_before_persistence(self):
        image, mask = sample()
        self.dialog = FollowupCaptureDialog(self.owner, image=image)
        self.settle()
        with patch("longitudinal_ui.RecordEditor") as editor:
            self.dialog.proceed()
            save = editor.call_args.args[2]
        self.owner.capture_review.clear()
        with self.assertRaises(ValueError):
            save("2026-10-11", image, mask, {"mask_reviewed": True})
        self.assertEqual(self.store.records(self.lesion), [])


if __name__ == "__main__":
    unittest.main()
