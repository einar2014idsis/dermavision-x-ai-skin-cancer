"""Clasificación experimental de lesiones. No estima diagnóstico ni estadio."""

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageOps

CLASSES = {"benign": 0, "malignant": 1}
EXTENSIONS = {".jpg", ".jpeg", ".png"}


def save_json(path, value):
    Path(path).write_text(
        json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def audit(root):
    root = Path(root).resolve()
    rows, errors = [], []
    for split in ("train", "test"):
        for name, label in CLASSES.items():
            folder = root / split / name
            if not folder.is_dir():
                raise ValueError(f"Falta carpeta: {folder}")
            for path in sorted(folder.rglob("*")):
                if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                    continue
                try:
                    with Image.open(path) as im:
                        rgb = ImageOps.exif_transpose(im).convert("RGB")
                        rgb.load()
                        digest = hashlib.sha256(
                            str(rgb.size).encode() + rgb.tobytes()
                        ).hexdigest()
                        rows.append(
                            dict(
                                path=str(path),
                                split=split,
                                label=label,
                                sha256=digest,
                                width=rgb.width,
                                height=rgb.height,
                            )
                        )
                except Exception as exc:
                    errors.append({"path": str(path), "error": str(exc)})
    groups = defaultdict(list)
    for row in rows:
        groups[row["sha256"]].append(row)
    duplicates = [g for g in groups.values() if len(g) > 1]
    report = dict(
        counts=dict(Counter(f"{r['split']}/{r['label']}" for r in rows)),
        valid_images=len(rows),
        invalid=errors,
        duplicate_groups=duplicates,
        conflicting_labels=[g for g in duplicates if len({r["label"] for r in g}) > 1],
        cross_split_duplicates=[
            g for g in duplicates if len({r["split"] for r in g}) > 1
        ],
        limitations=[
            "No hay identificación de paciente ni validación de procedencia clínica.",
            "Hash detecta píxeles idénticos; no detecta todos los duplicados aproximados.",
        ],
    )
    return rows, report


def prepare(root, output, acknowledge=False):
    rows, report = audit(root)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    save_json(output / "audit.json", report)
    if (
        report["invalid"]
        or report["conflicting_labels"]
        or report["cross_split_duplicates"]
    ):
        raise ValueError(
            "Auditoría bloqueada: revisar audit.json; no se modificaron originales."
        )
    if not acknowledge:
        raise ValueError(
            "Sin IDs de pacientes: use --allow-image-split solo para experimentos exploratorios."
        )
    unique = {}
    for row in rows:
        unique.setdefault(row["sha256"], row.copy())
    rows = list(unique.values())
    rng = random.Random(2026)
    for label in (0, 1):
        candidates = [r for r in rows if r["split"] == "train" and r["label"] == label]
        if len(candidates) < 4 or not any(
            r["split"] == "test" and r["label"] == label for r in rows
        ):
            raise ValueError(
                "Se necesitan ambas clases en train/test y >=4 imágenes por clase en train."
            )
        rng.shuffle(candidates)
        for row in candidates[: max(1, round(len(candidates) * 0.2))]:
            row["split"] = "validation"
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return dict(Counter(f"{r['split']}/{r['label']}" for r in rows))


def build_model(weights="imagenet"):
    import tensorflow as tf

    k = tf.keras
    inputs = k.Input((224, 224, 3), name="imagen_rgb_0_255")
    x = k.layers.RandomFlip("horizontal_and_vertical")(inputs)
    x = k.layers.RandomRotation(0.08)(x)
    base = k.applications.MobileNetV3Small(
        include_top=False,
        weights=weights,
        include_preprocessing=True,
        input_shape=(224, 224, 3),
    )
    base.trainable = False
    x = base(x, training=False)
    x = k.layers.GlobalAveragePooling2D()(x)
    x = k.layers.Dense(32, activation="relu", name="capa_oculta_32")(x)
    x = k.layers.Dropout(0.3)(x)
    x = k.layers.Dense(16, activation="relu", name="capa_oculta_16")(x)
    outputs = k.layers.Dense(1, activation="sigmoid", name="puntuacion_malignidad")(x)
    model = k.Model(inputs, outputs, name="DermaVision_X")
    model.compile(
        optimizer=k.optimizers.Adam(1e-3),
        loss="binary_crossentropy",
        metrics=[
            k.metrics.BinaryAccuracy(name="accuracy"),
            k.metrics.AUC(name="auc"),
            k.metrics.Recall(name="sensitivity"),
        ],
    )
    return model


def read_rgb(path):
    import numpy as np

    with Image.open(path) as im:
        return np.asarray(
            ImageOps.exif_transpose(im)
            .convert("RGB")
            .resize((224, 224), Image.Resampling.BILINEAR),
            dtype="float32",
        )


def dataset(rows, training=False):
    import tensorflow as tf

    rows = list(rows)
    if training:
        # Mezclar rutas antes de decodificar: evita lotes ordenados por clase
        # sin almacenar todas las imágenes RGB en memoria.
        random.Random(2026).shuffle(rows)

    def generate():
        for row in rows:
            yield read_rgb(row["path"]), [float(row["label"])]

    ds = tf.data.Dataset.from_generator(
        generate,
        output_signature=(
            tf.TensorSpec((224, 224, 3), tf.float32),
            tf.TensorSpec((1,), tf.float32),
        ),
    )
    ds = ds.apply(tf.data.experimental.assert_cardinality(len(rows)))
    if training:
        ds = ds.shuffle(min(len(rows), 256), seed=2026)
    return ds.batch(16).prefetch(1)


def metrics(labels, scores):
    from sklearn.metrics import (
        confusion_matrix,
        roc_auc_score,
        f1_score,
        accuracy_score,
    )

    predictions = scores >= 0.5
    tn, fp, fn, tp = confusion_matrix(labels, predictions, labels=[0, 1]).ravel()
    return dict(
        threshold=0.5,
        sensitivity=float(tp / (tp + fn)),
        specificity=float(tn / (tn + fp)),
        f1=float(f1_score(labels, predictions, zero_division=0)),
        auc=float(roc_auc_score(labels, scores)),
        accuracy=float(accuracy_score(labels, predictions)),
        confusion_matrix=[[int(tn), int(fp)], [int(fn), int(tp)]],
    )


def train(args):
    import numpy as np
    import tensorflow as tf

    tf.keras.utils.set_random_seed(2026)
    output = Path(args.output)
    if output.exists():
        raise ValueError(
            "Use un directorio nuevo para conservar los experimentos anteriores."
        )
    prepare(args.data, output, args.allow_image_split)
    with (output / "manifest.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    subsets = {
        s: [r for r in rows if r["split"] == s] for s in ("train", "validation", "test")
    }
    model = build_model()
    with (output / "architecture.txt").open("w", encoding="utf-8") as f:
        model.summary(print_fn=lambda line: f.write(line + "\n"))
    counts = Counter(int(r["label"]) for r in subsets["train"])
    weights = {
        label: len(subsets["train"]) / (2 * count) for label, count in counts.items()
    }
    save_json(
        output / "config.json",
        dict(
            seed=2026,
            epochs=args.epochs,
            image_size=224,
            class_mapping=CLASSES,
            threshold=0.5,
            class_weights=weights,
            patient_independence_verified=False,
            source_clinically_verified=False,
        ),
    )
    history = model.fit(
        dataset(subsets["train"], True),
        validation_data=dataset(subsets["validation"]),
        epochs=args.epochs,
        class_weight=weights,
        callbacks=[
            tf.keras.callbacks.EarlyStopping(
                monitor="val_auc", mode="max", patience=3, restore_best_weights=True
            ),
            tf.keras.callbacks.CSVLogger(str(output / "history.csv")),
        ],
    )
    model.save(output / "model.keras")
    # Test solo después de seleccionar el modelo con validation. Umbral fijo, no ajustado con test.
    scores = model.predict(dataset(subsets["test"]), verbose=0).ravel()
    labels = np.array([int(r["label"]) for r in subsets["test"]])
    save_json(output / "metrics.json", metrics(labels, scores))
    with (output / "test_predictions.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "label", "score"])
        writer.writerows(
            (r["path"], r["label"], float(s)) for r, s in zip(subsets["test"], scores)
        )
    print("Experimento exploratorio completado:", output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("audit", "train"):
        p = sub.add_parser(name)
        p.add_argument("--data", required=True)
        p.add_argument("--output", required=True)
        if name == "train":
            p.add_argument("--epochs", type=int, default=10)
            p.add_argument("--allow-image-split", action="store_true")
    p = sub.add_parser("predict")
    p.add_argument("--model", required=True)
    p.add_argument("--image", required=True)
    args = parser.parse_args()
    if args.command == "audit":
        _, report = audit(args.data)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        save_json(args.output, report)
        print(json.dumps({k: report[k] for k in ("counts", "valid_images")}, indent=2))
        print("Grupos duplicados:", len(report["duplicate_groups"]))
        print(
            "Errores:",
            len(report["invalid"]),
            "Cruces train/test:",
            len(report["cross_split_duplicates"]),
        )
    elif args.command == "train":
        if args.epochs < 1:
            parser.error("--epochs debe ser positivo")
        train(args)
    else:
        import tensorflow as tf

        model = tf.keras.models.load_model(args.model)
        score = float(model.predict(read_rgb(args.image)[None], verbose=0)[0, 0])
        print(
            json.dumps(
                dict(
                    score=score,
                    predicted_class="malignant" if score >= 0.5 else "benign",
                    notice="Clasificación experimental sin calibración ni detección fuera de dominio. No indica estadio.",
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
