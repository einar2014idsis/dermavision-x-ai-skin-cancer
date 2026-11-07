import tempfile
import unittest
from pathlib import Path
from PIL import Image
from dermavision import audit, prepare


class AuditTests(unittest.TestCase):
    def fixture(self, root):
        for s, split in enumerate(("train", "test")):
            for label, name in enumerate(("benign", "malignant")):
                folder = root / split / name
                folder.mkdir(parents=True)
                for i in range(5):
                    Image.new("RGB", (16, 16), (s * 100, label * 100, i * 20)).save(
                        folder / f"{i}.png"
                    )

    def test_split_preserves_test_and_requires_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            self.fixture(root)
            with self.assertRaises(ValueError):
                prepare(root, Path(tmp) / "blocked")
            counts = prepare(root, Path(tmp) / "prepared", True)
            self.assertEqual(counts["test/0"], 5)
            self.assertEqual(counts["train/1"], 4)
            self.assertEqual(counts["validation/1"], 1)

    def test_leakage_blocks_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            self.fixture(root)
            Image.open(root / "train/benign/0.png").save(root / "test/benign/leak.png")
            _, report = audit(root)
            self.assertEqual(len(report["cross_split_duplicates"]), 1)
            with self.assertRaises(ValueError):
                prepare(root, Path(tmp) / "prepared", True)


if __name__ == "__main__":
    unittest.main()
