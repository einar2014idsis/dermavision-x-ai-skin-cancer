import tkinter as tk
import unittest

from PIL import Image

from comparison_inspector import ComparisonInspector, SharedViewport, viewport_geometry


class ViewportTests(unittest.TestCase):
    def test_fit_preserves_portrait_and_landscape_proportions(self):
        for size in ((1200, 600), (600, 1200)):
            x, y, w, h = viewport_geometry(size, (500, 400))
            self.assertAlmostEqual(w / h, size[0] / size[1])
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(w, 500)
            self.assertLessEqual(h, 400)

    def test_zoom_holds_cursor_position_in_image_and_is_bounded(self):
        viewport = SharedViewport()
        viewport.zoom_at(2, (1000, 1000), (400, 400), (100, 100))
        x, y, width, height = viewport_geometry((1000, 1000), (400, 400), viewport.zoom, viewport.center)
        self.assertAlmostEqual((100 - x) / width, 0.25)
        self.assertAlmostEqual((100 - y) / height, 0.25)
        viewport.zoom_at(100, (1000, 1000), (400, 400))
        self.assertEqual(viewport.zoom, 8)
        viewport.zoom_at(0.001, (1000, 1000), (400, 400))
        self.assertEqual(viewport.zoom, 1)
        self.assertEqual(viewport.center, (0.5, 0.5))

    def test_panning_has_no_hidden_effect_at_fit_and_cannot_expose_empty_edges(self):
        viewport = SharedViewport()
        viewport.pan((300, 300), (1000, 1000), (400, 400))
        self.assertEqual(viewport.center, (0.5, 0.5))
        viewport.zoom_at(3, (1000, 1000), (400, 400))
        viewport.pan((10000, -10000), (1000, 1000), (400, 400))
        x, y, width, height = viewport_geometry((1000, 1000), (400, 400), viewport.zoom, viewport.center)
        self.assertLessEqual(x, 0)
        self.assertLessEqual(y, 0)
        self.assertGreaterEqual(x + width, 400)
        self.assertGreaterEqual(y + height, 400)


class InspectorWindowTests(unittest.TestCase):
    def test_zoom_renders_both_images_without_altering_originals(self):
        root = tk.Tk()
        root.withdraw()
        first = Image.new("RGB", (600, 400), "red")
        second = Image.new("RGB", (400, 600), "blue")
        inspector = ComparisonInspector(root, first, second, "01/01/2026", "01/02/2026")
        try:
            root.update()
            inspector.zoom(8)
            if inspector.render_job is not None:
                inspector.window.after_cancel(inspector.render_job)
            inspector.render()
            for canvas, photo in zip(inspector.canvases, inspector.photos):
                self.assertEqual(len(canvas.find_all()), 1)
                self.assertLessEqual(photo.width(), canvas.winfo_width() + 20)
                self.assertLessEqual(photo.height(), canvas.winfo_height() + 20)
            self.assertEqual(first.size, (600, 400))
            self.assertEqual(second.size, (400, 600))
            self.assertEqual(first.getpixel((0, 0)), (255, 0, 0))
            inspector.reset()
            self.assertEqual(inspector.viewport.zoom, 1)
        finally:
            inspector.close()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
