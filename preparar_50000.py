"""Selecciona recortes ISIC 2024 hasta completar 50.000 imágenes únicas."""
import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from random import Random
from zipfile import ZipFile

from PIL import Image, ImageOps

from preparar_combinado import pixel_hash
from preparar_isic2019 import read_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("manifest", "source", "output"):
        parser.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    rows = read_csv(args.manifest)
    train = sum(row["split"] == "train" and row["included"] == "true" for row in rows)
    needed = 50000 - train
    if needed <= 0:
        raise ValueError("El manifiesto base ya contiene 50.000 imágenes o más.")
    print(f"Base: {train}. Se necesitan {needed} imágenes adicionales.", flush=True)
    existing = {r["image_id"] for r in rows}
    # La auditoría de ampliación usó este mismo preprocesado para todas las fuentes.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        hashes = set(pool.map(pixel_hash, (row["path"] for row in rows)))
    root = args.source
    supplement = {r["isic_id"]: r for r in read_csv(root / "ISIC_2024_Training_Supplement.csv")}
    lesions = {r["lesion_id"] for r in rows if r.get("lesion_id")}
    candidates = [r for r in read_csv(root / "ISIC_2024_Training_GroundTruth.csv")
                  if r["isic_id"] not in existing and r["malignant"] in {"0.0", "1.0"}]
    rng = Random(2026)
    rng.shuffle(candidates)
    candidates.sort(key=lambda row: row["malignant"] != "1.0")
    args.output.mkdir(parents=True)
    images = args.output.resolve() / "images"
    images.mkdir()
    selected = []
    with ZipFile(root / "ISIC_2024_Training_Input.zip") as archive:
        names = {Path(name).stem: name for name in archive.namelist()
                 if Path(name).suffix.lower() == ".jpg"}
        for row in candidates:
            identifier = row["isic_id"]
            meta = supplement.get(identifier, {})
            lesion = meta.get("lesion_id", "")
            if identifier not in names or (lesion and lesion in lesions):
                continue
            content = archive.read(names[identifier])
            with Image.open(io.BytesIO(content)) as img:
                rgb = ImageOps.exif_transpose(img).convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
                digest = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
            if digest in hashes:
                continue
            hashes.add(digest)
            if lesion:
                lesions.add(lesion)
            path = images / f"{identifier}.jpg"
            path.write_bytes(content)
            selected.append(dict(image_id=identifier, path=str(path), source="ISIC-2024",
                                 diagnosis_original=meta.get("iddx_full", ""),
                                 label=str(int(float(row["malignant"]))), sha256=digest,
                                 lesion_id=lesion, group_id=f"ISIC-2024:{lesion or identifier}",
                                 split="train", included="true"))
            if len(selected) == needed:
                break
    if len(selected) != needed:
        raise ValueError(f"Solo se encontraron {len(selected)} imágenes de las {needed} necesarias.")
    all_rows = rows + selected
    fields = list(dict.fromkeys(k for row in all_rows for k in row))
    with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(all_rows)
    counts = Counter(f"{r['source']}/{r['label']}" for r in selected)
    report = dict(train_total=train + len(selected), added=counts,
                  original_validation=sum(r["split"] == "validation" and r["source"] != "PAD-UFES-20" for r in rows))
    (args.output / "audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
