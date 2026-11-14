"""Build a conservative, lesion-grouped binary manifest from official ISIC 2019 files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image
from sklearn.model_selection import StratifiedGroupKFold


MALIGNANT = {"MEL", "BCC", "SCC"}
BENIGN = {"NV", "BKL", "DF", "VASC"}
EXCLUDED = {"AK", "UNK"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True, help="ISIC 2019 image directory")
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    labels = {r["image"]: r for r in read_csv(args.ground_truth)}
    metadata = {r["image"]: r for r in read_csv(args.metadata)}
    paths = {p.stem: p.resolve() for p in args.images.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg"}}
    missing = sorted(set(labels) - set(paths))
    if missing:
        raise SystemExit(f"Faltan {len(missing)} imágenes; primera: {missing[0]}")

    rows: list[dict[str, object]] = []
    invalid: list[dict[str, str]] = []
    for image_id, raw in sorted(labels.items()):
        positive = [k for k, v in raw.items() if k != "image" and v == "1.0"]
        diagnosis = positive[0] if len(positive) == 1 else "AMBIGUOUS"
        label = 1 if diagnosis in MALIGNANT else 0 if diagnosis in BENIGN else None
        path = paths[image_id]
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                width, height = im.size
            digest = sha256(path)
        except Exception as exc:
            invalid.append({"image": image_id, "error": str(exc)})
            continue
        meta = metadata.get(image_id, {})
        lesion = (meta.get("lesion_id") or "").strip()
        rows.append({
            "image_id": image_id,
            "path": str(path),
            "source": "ISIC-2019",
            "diagnosis_original": diagnosis,
            "label": label,
            "lesion_id": lesion,
            "patient_id": "",
            "sha256": digest,
            "width": width,
            "height": height,
            "split": "",
            "included": "false" if label is None else "true",
            "exclusion_reason": "ambiguous_or_out_of_scope_diagnosis" if label is None else "",
            "duplicate_of": "",
        })

    # Exclude conflicting labels for byte-identical files. Collapse same-label duplicates.
    by_hash: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_hash[str(row["sha256"])].append(row)
    conflicts = 0
    exact_duplicate_rows = 0
    for group in by_hash.values():
        if len(group) < 2:
            continue
        exact_duplicate_rows += len(group) - 1
        active_labels = {r["label"] for r in group if r["label"] is not None}
        if len(active_labels) > 1:
            conflicts += 1
            for row in group:
                row["included"] = "false"
                row["exclusion_reason"] = "conflicting_labels_for_exact_duplicate"
            continue
        candidates = [r for r in group if r["label"] is not None]
        canonical = min(candidates, key=lambda r: str(r["image_id"])) if candidates else None
        for row in group:
            if canonical is None or row is not canonical:
                row["included"] = "false"
                row["duplicate_of"] = str(canonical["image_id"]) if canonical else ""
                row["exclusion_reason"] = "exact_duplicate"

    labels_by_lesion: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        lesion_id = str(row["lesion_id"])
        if row["included"] == "true" and lesion_id:
            labels_by_lesion[lesion_id].add(int(row["label"]))
    conflicting_lesions = {lesion for lesion, values in labels_by_lesion.items() if len(values) > 1}
    for row in rows:
        if str(row["lesion_id"]) in conflicting_lesions and row["included"] == "true":
            row["included"] = "false"
            row["exclusion_reason"] = "conflicting_diagnoses_within_lesion"

    # Keep lesions and identical images in one fold, even when they use different IDs.
    uf = UnionFind()
    active = [r for r in rows if r["included"] == "true"]
    by_lesion: dict[str, list[dict[str, object]]] = defaultdict(list)
    by_digest: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in active:
        image_id = str(row["image_id"])
        lesion_id = str(row["lesion_id"])
        group_id = f"lesion:{lesion_id}" if lesion_id else f"image:{image_id}"
        row["group_id"] = group_id
        by_lesion[group_id].append(row)
        by_digest[str(row["sha256"])].append(row)
    for members in by_digest.values():
        for row in members[1:]:
            uf.union(str(members[0]["group_id"]), str(row["group_id"]))

    # StratifiedGroupKFold: one fold for test, one fold of the remainder for validation.
    import numpy as np

    y = np.asarray([int(r["label"]) for r in active])
    groups = np.asarray([uf.find(str(r["group_id"])) for r in active])
    indices = np.arange(len(active))
    outer = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=2026)
    trainval_idx, test_idx = next(outer.split(indices, y, groups))
    inner = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=2027)
    train_idx, val_idx = next(inner.split(trainval_idx, y[trainval_idx], groups[trainval_idx]))
    for idx in train_idx:
        active[int(trainval_idx[idx])]["split"] = "train"
    for idx in val_idx:
        active[int(trainval_idx[idx])]["split"] = "validation"
    for idx in test_idx:
        active[int(idx)]["split"] = "test"

    # Record union component so future audits can verify there is no component leakage.
    for row in active:
        row["group_id"] = uf.find(str(row["group_id"]))

    args.output.mkdir(parents=True, exist_ok=True)
    columns = ["image_id", "path", "source", "diagnosis_original", "label", "lesion_id", "patient_id", "sha256", "width", "height", "group_id", "split", "included", "exclusion_reason", "duplicate_of"]
    with (args.output / "manifest_all.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    training_rows = [r for r in rows if r["included"] == "true"]
    with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(training_rows)

    # Component and label split checks are explicit outputs, not assumptions.
    groups_by_split: dict[str, set[str]] = defaultdict(set)
    for row in training_rows:
        groups_by_split[str(row["split"])].add(str(row["group_id"]))
    overlap = {
        f"{a}_vs_{b}": sorted(groups_by_split[a] & groups_by_split[b])
        for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))
    }
    report = {
        "source": "ISIC 2019 official training image, ground truth, and metadata files",
        "class_mapping": {"malignant": sorted(MALIGNANT), "benign": sorted(BENIGN), "excluded": sorted(EXCLUDED)},
        "raw_rows": len(labels),
        "valid_images": len(rows),
        "missing_images": len(missing),
        "invalid_images": invalid,
        "exact_duplicate_rows": exact_duplicate_rows,
        "conflicting_duplicate_groups": conflicts,
        "lesions_with_conflicting_labels": len(conflicting_lesions),
        "included_rows": len(training_rows),
        "included_by_label": dict(Counter(str(r["label"]) for r in training_rows)),
        "included_by_split": dict(Counter(str(r["split"]) for r in training_rows)),
        "included_by_split_label": dict(Counter(f"{r['split']}/label_{r['label']}" for r in training_rows)),
        "missing_lesion_id_count": sum(not str(r["lesion_id"]) for r in training_rows),
        "patient_independence_verified": False,
        "group_overlap_counts": {k: len(v) for k, v in overlap.items()},
        "group_overlap_examples": {k: v[:10] for k, v in overlap.items()},
        "random_seeds": {"test": 2026, "validation": 2027},
        "notes": [
            "ISIC 2019 metadata has lesion IDs but no patient IDs; split independence is by lesion/component only.",
            "MEL, BCC, SCC map to malignant; NV, BKL, DF, VASC map to benign.",
            "AK and ambiguous/unknown labels are excluded because they do not map unambiguously to this binary target.",
            "The original 3,296-image project dataset is unavailable locally, so its historical test cannot be reconstructed.",
            "This is an exploratory dermoscopic dataset, not external validation on phone photographs or a clinical-use claim.",
        ],
    }
    (args.output / "audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("raw_rows", "valid_images", "included_rows", "included_by_label", "included_by_split", "missing_lesion_id_count", "group_overlap_counts")}, indent=2))


if __name__ == "__main__":
    main()
