"""Compara dos modelos, fija sus umbrales en validación y exporta el elegido."""

import argparse
import csv
import json
import shutil
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.metrics import confusion_matrix, roc_auc_score, roc_curve

from dermavision import dataset
from entrenar_isic2019 import load_manifest


def measurements(labels, scores, threshold):
    tn, fp, fn, tp = confusion_matrix(labels, scores >= threshold, labels=[0, 1]).ravel()
    return {
        "threshold": threshold, "auc": float(roc_auc_score(labels, scores)),
        "sensitivity": float(tp / (tp + fn)), "specificity": float(tn / (tn + fp)),
        "accuracy": float((tp + tn) / len(labels)), "f1": float(2 * tp / (2 * tp + fp + fn)),
        "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "baseline", "candidate", "history", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    for gpu in tf.config.list_physical_devices("GPU"):
        tf.config.experimental.set_memory_growth(gpu, True)
    subsets = load_manifest(args.manifest, ("validation", "test"))
    val = subsets["validation"]
    labels = np.array([r["label"] for r in val])
    own = np.array([r["source"] == "OWN" for r in val])
    if set(labels[own]) != {0, 1}:
        raise ValueError("La validación propia debe contener ambas clases.")
    data = dataset(val, batch_size=32)
    val_report = {}
    for name, path in (("baseline", args.baseline), ("candidate", args.candidate)):
        model = tf.keras.models.load_model(path, compile=False, safe_mode=True)
        scores = model.predict(data, verbose=0).ravel()
        fpr, tpr, thresholds = roc_curve(labels, scores, drop_intermediate=False)
        eligible = np.flatnonzero(tpr >= 0.90)
        threshold = float(thresholds[eligible[np.argmin(fpr[eligible])]])
        val_report[name] = {
            "all": measurements(labels, scores, threshold),
            "own": measurements(labels[own], scores[own], threshold),
        }
    old, new = (val_report[key] for key in ("baseline", "candidate"))
    preferred = (
        new["all"]["auc"] > old["all"]["auc"]
        and new["own"]["auc"] >= old["own"]["auc"]
        and new["own"]["sensitivity"] >= old["own"]["sensitivity"]
        and new["own"]["specificity"] >= old["own"]["specificity"]
    )
    val_report["promote"] = preferred
    val_report["baseline_model"] = str(args.baseline.resolve())
    val_report["candidate_model"] = str(args.candidate.resolve())
    val_report["rule"] = (
        "Higher overall AUC, no drop in own AUC, sensitivity or specificity, "
        "thresholds chosen by maximizing specificity at >=90% overall sensitivity in validation."
    )
    args.output.mkdir(parents=True)
    write_json(args.output / "decision.json", val_report)
    print(json.dumps(val_report, indent=2), flush=True)
    if not preferred:
        return

    test = subsets["test"]
    if not test:
        raise ValueError("Se requiere una prueba para exportar las métricas.")
    threshold = new["all"]["threshold"]
    predictions = model.predict(dataset(test, batch_size=32), verbose=0).ravel()
    metrics = measurements(np.array([r["label"] for r in test]), predictions, threshold)
    metrics["evaluation"] = "historical_test_followup"
    config = dict(image_size=224, class_mapping={"benign": 0, "malignant": 1},
                  threshold=threshold, domain_reference="functional-02")
    calibration = dict(schema="dermavision-calibration-v1", fit_split="validation",
                       slope=1, intercept=0, threshold=threshold,
                       uncertain_low=threshold, uncertain_high=threshold)
    for name, value in (("config", config), ("calibration", calibration), ("metrics", metrics)):
        write_json(args.output / f"{name}.json", value)
    with (args.output / "test_predictions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("image_id", "path", "label", "score"))
        writer.writerows((r["image_id"], r["path"], r["label"], float(score))
                         for r, score in zip(test, predictions))
    with args.manifest.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8") as dest:
            writer = csv.DictWriter(dest, reader.fieldnames)
            writer.writeheader()
            for row in reader:
                row["path"] = str((args.manifest.parent / row["path"]).resolve())
                writer.writerow(row)
    shutil.copyfile(args.history, args.output / "history.csv")
    shutil.copyfile(args.candidate, args.output / "model.keras")


if __name__ == "__main__":
    main()
