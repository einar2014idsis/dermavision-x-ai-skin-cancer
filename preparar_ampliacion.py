"""Amplía el manifiesto con diagnóstico explícito y reserva pacientes de celular."""
import argparse
import csv
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

from sklearn.model_selection import StratifiedGroupKFold

from preparar_combinado import pixel_hash
from preparar_isic2019 import UnionFind, read_csv

PAD = {"BCC": 1, "MEL": 1, "SCC": 1, "NEV": 0, "SEK": 0}
ISIC = {"melanoma": 1, "nevus": 0, "seborrheic keratosis": 0,
        "lentigo NOS": 0, "lichenoid keratosis": 0, "solar lentigo": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "raw", "isic2020_images", "output"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    original = read_csv(args.manifest)
    existing_ids = {r["image_id"] for r in original}
    with ThreadPoolExecutor(max_workers=6) as pool:
        original_hashes = set(pool.map(pixel_hash, (r["path"] for r in original)))
    args.output.mkdir(parents=True)
    pad_dir = args.raw / "pad-ufes-20"
    metadata = read_csv(pad_dir / "metadata.csv")
    images = args.output / "pad_images"
    images.mkdir()
    needed = {r["img_id"] for r in metadata if r["diagnostic"] in PAD}
    for file in sorted(pad_dir.glob("imgs_part_*.zip")):
        with ZipFile(file) as archive:
            for entry in archive.namelist():
                name = Path(entry).name
                if name in needed:
                    with (images / name).open("xb") as stream:
                        stream.write(archive.read(entry))
    uf = UnionFind()
    seen = {}
    excluded = Counter()

    def add(source, image_id, patient, lesion, diagnosis, label, path):
        if not patient or not lesion:
            raise ValueError(f"Identificadores incompletos: {image_id}")
        sha = pixel_hash(path)
        group = f"{source}:patient:{patient}"
        uf.union(group, f"{source}:lesion:{lesion}")
        if sha in original_hashes or image_id in existing_ids:
            excluded[source + "/overlap"] += 1
            uf.union(group, "baseline-overlap")
            return
        if sha in seen:
            previous = seen[sha]
            uf.union(group, previous["group_id"])
            if previous["label"] != str(label):
                uf.union(group, "conflict")
            excluded[source + "/duplicate"] += 1
            return
        seen[sha] = dict(image_id=image_id, path=str(path.resolve()), label=str(label),
                         source=source, diagnosis_original=diagnosis, sha256=sha, group_id=group,
                         patient_id=patient, lesion_id=lesion, split="train", included="true")

    isic_dir = args.raw / "isic2020"
    duplicates = {r[key] for r in read_csv(isic_dir / "ISIC_2020_Training_Duplicates.csv")
                  for key in ("image_name_1", "image_name_2")}
    for r in read_csv(isic_dir / "ISIC_2020_Training_GroundTruth_v2.csv"):
        name, diagnosis = r["image_name"], r["diagnosis"]
        if name in duplicates or diagnosis not in ISIC:
            excluded["ISIC-2020/duplicate_or_out_of_scope"] += 1
            continue
        label = ISIC[diagnosis]
        if r["benign_malignant"] != ("malignant" if label else "benign"):
            continue
        add("ISIC-2020", name, r["patient_id"], r["lesion_id"], diagnosis,
            label, args.isic2020_images / f"{name}.jpg")
    for r in metadata:
        diagnosis = r["diagnostic"]
        if diagnosis in PAD:
            add("PAD-UFES-20", r["img_id"], r["patient_id"], r["lesion_id"],
                diagnosis, PAD[diagnosis], images / r["img_id"])
        else:
            excluded["PAD-UFES-20/out_of_scope"] += 1
    bad = {uf.find("baseline-overlap"), uf.find("conflict")}
    extra = []
    for row in seen.values():
        row["group_id"] = uf.find(row["group_id"])
        if row["group_id"] in bad:
            excluded[row["source"] + "/group"] += 1
        else:
            extra.append(row)
    pad = [r for r in extra if r["source"] == "PAD-UFES-20"]
    labels, groups = ([r[key] for r in pad] for key in ("label", "group_id"))
    folds = list(StratifiedGroupKFold(5, shuffle=True, random_state=2026).split(pad, labels, groups))
    for split, (_, indices) in zip(("test", "validation"), folds):
        for i in indices:
            pad[i]["split"] = split
    for split in ("train", "validation", "test"):
        if {r["label"] for r in pad if r["split"] == split} != {"0", "1"}:
            raise ValueError(f"Faltan clases PAD en {split}")
    rows = original + extra
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, columns)
        writer.writeheader()
        writer.writerows(rows)
    report = {"counts": Counter(r["source"] + "/" + r["split"] for r in rows),
              "added_diagnoses": Counter(r["source"] + "/" + r["diagnosis_original"]
                                         for r in extra if r["split"] == "train"),
              "exclusions": excluded}
    (args.output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
