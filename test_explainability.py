import unittest
import numpy as np
from PIL import Image

from explainability import occlusion_explanation


class FakeOutput:
    def __init__(self, values):
        self.values = values

    def numpy(self):
        return self.values


class MeanModel:
    def __call__(self, batch, training=False):
        values = np.asarray(batch, dtype=float).mean(axis=(1, 2, 3)) / 255
        return FakeOutput(values[:, None])


class ExplainabilityTests(unittest.TestCase):
    def test_full_map_opacity_and_optional_contour_do_not_clip_exterior(self):
        from explainability import influence_view
        original = Image.new("RGB", (224, 224), (80, 80, 80))
        overlay = Image.new("RGB", (224, 224), (240, 220, 30))
        mask = Image.new("L", (224, 224), 0)
        mask.paste(255, (70, 70, 154, 154))
        np.testing.assert_array_equal(np.asarray(influence_view(original, overlay, mask)), np.asarray(overlay))
        np.testing.assert_array_equal(np.asarray(influence_view(original, overlay, mask, 0)), np.asarray(original))
        annotated = np.asarray(influence_view(original, overlay, mask, contour=True))
        np.testing.assert_array_equal(annotated[10, 10], np.asarray(overlay)[10, 10])
        np.testing.assert_array_equal(annotated[100, 100], np.asarray(overlay)[100, 100])

    def test_invalid_model_output_and_label_cannot_create_heatmap(self):
        image = Image.new("RGB", (224, 224), "white")
        with self.assertRaises(ValueError):
            occlusion_explanation(MeanModel(), image, "uncertain")
        with self.assertRaises(ValueError):
            occlusion_explanation(MeanModel(), image, "malignant", grid=0)

        def invalid(batch, training=False):
            return FakeOutput(np.full((len(batch), 1), float("nan")))

        with self.assertRaises(ValueError):
            occlusion_explanation(invalid, image, "malignant")

    def test_overlay_has_expected_size_and_finite_heatmap(self):
        image = Image.fromarray(np.full((180, 260, 3), 180, dtype=np.uint8))
        overlay, heatmap = occlusion_explanation(MeanModel(), image, "malignant")
        self.assertEqual(overlay.size, (224, 224))
        self.assertEqual(heatmap.shape, (224, 224))
        self.assertTrue(np.isfinite(heatmap).all())
        self.assertTrue((heatmap >= 0).all())

    def test_no_signal_keeps_original_without_fake_hotspots(self):
        from types import SimpleNamespace

        def constant(batch, training=False):
            return SimpleNamespace(numpy=lambda: np.full((len(batch), 1), 0.8))

        image = Image.new("RGB", (224, 224), (160, 130, 110))
        overlay, heat = occlusion_explanation(constant, image, "malignant")
        self.assertTrue(np.array_equal(np.asarray(overlay), np.asarray(image)))
        self.assertEqual(float(heat.max()), 0.0)
        self.assertFalse(overlay.info["explanation_stats"]["informative"])

    def test_known_center_feature_is_localized_and_not_shifted(self):
        class CenterModel:
            def __call__(self, batch, training=False):
                values = (
                    np.asarray(batch, dtype=float)[:, 90:134, 90:134].mean(
                        axis=(1, 2, 3)
                    )
                    / 255
                )
                return FakeOutput(values[:, None])

        pixels = np.full((224, 224, 3), 40, dtype=np.uint8)
        pixels[90:134, 90:134] = 230
        _, heat = occlusion_explanation(
            CenterModel(), Image.fromarray(pixels), "malignant"
        )
        self.assertGreater(
            float(heat[95:129, 95:129].mean()), float(heat[:30, :30].mean()) + 0.4
        )
        y, x = np.unravel_index(np.argmax(heat), heat.shape)
        self.assertTrue(60 < x < 164 and 60 < y < 164)

    def test_real_background_influence_is_not_forced_to_center(self):
        class CornerModel:
            def __call__(self, batch, training=False):
                values = (
                    np.asarray(batch, dtype=float)[:, :40, :40].mean(axis=(1, 2, 3))
                    / 255
                )
                return FakeOutput(values[:, None])

        pixels = np.full((224, 224, 3), 40, dtype=np.uint8)
        pixels[:40, :40] = 230
        _, heat = occlusion_explanation(
            CornerModel(), Image.fromarray(pixels), "malignant"
        )
        self.assertGreater(
            float(heat[:40, :40].mean()), float(heat[95:129, 95:129].mean()) + 0.4
        )

    def test_opposing_feature_is_visible_and_caption_explains_it(self):
        from explainability import explanation_diagnostics, explanation_caption

        class CenterModel:
            def __call__(self, batch, training=False):
                values = (
                    np.asarray(batch, dtype=float)[:, 90:134, 90:134].mean(
                        axis=(1, 2, 3)
                    )
                    / 255
                )
                return FakeOutput(values[:, None])

        pixels = np.full((224, 224, 3), 40, dtype=np.uint8)
        pixels[90:134, 90:134] = 230
        overlay, heat = occlusion_explanation(
            CenterModel(), Image.fromarray(pixels), "benign"
        )
        self.assertGreater(float(heat.max()), 0.5)
        self.assertGreater(overlay.info["explanation_stats"]["opposes_fraction"], 0)
        self.assertIn(
            "Azul", explanation_caption(explanation_diagnostics(overlay, heat))
        )

    def test_unsigned_palette_preserves_measured_influence_and_no_signal(self):
        from explainability import explanation_diagnostics, explanation_caption

        pixels = np.full((224, 224, 3), 40, dtype=np.uint8)
        pixels[90:134, 90:134] = 230
        image = Image.fromarray(pixels)
        signed, heat = occlusion_explanation(MeanModel(), image, "malignant")
        magnitude, same_heat = occlusion_explanation(
            MeanModel(), image, "malignant", display="magnitude-green-yellow"
        )
        np.testing.assert_array_equal(heat, same_heat)
        self.assertFalse(np.array_equal(np.asarray(signed), np.asarray(magnitude)))
        self.assertIn(
            "Amarillo",
            explanation_caption(explanation_diagnostics(magnitude, same_heat)),
        )
        self.assertIn(
            "no distingue",
            explanation_caption(explanation_diagnostics(magnitude, same_heat)),
        )
        constant = lambda batch, training=False: FakeOutput(
            np.full((len(batch), 1), 0.8)
        )
        blank, _ = occlusion_explanation(
            constant, image, "malignant", display="magnitude-green-yellow"
        )
        np.testing.assert_array_equal(np.asarray(blank), np.asarray(image))

    def test_reviewed_contour_is_a_display_annotation_not_a_new_heatmap(self):
        from explainability import with_reviewed_contour

        base = Image.new("RGB", (224, 224), "white")
        mask = Image.new("L", (224, 224), 0)
        mask.paste(255, (70, 70, 154, 154))
        rendered = with_reviewed_contour(base, mask)
        pixels = np.asarray(rendered)
        # An annotation must not invent green influence inside the region.
        np.testing.assert_array_equal(pixels[100, 100], np.array([255, 255, 255]))
        np.testing.assert_array_equal(pixels[10, 10], np.array([255, 255, 255]))

    def test_focused_view_filters_only_the_presentation(self):
        from explainability import focused_explanation_view

        original = Image.new("RGB", (224, 224), (90, 120, 150))
        overlay = Image.new("RGB", (224, 224), (255, 220, 20))
        mask = Image.new("L", (224, 224), 0)
        mask.paste(255, (70, 70, 154, 154))
        focused = np.asarray(focused_explanation_view(original, overlay, mask))
        # Measured overlay is retained inside; outside is visibly neutralized.
        np.testing.assert_array_equal(focused[100, 100], np.array([255, 220, 20]))
        self.assertEqual(int(focused[10, 10, 0]), int(focused[10, 10, 1]))
        self.assertEqual(int(focused[10, 10, 1]), int(focused[10, 10, 2]))


if __name__ == "__main__":
    unittest.main()
