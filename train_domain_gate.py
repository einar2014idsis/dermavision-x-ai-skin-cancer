"""Entrenamiento reproducible del filtro con lesiones locales y negativos CIFAR-100.

No usa imágenes de cámara ni sube datos. CIFAR es un proxy de objetos, no una
validación de fotografías de celular, piel sana ni todas las patologías cutáneas.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import tarfile

import numpy as np
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, confusion_matrix
from sklearn.preprocessing import StandardScaler

from domain_gate import feature_model, gate_pixels, gate_scores

SEED = 2026


def save(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def display_variant(image, seed):
    """Perturbación sintética de iluminación, giro y desenfoque. No es cámara real."""
    rng = np.random.default_rng(seed)
    image = image.convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
    image = ImageEnhance.Brightness(image).enhance(float(rng.uniform(0.75, 1.2)))
    image = ImageEnhance.Contrast(image).enhance(float(rng.uniform(0.8, 1.2)))
    image = image.rotate(
        float(rng.uniform(-8, 8)),
        resample=Image.Resampling.BILINEAR,
        fillcolor=tuple(np.asarray(image).reshape(-1, 3).mean(axis=0).astype(int)),
    )
    return image.filter(ImageFilter.GaussianBlur(float(rng.uniform(0, 0.8))))


def cifar_arrays(path):
    if hashlib.md5(path.read_bytes()).hexdigest() != "03b5dce01913d631647c71ecec9e9cb8":
        raise ValueError("Checksum CIFAR-100 no coincide con la fuente oficial.")
    result = {}
    with tarfile.open(path) as archive:
        names = (
            archive.extractfile("cifar-100-binary/fine_label_names.txt")
            .read()
            .decode()
            .splitlines()
        )
        for split in ("train", "test"):
            data = np.frombuffer(
                archive.extractfile(f"cifar-100-binary/{split}.bin").read(),
                dtype="uint8",
            ).reshape(-1, 3074)
            result[split] = (
                data[:, 2:].reshape(-1, 3, 32, 32).transpose(0, 2, 3, 1),
                data[:, 1],
            )
    return result, names


def report(labels, scores, threshold):
    tn, fp, fn, tp = confusion_matrix(
        labels, scores >= threshold, labels=[0, 1]
    ).ravel()
    return dict(
        images=len(labels),
        accepted_lesions=int(tp),
        rejected_lesions=int(fn),
        rejected_objects=int(tn),
        accepted_objects=int(fp),
        lesion_acceptance=float(tp / (tp + fn)),
        object_rejection=float(tn / (tn + fp)),
        auc=float(roc_auc_score(labels, scores)),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runs/domain-01")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(exist_ok=False)
    experiment = Path("runs/functional-02")
    archive = Path("runs/gate-data/cifar-100-binary.tar.gz")
    cifar, names = cifar_arrays(archive)
    with (experiment / "manifest.csv").open(encoding="utf-8") as stream:
        originals = list(csv.DictReader(stream))
    rows = [
        dict(
            source="local",
            source_split=r["split"],
            index=-1,
            path=r["path"],
            category="lesion_" + r["label"],
            label=1,
            split=r["split"],
            sha256=r["sha256"],
        )
        for r in originals
    ]
    rng = np.random.default_rng(SEED)
    seen = {r["sha256"] for r in rows}
    duplicate_count = 0
    for source_split in ("train", "test"):
        images, labels = cifar[source_split]
        for cls, name in enumerate(names):
            indices = rng.permutation(np.flatnonzero(labels == cls))
            # 30 train + 10 validation per category; all 100 test bottles and
            # 10 held-out examples per other category.
            limit = 40 if source_split == "train" else (100 if name == "bottle" else 10)
            for n, idx in enumerate(indices[:limit]):
                image = images[idx]
                digest = hashlib.sha256(
                    str((32, 32)).encode() + image.tobytes()
                ).hexdigest()
                if digest in seen:
                    duplicate_count += 1
                    continue
                seen.add(digest)
                split = (
                    ("train" if n < 30 else "validation")
                    if source_split == "train"
                    else "test"
                )
                rows.append(
                    dict(
                        source="cifar100",
                        source_split=source_split,
                        index=int(idx),
                        path="",
                        category=name,
                        label=0,
                        split=split,
                        sha256=digest,
                    )
                )
    with (output / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("Datos:", dict(Counter((r["split"], r["label"]) for r in rows)), flush=True)
    import tensorflow as tf

    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    tf.keras.utils.set_random_seed(SEED)
    model = tf.keras.models.load_model(experiment / "model.keras", compile=False)
    features = feature_model(model)

    def read(row):
        if row["source"] == "cifar100":
            return Image.fromarray(cifar[row["source_split"]][0][row["index"]])
        with Image.open(row["path"]) as image:
            return ImageOps.exif_transpose(image).convert("RGB")

    def extract(selected, augmented=False):
        values = []
        for start in range(0, len(selected), 32):
            batch = []
            for i, row in enumerate(selected[start : start + 32]):
                image = read(row)
                if augmented:
                    image = display_variant(image, SEED + start + i)
                batch.append(gate_pixels(image))
            values.append(features(np.stack(batch), training=False).numpy())
            if start % 512 == 0:
                print(
                    f"Características {start}/{len(selected)}, perturbadas={augmented}",
                    flush=True,
                )
        return np.concatenate(values)

    partitions = {}
    for split in ("train", "validation"):
        selected = [r for r in rows if r["split"] == split]
        x = extract(selected)
        y = np.array([r["label"] for r in selected])
        # Las variantes permanecen en la partición de su imagen de origen.
        x = np.concatenate([x, extract(selected, True)])
        y = np.concatenate([y, y])
        partitions[split] = (x, y)
    scaler = StandardScaler().fit(partitions["train"][0])
    clf = LogisticRegression(
        C=0.1, max_iter=2000, class_weight="balanced", random_state=SEED
    )
    clf.fit(scaler.transform(partitions["train"][0]), partitions["train"][1])
    weights = clf.coef_[0] / scaler.scale_
    params = dict(
        schema="dermavision-domain-v1",
        weights=weights.tolist(),
        bias=float(clf.intercept_[0] - weights @ scaler.mean_),
        seed=SEED,
        classifier_sha256=hashlib.sha256(
            (experiment / "model.keras").read_bytes()
        ).hexdigest(),
    )
    vx, vy = partitions["validation"]
    vs = gate_scores(vx, params)
    threshold = None
    for candidate in np.linspace(0.5, 0.999, 500):
        m = report(vy, vs, candidate)
        if m["object_rejection"] >= 0.98 and m["lesion_acceptance"] >= 0.85:
            threshold = float(candidate)
            break
    params["validation_passed"] = threshold is not None
    params["threshold"] = threshold if threshold is not None else 0.999
    save(output / "gate.json", params)
    results = dict(
        validation=report(vy, vs, params["threshold"]),
        threshold=params["threshold"],
        validation_counts_include_synthetic_variants=True,
        exact_duplicates_removed=duplicate_count,
        criteria=dict(object_rejection=0.98, lesion_acceptance=0.85),
        source="https://www.cs.toronto.edu/~kriz/cifar.html",
        limitations=[
            "CIFAR-100 de 32x32 es un proxy de objetos; no valida cámara/celular.",
            "Sin negativos de piel sana o patologías no incluidas.",
            "Independencia por paciente no verificada; no detecta duplicados aproximados.",
            "La aceptación no confirma lesión ni malignidad; el filtro puede fallar.",
        ],
    )
    # Test solamente después de fijar umbral.
    selected = [r for r in rows if r["split"] == "test"]
    ty = np.array([r["label"] for r in selected])
    scores = gate_scores(extract(selected), params)
    results["test"] = report(ty, scores, params["threshold"])
    bs = scores[[r["category"] == "bottle" for r in selected]]
    results["bottles"] = dict(
        images=len(bs), rejected=int((bs < params["threshold"]).sum())
    )
    perturbed = gate_scores(extract(selected, True), params)
    results["synthetic_display_test"] = report(ty, perturbed, params["threshold"])
    with (output / "test_predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "source",
                "source_split",
                "index",
                "path",
                "category",
                "label",
                "score",
                "perturbed_score",
            ]
        )
        writer.writerows(
            [
                r["source"],
                r["source_split"],
                r["index"],
                r["path"],
                r["category"],
                r["label"],
                float(s),
                float(ps),
            ]
            for r, s, ps in zip(selected, scores, perturbed)
        )
    save(output / "metrics.json", results)
    print(json.dumps(results, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
