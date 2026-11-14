"""Ajusta los últimos bloques convolucionales y compara en validación."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.metrics import roc_auc_score

from dermavision import dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--blocks", type=int, choices=(2, 4), default=2)
    parser.add_argument("--external-weight", type=float, default=1.0)
    parser.add_argument("--original-validation-monitor", action="store_true")
    args = parser.parse_args()
    tf.keras.utils.set_random_seed(2026)
    gpus = tf.config.list_physical_devices("GPU")
    if not gpus:
        raise RuntimeError("TensorFlow no detectó la GPU.")
    for gpu in gpus:
        tf.config.experimental.set_memory_growth(gpu, True)
    with args.manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    train = [r for r in rows if r["included"] == "true" and r["split"] == "train"]
    val = [r for r in rows if r["included"] == "true" and r["split"] == "validation"]
    train_ds = dataset(train, training=True)
    val_ds = dataset(val)
    labels = np.array([int(r["label"]) for r in val])
    sources = np.array([r["source"] for r in val])
    model = tf.keras.models.load_model(args.model, compile=False, safe_mode=True)
    args.output.mkdir(parents=True)

    def evaluate(current):
        scores = current.predict(val_ds, verbose=0).ravel()
        results = {
            "all": float(roc_auc_score(labels, scores)),
            **{
                source: float(roc_auc_score(labels[sources == source], scores[sources == source]))
                for source in sorted(set(sources))
            },
        }
        original = sources != "PAD-UFES-20"
        results["original_validation"] = float(roc_auc_score(labels[original], scores[original]))
        return results, scores

    def report(filename, values):
        (args.output / filename).write_text(json.dumps(values, indent=2), encoding="utf-8")

    baseline, baseline_scores = evaluate(model)
    report("baseline_validation.json", baseline)
    def save_predictions(name, scores):
        with (args.output / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(("image_id", "path", "source", "diagnosis", "label", "score"))
            writer.writerows((r["image_id"], r["path"], r["source"], r.get("diagnosis_original", ""),
                              r["label"], float(score)) for r, score in zip(val, scores))

    save_predictions("baseline_predictions.csv", baseline_scores)
    base = next(layer for layer in model.layers if isinstance(layer, tf.keras.Model))
    base.trainable = True
    prefixes = ("expanded_conv_9", "expanded_conv_10", "conv_1")
    if args.blocks == 4:
        prefixes += ("expanded_conv_7", "expanded_conv_8")
    for layer in base.layers:
        layer.trainable = layer.name.startswith(prefixes) and not isinstance(
            layer, tf.keras.layers.BatchNormalization
        ) and bool(layer.weights)
    tuned = [layer.name for layer in base.layers if layer.trainable_weights]
    if not tuned:
        raise RuntimeError("No se encontraron parámetros del extractor para ajustar.")
    report("fine_tune_config.json", {"layers": tuned, "learning_rate": 1e-5, "initial_model": str(args.model)})
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-5, clipnorm=1.0),
        loss="binary_crossentropy",
        metrics=[tf.keras.metrics.AUC(name="auc")],
    )
    checkpoint = args.output / "candidate.keras"
    selection_ds = dataset([r for r in val if r["source"] != "PAD-UFES-20"]) if args.original_validation_monitor else val_ds
    if args.external_weight != 1.0:
        if not 0 < args.external_weight <= 1:
            parser.error("--external-weight debe estar entre 0 y 1.")
        for row in train:
            row["sample_weight"] = args.external_weight if row["source"] == "ISIC-2024" else 1.0
        total = sum(r["sample_weight"] for r in train)
        class_weights = {label: total / (2 * sum(r["sample_weight"] for r in train
                                                 if int(r["label"]) == label)) for label in (0, 1)}
        for row in train:
            row["sample_weight"] *= class_weights[int(row["label"])]
        train_ds = dataset(train, training=True, sample_weights=True)
        class_weights = None
    else:
        class_weights = {label: len(train)/(2 * sum(int(r["label"]) == label for r in train)) for label in (0, 1)}
    model.fit(
        train_ds, validation_data=selection_ds, class_weight=class_weights, epochs=args.epochs, verbose=2,
        callbacks=[
            tf.keras.callbacks.CSVLogger(args.output / "history.csv"),
            tf.keras.callbacks.ModelCheckpoint(checkpoint, monitor="val_auc", mode="max", save_best_only=True),
            tf.keras.callbacks.EarlyStopping(monitor="val_auc", mode="max", patience=3),
        ],
    )
    candidate_model = tf.keras.models.load_model(checkpoint, compile=False, safe_mode=True)
    candidate, scores = evaluate(candidate_model)
    save_predictions("candidate_predictions.csv", scores)
    comparison = {
        "baseline": baseline, "candidate": candidate,
        "target_auc": 0.93, "target_met": candidate["original_validation"] >= 0.93,
    }
    phone_test = [r for r in rows if r["included"] == "true"
                  and r["source"] == "PAD-UFES-20" and r["split"] == "test"]
    if phone_test:
        test_data = dataset(phone_test)
        test_labels = [int(r["label"]) for r in phone_test]
        baseline_model = tf.keras.models.load_model(args.model, compile=False, safe_mode=True)
        comparison["phone_patient_holdout"] = {
            "n": len(phone_test),
            "baseline_auc": float(roc_auc_score(test_labels, baseline_model.predict(test_data, verbose=0).ravel())),
            "candidate_auc": float(roc_auc_score(test_labels, candidate_model.predict(test_data, verbose=0).ravel())),
        }
    report("comparison.json", comparison)
    print("Comparación de AUC en validación:", baseline, candidate, flush=True)


if __name__ == "__main__":
    main()
