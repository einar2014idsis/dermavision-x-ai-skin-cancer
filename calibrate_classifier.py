"""Genera validación, ajusta Platt y fija umbral sin usar test para decidir."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, roc_auc_score, f1_score

from calibration import logit, sigmoid

ROOT = Path(__file__).resolve().parent
RUN = ROOT / "runs" / "functional-02"


def load_rows(split):
    with (RUN / "manifest.csv").open(newline="", encoding="utf-8-sig") as handle:
        return [row for row in csv.DictReader(handle) if row["split"] == split]


def predict(model, rows, batch_size=32):
    scores = []
    for start in range(0, len(rows), batch_size):
        images = []
        for row in rows[start:start + batch_size]:
            with Image.open(row["path"]) as image:
                images.append(np.asarray(image.convert("RGB").resize((224, 224)), dtype="float32"))
        scores.extend(model(np.stack(images), training=False).numpy().reshape(-1).tolist())
    return np.asarray(scores, dtype=float)


def measures(labels, scores, threshold):
    pred = scores >= threshold
    tn, fp, fn, tp = confusion_matrix(labels, pred, labels=[0, 1]).ravel()
    return {"threshold": float(threshold), "sensitivity": tp / (tp + fn),
            "specificity": tn / (tn + fp), "accuracy": (tp + tn) / len(labels),
            "f1": float(f1_score(labels, pred, zero_division=0)),
            "false_negatives": int(fn), "false_positives": int(fp),
            "auc": float(roc_auc_score(labels, scores))}


def selective_measures(labels, scores, threshold, width):
    decided = (scores < threshold - width) | (scores > threshold + width)
    metric = measures(labels[decided], scores[decided], threshold)
    metric.update({"uncertain_low": float(threshold - width),
                   "uncertain_high": float(threshold + width),
                   "coverage": float(decided.mean()),
                   "abstained": int((~decided).sum())})
    return metric


def main():
    import tensorflow as tf
    model = tf.keras.models.load_model(RUN / "model.keras", compile=False, safe_mode=True)
    validation = load_rows("validation")
    raw_validation = predict(model, validation)
    y_validation = np.asarray([int(row["label"]) for row in validation])
    platt = LogisticRegression(C=1e6, solver="lbfgs").fit(logit(raw_validation).reshape(-1, 1), y_validation)
    calibrated_validation = sigmoid(platt.coef_[0, 0] * logit(raw_validation) + platt.intercept_[0])
    # El sistema puede abstenerse cerca del umbral. Se exige conservar al menos
    # 85 % de cobertura y 94 % de sensibilidad entre los casos decididos; luego
    # se maximiza especificidad. Todas estas decisiones usan solo validación.
    candidates = []
    for threshold in np.linspace(.15, .65, 501):
        for width in np.linspace(.03, .10, 15):
            if threshold - width <= 0 or threshold + width >= 1:
                continue
            metric = selective_measures(y_validation, calibrated_validation, threshold, width)
            if metric["coverage"] >= .85 and metric["sensitivity"] >= .94:
                candidates.append(metric)
    chosen = max(candidates, key=lambda item: (item["specificity"], item["accuracy"],
                                                item["coverage"], item["threshold"]))
    low, high = chosen["uncertain_low"], chosen["uncertain_high"]

    test_rows = load_rows("test")
    with (RUN / "test_predictions.csv").open(encoding="utf-8-sig") as handle:
        raw_test = np.asarray([float(row["score"]) for row in csv.DictReader(handle)])
    y_test = np.asarray([int(row["label"]) for row in test_rows])
    calibrated_test = sigmoid(platt.coef_[0, 0] * logit(raw_test) + platt.intercept_[0])
    test_selective = selective_measures(y_test, calibrated_test, chosen["threshold"],
                                        chosen["threshold"] - low)
    payload = {"schema": "dermavision-calibration-v1", "method": "Platt scaling",
               "fit_split": "validation", "selection_rule": "coverage >= 0.85, decided sensitivity >= 0.94; maximize specificity",
               "slope": float(platt.coef_[0, 0]), "intercept": float(platt.intercept_[0]),
               "threshold": chosen["threshold"], "uncertain_low": low, "uncertain_high": high,
               "validation": chosen,
               "test_report_only": {"all_cases": measures(y_test, calibrated_test, chosen["threshold"]),
                                    "after_abstention": test_selective},
               "limitations": ["Sin independencia por paciente verificada.",
                               "No constituye calibración clínica externa.",
                               "La zona no concluyente se definió con validación interna."]}
    (RUN / "calibration.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
