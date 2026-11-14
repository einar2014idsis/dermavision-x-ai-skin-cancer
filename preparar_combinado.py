"""Integra el ZIP histórico con el manifiesto auditado de ISIC 2019."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageOps
from sklearn.model_selection import StratifiedGroupKFold

from preparar_isic2019 import UnionFind, read_csv


def pixel_hash(path):
    with Image.open(path) as image:
        rgb = ImageOps.exif_transpose(image).convert("RGB").resize(
            (224, 224), Image.Resampling.BILINEAR
        )
        return hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "historical", "isic", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    historical = {r["path"].removeprefix("dataset/"): r for r in read_csv(args.historical)
                  if r["split"] == "test"}
    if not historical:
        raise ValueError("Falta el test histórico.")
    output = args.output.resolve()
    output.mkdir(parents=True)
    rows = []
    with ZipFile(args.archive) as archive:
        for name in sorted(archive.namelist()):
            parts = name.split("/")
            if len(parts) != 4 or parts[0] != "data":
                continue
            _, split, category, filename = parts
            if split not in {"train", "test"} or category not in {"benign", "malignant"}:
                continue
            if Path(filename).suffix.lower() not in {".jpg", ".jpeg", ".png"}:
                continue
            if "/" in filename or chr(92) in filename or ":" in filename:
                raise ValueError(name)
            rel = "/".join(parts[1:])
            source = "OWN" if split == "train" else "OWN-HISTORICAL-TEST"
            path = output / "images" / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(archive.read(name))
            rows.append(dict(image_id=f"{source}:{rel}", path=str(path), source=source,
                             label=str(int(category == "malignant")), group_id=f"{source}:{rel}",
                             split=split, included="true", historical_key=rel))
    for row in read_csv(args.isic):
        if row["included"] == "true":
            rows.append({key: row[key] for key in ("image_id", "source", "label", "group_id", "included")}
                        | {"path": str((args.isic.resolve().parent / row["path"]).resolve()), "split": "train"})
    with ThreadPoolExecutor(max_workers=6) as pool:
        for row, digest in zip(rows, pool.map(pixel_hash, (r["path"] for r in rows))):
            row["sha256"] = digest
    test = [r for r in rows if r["split"] == "test"]
    if {r["historical_key"] for r in test} != historical.keys():
        raise ValueError("Los archivos de prueba difieren del manifiesto histórico.")
    for row in test:
        expected = historical[row["historical_key"]]
        if (row["sha256"], row["label"]) != (expected["sha256"], expected["label"]):
            raise ValueError(f"Prueba histórica incompatible: {row['path']}")
    uf = UnionFind()
    hashes = defaultdict(list)
    for row in rows:
        hashes[row["sha256"]].append(row)
    for group in hashes.values():
        for row in group[1:]:
            uf.union(group[0]["group_id"], row["group_id"])
    for row in rows:
        row["group_id"] = uf.find(row["group_id"])
    test_groups = {r["group_id"] for r in test}
    by_group = defaultdict(list)
    for row in rows:
        if row["split"] == "train" and row["group_id"] not in test_groups:
            by_group[row["group_id"]].append(row)
    fitting = []
    for group in by_group.values():
        if len({r["label"] for r in group}) == 1:
            seen = set()
            for row in group:
                if row["sha256"] not in seen:
                    fitting.append(row)
                    seen.add(row["sha256"])
    labels = [r["source"] + "/" + r["label"] for r in fitting]
    groups = [r["group_id"] for r in fitting]
    splitter = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=2026)
    _, validation = next(splitter.split(fitting, labels, groups))
    for index in validation:
        fitting[index]["split"] = "validation"
    selected = fitting + test
    counts = Counter(f"{r['split']}/{r['source']}/{r['label']}" for r in selected)
    columns = ["image_id", "path", "source", "label", "group_id", "split", "included", "sha256"]
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(selected)
    (output / "audit.json").write_text(json.dumps({
        "counts": counts, "historical_test_verified": len(test),
        "excluded": len(rows) - len(selected), "patient_independence_verified": False
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
