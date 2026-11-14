"""Train/evaluate the experimental binary model from the audited ISIC manifest."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import sys
from collections import Counter
from pathlib import Path

import tensorflow as tf

from dermavision import build_model, dataset, metrics, save_json


def load_manifest(path: Path, splits=("train", "validation", "test")):
    subsets = {name: [] for name in splits}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("included") != "true":
                continue
            split = row["split"]
            if split not in subsets:
                if split in {"train", "validation", "test"}:
                    continue
                raise ValueError(f"Partición inesperada: {split!r}")
            resolved = (path.parent / row["path"]).resolve()
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            row["path"] = str(resolved)
            row["label"] = int(row["label"])
            subsets[split].append(row)
    for split, rows in subsets.items():
        if split == "test" and not rows:
            continue
        if not rows or {r["label"] for r in rows} != {0, 1}:
            raise ValueError(f"{split} debe contener imágenes de las dos clases.")
    return subsets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--test-manifest", type=Path, help="optional independent test manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--resume", action="store_true", help="resume from BackupAndRestore in the existing output folder")
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1:
        raise SystemExit("epochs y batch-size deben ser positivos")
    if args.output.exists() and not args.resume:
        raise SystemExit(f"La carpeta de salida ya existe; usa otra o --resume: {args.output}")
    if args.resume and not (args.output / "backup").is_dir():
        raise SystemExit("--resume requiere una carpeta backup creada por una corrida previa.")

    tf.keras.utils.set_random_seed(2026)
    gpus = tf.config.list_physical_devices("GPU")
    for gpu in gpus:
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except RuntimeError:
            pass

    splits = ("train", "validation") if args.test_manifest else ("train", "validation", "test")
    subsets = load_manifest(args.manifest, splits)
    if args.test_manifest:
        external = load_manifest(args.test_manifest, ("test",))
        subsets["test"] = external["test"]
    if not subsets["test"]:
        raise ValueError("Se requiere un test en --manifest o --test-manifest.")
    fitting = subsets["train"] + subsets["validation"]
    for key in ("path", "sha256", "group_id"):
        fitting_keys = {r[key] for r in fitting if r.get(key)}
        if any(r.get(key) in fitting_keys for r in subsets["test"]):
            raise ValueError(f"El test comparte {key} con entrenamiento o validación.")
    counts = Counter(int(r["label"]) for r in subsets["train"])
    class_weights = {label: len(subsets["train"]) / (2 * count) for label, count in counts.items()}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "checkpoints").mkdir(exist_ok=True)

    config = {
        "seed": 2026,
        "epochs_requested": args.epochs,
        "batch_size": args.batch_size,
        "image_size": 224,
        "class_mapping": {"benign": 0, "malignant": 1},
        "class_weights": class_weights,
        "optimizer": "Adam(1e-3)",
        "backbone": "MobileNetV3Small ImageNet, frozen",
        "tensorflow": tf.__version__,
        "python": sys.version,
        "platform": platform.platform(),
        "gpu_devices": [d.name for d in gpus],
        "manifest": str(args.manifest.resolve()),
        "test_manifest": str(args.test_manifest.resolve()) if args.test_manifest else None,
        "counts": {split: dict(Counter(str(r["label"]) for r in rows)) for split, rows in subsets.items()},
        "patient_independence_verified": False,
    }
    config_path = args.output / "config.json"
    if args.resume:
        previous = json.loads(config_path.read_text(encoding="utf-8"))
        for key in ("seed", "batch_size", "manifest", "test_manifest"):
            if previous.get(key) != config.get(key):
                raise SystemExit(f"No se puede reanudar: cambió {key}.")
    else:
        save_json(config_path, config)

    model = build_model()
    with (args.output / "architecture.txt").open("w", encoding="utf-8") as f:
        model.summary(print_fn=lambda line: f.write(line + "\n"))
    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            filepath=str(args.output / "checkpoints" / "epoch-{epoch:03d}.keras"),
            monitor="val_auc",
            mode="max",
            save_best_only=False,
        ),
        tf.keras.callbacks.BackupAndRestore(backup_dir=str(args.output / "backup")),
        tf.keras.callbacks.CSVLogger(str(args.output / "history.csv"), append=args.resume),
        tf.keras.callbacks.EarlyStopping(monitor="val_auc", mode="max", patience=4, restore_best_weights=True),
    ]
    history = model.fit(
        dataset(subsets["train"], training=True, batch_size=args.batch_size),
        validation_data=dataset(subsets["validation"], batch_size=args.batch_size),
        epochs=args.epochs,
        class_weight=class_weights,
        callbacks=callbacks,
        verbose=1,
    )
    model.save(args.output / "model.keras")

    # The test set is evaluated once, after checkpoint selection on validation.
    scores = model.predict(dataset(subsets["test"], batch_size=args.batch_size), verbose=0).ravel()
    labels = [int(r["label"]) for r in subsets["test"]]
    save_json(args.output / "metrics_test.json", metrics(labels, scores))
    with (args.output / "predictions_test.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_id", "path", "label", "score"])
        writer.writerows((r["image_id"], r["path"], r["label"], float(score)) for r, score in zip(subsets["test"], scores))
    print(f"Entrenamiento terminado: {args.output}")
    print(f"Épocas ejecutadas: {len(history.history.get('loss', []))}; GPU(s): {len(gpus)}")


if __name__ == "__main__":
    main()
