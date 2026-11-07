"""Evalúa la combinación con umbrales ya fijados; nunca ajusta con test."""

import csv
import json
from pathlib import Path
import numpy as np
from PIL import Image
from semantic_gate import decide, combine_decisions, TAXONOMY_HASH
from domain_gate import DomainGate, gate_pixels, gate_scores


def finalize():
    import tensorflow as tf
    from train_domain_gate import cifar_arrays

    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    base = Path(__file__).parent / "runs"
    output = base / "domain-02"
    config = json.loads((output / "config.json").read_text(encoding="utf-8"))
    assert config["taxonomy_sha256"] == TAXONOMY_HASH and config["validation_passed"]
    model_path = base / "functional-02" / "model.keras"
    reference = DomainGate(
        base / "domain-01" / "gate.json",
        model_path,
        tf.keras.models.load_model(model_path, compile=False),
    )
    rows = list(
        csv.DictReader((base / "domain-01" / "manifest.csv").open(encoding="utf-8"))
    )
    cifar, _ = cifar_arrays(base / "gate-data" / "cifar-100-binary.tar.gz")

    def read(row):
        if row["source"] == "cifar100":
            return Image.fromarray(cifar[row["source_split"]][0][int(row["index"])])
        with Image.open(row["path"]) as im:
            return im.convert("RGB")

    def report(labels, decisions):
        states = np.array([d.state for d in decisions])
        return dict(
            images=len(labels),
            accepted_lesions=int(((states == "accepted") & (labels == 1)).sum()),
            total_lesions=int((labels == 1).sum()),
            accepted_objects=int(((states == "accepted") & (labels == 0)).sum()),
            total_objects=int((labels == 0).sum()),
            rejected_lesions=int(((states == "rejected") & (labels == 1)).sum()),
            uncertain_lesions=int(((states == "uncertain") & (labels == 1)).sum()),
            explicitly_rejected_objects=int(
                ((states == "rejected") & (labels == 0)).sum()
            ),
            uncertain_objects=int(((states == "uncertain") & (labels == 0)).sum()),
            lesion_acceptance=float((states[labels == 1] == "accepted").mean()),
            object_blocking=float((states[labels == 0] != "accepted").mean()),
        )

    results = dict(
        accept_margin=config["accept_margin"],
        reject_margin=config["reject_margin"],
        mode="semantic AND reference domain gate; disagreement abstains",
        threshold_selection="validation only, grid .001 to .100; no test tuning",
        criteria=dict(object_blocking=0.98, lesion_acceptance=0.85),
        limitations=[
            "CIFAR-100 es un proxy de objetos de 32x32, no de todos los objetos reales.",
            "No evaluado con piel sana, otros trastornos ni cámaras reales.",
            "Sin independencia por paciente verificada ni validación clínica.",
            "Los casos no concluyentes reducen la cobertura de lesiones.",
            "CLIP es un modelo general de investigación.",
        ],
    )
    for split in ("validation", "test"):
        selected = [r for r in rows if r["split"] == split]
        cache = np.load(output / f"{split}_similarities.npz")
        values, labels = cache["values"], cache["labels"]
        np.testing.assert_array_equal(labels, [int(r["label"]) for r in selected])
        decisions = [
            decide(s, config["accept_margin"], config["reject_margin"]) for s in values
        ]
        results["semantic_" + split] = report(labels, decisions)
        # Evaluate the second verifier only for semantic positives, just like UI.
        indices = [i for i, d in enumerate(decisions) if d.state == "accepted"]
        reference_values = np.full(len(selected), np.nan)
        for start in range(0, len(indices), 32):
            batch = indices[start : start + 32]
            pixels = np.stack([gate_pixels(read(selected[i])) for i in batch])
            scores = gate_scores(
                reference.features(pixels, training=False).numpy(), reference.parameters
            )
            for i, score in zip(batch, scores):
                reference_values[i] = score
                decisions[i] = combine_decisions(
                    decisions[i], score >= reference.threshold
                )
        results[split] = report(labels, decisions)
        with (output / f"{split}_predictions.csv").open(
            "w", newline="", encoding="utf-8"
        ) as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "source",
                    "path",
                    "index",
                    "category",
                    "label",
                    "lesion_similarity",
                    "skin_similarity",
                    "object_similarity",
                    "reference_score",
                    "state",
                ]
            )
            for row, s, ref, decision in zip(
                selected, values, reference_values, decisions
            ):
                writer.writerow(
                    [
                        row["source"],
                        row["path"],
                        row["index"],
                        row["category"],
                        row["label"],
                        *s,
                        float(ref) if np.isfinite(ref) else "",
                        decision.state,
                    ]
                )
        print(split, results[split], flush=True)
    results["combined_validation_passed"] = (
        results["validation"]["object_blocking"] >= 0.98
        and results["validation"]["lesion_acceptance"] >= 0.85
    )
    config["combined_validation_passed"] = results["combined_validation_passed"]
    (output / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if not results["combined_validation_passed"]:
        raise RuntimeError("La combinación no cumple los criterios de validación.")


if __name__ == "__main__":
    finalize()
