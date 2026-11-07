"""Read-only inventory and reproducible paired benchmark; never edits the live store."""
import argparse
import csv
import hashlib
import json
import platform
import sqlite3
import time
from datetime import datetime
from collections import Counter
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_csv(path, rows, fields):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def inventory(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect((root / 'history.sqlite3').as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        records = [dict(row) for row in db.execute(
            'SELECT r.*, l.person_id FROM records r JOIN lesions l ON r.lesion_id=l.id'
        )]
        comparisons = [dict(row) for row in db.execute('SELECT * FROM comparisons')]
    finally:
        db.close()
    # All existing data have already been accessible during development. Never
    # retroactively label these observations as an untouched final test set.
    visits = []
    for row in records:
        visits.append(dict(
            record_id=row['id'], person_id=row['person_id'], lesion_id=row['lesion_id'],
            captured_at=row['captured_at'], split='development',
            image=str(root / row['image']), mask=str(root / row['mask']),
            image_sha256=row['sha256'], mask_sha256=row['mask_sha256'],
            source='', source_original_id='', device='', consent_status='unverified', contour_reviewer='',
        ))
    fields = ['record_id', 'person_id', 'lesion_id', 'captured_at', 'split', 'image', 'mask',
              'image_sha256', 'mask_sha256', 'source', 'source_original_id', 'device', 'consent_status', 'contour_reviewer']
    write_csv(output / 'visits.csv', visits, fields)
    lookup = {row['record_id']: row for row in visits}
    pairs, counts, excluded, reasons = [], Counter(), Counter(), Counter()
    for row in comparisons:
        result = json.loads(row['result'])
        status = 'accepted' if result.get('comparable') else 'visual' if result.get('mode') == 'visual' else 'rejected'
        counts[status] += 1
        if status == 'rejected':
            reasons.update(rejection_codes(result))
        if (row['previous_id'] in lookup and row['current_id'] in lookup
                and lookup[row['previous_id']]['lesion_id'] == lookup[row['current_id']]['lesion_id']
                and row['previous_id'] != row['current_id']):
            try:
                chronological = (datetime.fromisoformat(lookup[row['previous_id']]['captured_at'])
                                 < datetime.fromisoformat(lookup[row['current_id']]['captured_at']))
            except (ValueError, TypeError):
                chronological = False
            if not chronological:
                excluded['invalid_or_nonchronological_dates'] += 1
                continue
            pairs.append(dict(pair_id=row['id'], previous_id=row['previous_id'], current_id=row['current_id'],
                              reference_comparable='unknown', capture_group='unknown', reviewer='', reference_reason=''))
        else:
            excluded['missing_or_incompatible_visits'] += 1
    write_csv(output / 'pairs.csv', pairs,
              ['pair_id', 'previous_id', 'current_id', 'reference_comparable', 'capture_group', 'reviewer', 'reference_reason'])
    summary = dict(records=len(visits), persons=len({r['person_id'] for r in visits}),
                   lesions=len({r['lesion_id'] for r in visits}), saved_comparison_attempts=len(comparisons),
                   saved_status_counts=dict(counts), independent_reference_labels=0,
                   saved_rejection_reasons=dict(sorted(reasons.items())),
                   eligible_longitudinal_attempts=len(pairs),
                   excluded_attempts=dict(excluded),
                   note='Historical algorithm decisions are not correctness labels. Includes attempts, not necessarily unique pairs. All existing data are development; provenance and consent require review.')
    (output / 'inventory.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    return summary


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def validate(visits):
    ids, persons, hashes, lesions, originals = set(), {}, {}, {}, {}
    for row in visits:
        if not row['person_id'] or row['split'] not in ('development', 'validation', 'test'):
            raise ValueError('Person ID and explicit development/validation/test split required.')
        if row['record_id'] in ids:
            raise ValueError('Duplicate record ID.')
        if not row['lesion_id']:
            raise ValueError('Lesion ID required.')
        if lesions.setdefault(row['lesion_id'], row['person_id']) != row['person_id']:
            raise ValueError('Lesion ID is associated with multiple persons.')
        try:
            datetime.fromisoformat(row['captured_at'])
        except (ValueError, TypeError):
            raise ValueError('Valid ISO capture date required: ' + row['record_id'])
        ids.add(row['record_id'])
        previous = persons.setdefault(row['person_id'], row['split'])
        if previous != row['split']:
            raise ValueError('Data leakage: person occurs in multiple splits.')
        # Augmentations are different bytes: exact file hashes alone do not
        # protect against putting derivatives of one photograph in train/test.
        original = row.get('source_original_id', '').strip()
        if original and originals.setdefault(original, row['split']) != row['split']:
            raise ValueError('Data leakage: derivatives of one original occur in multiple splits.')
        for field in ('image', 'mask'):
            actual = digest(row[field])
            if actual != row[field + '_sha256']:
                raise ValueError('File hash mismatch: ' + row['record_id'] + '/' + field)
            if field == 'image':
                previous_split = hashes.setdefault(actual, row['split'])
                if previous_split != row['split']:
                    raise ValueError('Data leakage: identical image occurs in multiple splits.')
    return {row['record_id']: row for row in visits}


def rejection_codes(result):
    """Stable categories from recorded evidence, without treating rejection as truth."""
    if result.get('comparable'):
        return []
    codes = set()
    for assessment in result.get('capture_quality', []):
        for field, code in [('resolution_ok', 'quality_resolution'),
                            ('lighting_ok', 'quality_lighting'), ('focus_ok', 'quality_focus')]:
            if assessment.get(field) is False:
                codes.add(code)
    registration = result.get('registration', {})
    if registration and not registration.get('accepted', False):
        codes.add('registration')
    if registration.get('framing_accepted') is False:
        codes.add('framing')
    if result.get('color_normalization', {}).get('accepted') is False:
        codes.add('color')
    warnings = ' '.join(result.get('warnings', [])).lower()
    if 'contornos requieren revisión' in warnings:
        codes.add('contour_review')
    if 'contorno es insuficiente' in warnings:
        codes.add('contour_geometry')
    if 'calidad o contenido' in warnings:
        codes.add('content_gate')
    if 'correspondencia' in warnings:
        codes.add('registration')
    return sorted(codes or {'other_rejection'})


def summarize_rows(rows):
    """Descriptive coverage for everyone; correctness only for labelled pairs."""
    total = len(rows)
    accepted = [row for row in rows if row['status'] == 'accepted']
    known_no = [row for row in rows if row['reference_comparable'] == 'no']
    known_yes = [row for row in rows if row['reference_comparable'] == 'yes']
    accepted_labelled = [row for row in accepted if row['reference_comparable'] != 'unknown']
    false_accepts = sum(row['status'] == 'accepted' for row in known_no)
    false_rejects = sum(row['status'] == 'rejected' for row in known_yes)
    reasons = Counter(code for row in rows for code in row.get('reason_codes', '').split('|') if code)
    return dict(total=total, statuses=dict(Counter(row['status'] for row in rows)),
                coverage=len(accepted) / total if total else None,
                rejection_reasons=dict(sorted(reasons.items())),
                incorrect_acceptances=false_accepts if known_no else None,
                false_acceptance_rate=false_accepts / len(known_no) if known_no else None,
                noncomparable_reference_count=len(known_no),
                incorrect_rejections=false_rejects if known_yes else None,
                false_rejection_rate=false_rejects / len(known_yes) if known_yes else None,
                comparable_reference_count=len(known_yes),
                labelled=len(known_no) + len(known_yes),
                accepted_labelled=len(accepted_labelled),
                accepted_unknown=sum(row['reference_comparable'] == 'unknown' for row in accepted),
                # This is one operating point, NOT a risk-coverage curve. The
                # present boolean gate has no learned/calibrated acceptance score.
                selective_risk_labelled=(false_accepts / len(accepted_labelled)
                                         if accepted_labelled else None))


def evaluate_pair(images, pair, person_id, split):
    from longitudinal_analysis import compare_images, compare_visual_images
    rows, details = [], []
    for method, function in [('basic', compare_visual_images), ('complete', compare_images)]:
        started = time.perf_counter()
        try:
            result, _, _ = function(images[0], images[2], images[1], images[3])
            accepted = method == 'basic' or bool(result.get('comparable'))
            status = 'accepted' if accepted else 'rejected'
            reason = ' | '.join(result.get('warnings', [])) if not accepted else ''
            codes = [] if accepted else rejection_codes(result)
            # Compare descriptor endpoints, never the differently defined indices.
            metrics = result.get('visual_differences', {}) if method == 'basic' else result.get('changes', {}) if accepted else {}
            values = {k: metrics.get(k) for k in ('shape', 'asymmetry', 'border', 'color', 'texture')}
            details.append(dict(pair_id=pair['pair_id'], method=method, result=result))
        except Exception as exc:
            status, reason, codes, values = 'error', type(exc).__name__ + ': ' + str(exc), ['execution_error'], {}
        rows.append(dict(pair_id=pair['pair_id'], person_id=person_id, split=split,
                         method=method, reference_comparable=pair['reference_comparable'],
                         capture_group=pair['capture_group'], status=status, reason=reason,
                         reason_codes='|'.join(codes), seconds=time.perf_counter() - started, **values))
    return rows, details


RESULT_FIELDS = ['pair_id', 'person_id', 'split', 'method', 'reference_comparable', 'capture_group',
                 'status', 'reason', 'reason_codes', 'seconds', 'shape', 'asymmetry', 'border', 'color', 'texture']


def save_results(output, rows, details, reference_scope):
    output = Path(output)
    write_csv(output / 'results.csv', rows, RESULT_FIELDS)
    summary = {method: summarize_rows([row for row in rows if row['method'] == method])
               for method in ('basic', 'complete')}
    summary['reference_scope'] = reference_scope
    summary['by_capture_group'] = {
        group: {method: summarize_rows([row for row in rows if row['method'] == method and row['capture_group'] == group])
                for method in ('basic', 'complete')}
        for group in sorted({row['capture_group'] for row in rows})}
    summary['limitations'] = ['No clinical or cancer-detection validation.',
        'Unknown references do not support correctness claims; accepted unknown pairs are excluded from selective risk.',
        'The basic descriptor baseline emits a result unconditionally; accepted means output produced, not clinical validity.',
        'Rejection categories can overlap. Errors are separate from rejections.',
        'Selective risk is one labelled operating point, not a calibrated risk-coverage curve or risk guarantee.',
        'No confidence intervals or independent landmark alignment error yet.',
        'Repeated pairs per person or original are dependent; counts are descriptive.',
        'Alignment-only ablation remains pending. Complete uses heuristic quality, geometric and color controls.']
    if reference_scope == 'synthetic_expectations':
        summary['limitations'].append('Synthetic expectations derive from known generated originals and fixed perturbations, not expert labels or clinical longitudinal change.')
    else:
        summary['limitations'].append('Reviewer identifiers are declarations; independence and label quality require external verification.')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (output / 'details.json').write_text(json.dumps(details, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return summary


def benchmark(visits_path, pairs_path, output, split):
    import numpy as np
    import cv2
    import PIL
    from PIL import Image
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lookup = validate(read_csv(visits_path))
    rows, details, seen = [], [], set()
    for pair in read_csv(pairs_path):
        a, b = lookup[pair['previous_id']], lookup[pair['current_id']]
        if a['person_id'] != b['person_id'] or a['lesion_id'] != b['lesion_id']:
            raise ValueError('A longitudinal pair must belong to the same person and lesion.')
        try:
            chronological = datetime.fromisoformat(a['captured_at']) < datetime.fromisoformat(b['captured_at'])
        except TypeError:
            raise ValueError('Pair dates must use compatible time zones.')
        if not chronological:
            raise ValueError('Pair must contain two distinct visits in chronological order.')
        if a['split'] != split:
            continue
        key = (a['record_id'], b['record_id'])
        if key in seen:
            continue
        seen.add(key)
        if pair['reference_comparable'] not in ('yes', 'no', 'unknown'):
            raise ValueError('Reference label must be yes, no or unknown.')
        if pair['reference_comparable'] != 'unknown' and not pair.get('reviewer', '').strip():
            raise ValueError('Known reference label requires an independent reviewer identifier.')
        images = []
        started = time.perf_counter()
        try:
            for visit in (a, b):
                for field, mode in [('image', 'RGB'), ('mask', 'L')]:
                    with Image.open(visit[field]) as image:
                        images.append(image.convert(mode))
        except Exception as exc:
            for method in ('basic', 'complete'):
                rows.append(dict(pair_id=pair['pair_id'], person_id=a['person_id'], split=split,
                                 method=method, reference_comparable=pair['reference_comparable'],
                                 capture_group=pair['capture_group'], status='error',
                                 reason=type(exc).__name__ + ': ' + str(exc), reason_codes='execution_error',
                                 seconds=time.perf_counter() - started))
            continue
        pair_rows, pair_details = evaluate_pair(images, pair, a['person_id'], split)
        rows.extend(pair_rows)
        details.extend(pair_details)
    summary = save_results(output, rows, details, 'reviewer_declared_or_unknown')
    provenance = dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, pillow=PIL.__version__,
                      split=split, visits_sha256=digest(visits_path), pairs_sha256=digest(pairs_path),
                      code={p.name: digest(p) for p in [Path(__file__), Path(__file__).with_name('longitudinal_analysis.py'),
                                                      Path(__file__).with_name('capture_guide.py')]})
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inv = commands.add_parser('inventory')
    inv.add_argument('--store', required=True)
    inv.add_argument('--output', required=True)
    run = commands.add_parser('benchmark')
    run.add_argument('--visits', required=True)
    run.add_argument('--pairs', required=True)
    run.add_argument('--output', required=True)
    run.add_argument('--split', choices=['development', 'validation', 'test'], default='development')
    synthetic = commands.add_parser('synthetic', help='Controlled phantoms; no patient data or clinical labels.')
    synthetic.add_argument('--output', required=True)
    synthetic.add_argument('--originals', type=int, default=4)
    synthetic.add_argument('--seed', type=int, default=20261030)
    synthetic.add_argument('--split', choices=['development', 'validation', 'test'], default='development')
    args = parser.parse_args()
    if args.command == 'inventory':
        result = inventory(args.store, args.output)
    elif args.command == 'synthetic':
        from research_synthetic import synthetic_benchmark
        result = synthetic_benchmark(args.output, args.originals, args.seed, args.split)
    else:
        result = benchmark(args.visits, args.pairs, args.output, args.split)
    print(json.dumps(result, ensure_ascii=False, indent=2))
