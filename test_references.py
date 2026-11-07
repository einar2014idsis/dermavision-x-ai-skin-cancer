import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from references import ReferenceIndex


class ReferenceTests(unittest.TestCase):
    def test_search_both_labels_excludes_test_and_identical_image(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            rows = []
            for name, split, label, color in [
                ("query", "train", "0", (200, 10, 10)),
                ("similar", "train", "1", (190, 15, 15)),
                ("different", "train", "0", (10, 200, 10)),
                ("heldout", "test", "1", (199, 10, 10)),
            ]:
                path = folder / (name + ".png")
                Image.new("RGB", (224, 224), color).save(path)
                rows.append(dict(path=str(path), split=split, label=label))
            manifest = folder / "manifest.csv"
            with manifest.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["path", "split", "label"])
                writer.writeheader()
                writer.writerows(rows)

            def extractor(batch, training=False):
                return SimpleNamespace(numpy=lambda: np.mean(batch, axis=(1, 2)))

            index = ReferenceIndex(manifest, extractor)
            matches = index.search(Image.new("RGB", (224, 224), (200, 10, 10)))
            self.assertEqual([m["label"] for m in matches], ["Maligna", "Benigna"])
            self.assertIn("similar.png", matches[0]["source"])
            self.assertEqual(len(index.rows), 3)


if __name__ == "__main__":
    unittest.main()
