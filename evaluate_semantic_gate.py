"""Selecciona umbral con validation y evalúa test una vez; guarda evidencia.

No reentrena CLIP ni utiliza test para ajustar prompts o umbrales.
"""
import csv
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image
from semantic_gate import SemanticEncoder, TAXONOMY_HASH, decide
from train_domain_gate import cifar_arrays


def evaluate():
    base = Path(__file__).parent
    output = base/'runs'/'domain-02'
    output.mkdir(exist_ok=True)
    rows = list(csv.DictReader((base/'runs/domain-01/manifest.csv').open(encoding='utf-8')))
    arrays, _ = cifar_arrays(base/'runs/gate-data/cifar-100-binary.tar.gz')
    encoder = SemanticEncoder(base/'runs/clip-vit-base-patch32')
    def read(row):
        if row['source'] == 'cifar100':
            return Image.fromarray(arrays[row['source_split']][0][int(row['index'])])
        with Image.open(row['path']) as im:
            return im.convert('RGB')
    def extract(split):
        selected = [r for r in rows if r['split'] == split]
        parts = []
        for start in range(0, len(selected), 16):
            parts.append(encoder.similarities([read(r) for r in selected[start:start+16]]))
            if start % 160 == 0:
                print(f'{split}: {start}/{len(selected)}', flush=True)
        values = np.concatenate(parts)
        np.savez(output/f'{split}_similarities.npz', values=values,
                 labels=np.array([int(r['label']) for r in selected]))
        return selected, values
    def report(selected, scores, threshold):
        labels = np.array([int(r['label']) for r in selected])
        margin = scores[:, 0]-scores[:, 1:].max(axis=1)
        states = np.array([decide(s, threshold, -.025).state for s in scores])
        return dict(images=len(labels), accepted_lesions=int(((margin >= threshold) & (labels == 1)).sum()),
                    total_lesions=int((labels == 1).sum()),
                    accepted_objects=int(((margin >= threshold) & (labels == 0)).sum()),
                    total_objects=int((labels == 0).sum()),
                    lesion_acceptance=float((margin[labels == 1] >= threshold).mean()),
                    object_blocking=float((margin[labels == 0] < threshold).mean()),
                    explicitly_rejected=int((states == 'rejected').sum()), uncertain=int((states == 'uncertain').sum()))
    start = time.monotonic()
    selected, values = extract('validation')
    threshold = None
    for candidate in np.arange(.001, .101, .001):
        result = report(selected, values, candidate)
        if result['object_blocking'] >= .98 and result['lesion_acceptance'] >= .85:
            threshold = float(candidate)
            break
    config = dict(schema='dermavision-semantic-v1', taxonomy_sha256=TAXONOMY_HASH,
                  validation_passed=threshold is not None, accept_margin=threshold or .1, reject_margin=-.025)
    results = dict(validation=report(selected, values, config['accept_margin']),
                   criteria=dict(object_blocking=.98, lesion_acceptance=.85),
                   limitations=['CIFAR-100 es un proxy de objetos de baja resolución.',
                                'No evaluado con piel sana, otras patologías ni cámaras reales.',
                                'Independencia por paciente no verificada. No valida diagnóstico.',
                                'CLIP es un modelo general de investigación, no un detector clínico.'])
    (output/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    selected, values = extract('test')
    results['test'] = report(selected, values, config['accept_margin'])
    results['seconds'] = time.monotonic()-start
    with (output/'test_predictions.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(['source', 'path', 'index', 'category', 'label', 'lesion', 'skin', 'other', 'state'])
        for row, scores in zip(selected, values):
            writer.writerow([row['source'], row['path'], row['index'], row['category'], row['label'],
                             *scores, decide(scores, config['accept_margin'], -.025).state])
    (output/'metrics.json').write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(results, indent=2, ensure_ascii=False), flush=True)

if __name__ == '__main__':
    evaluate()
    from finalize_semantic_evaluation import finalize
    finalize()
