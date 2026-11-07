"""Controlled synthetic acquisition benchmark; no patients or diagnostic labels."""
import json
import platform
from pathlib import Path

import cv2
import numpy as np
import PIL
from PIL import Image, ImageFilter

from research_evaluation import digest, evaluate_pair, save_results, validate, write_csv


GENERATOR_VERSION = 'acquisition-controls-v1'
SPLIT_OFFSETS = {'development': 0, 'validation': 1_000_000, 'test': 2_000_000}


def synthetic_original(seed):
    """Textured skin-colored phantom, not a realistic or medically labelled lesion."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 13, (400, 400, 1))
    pixels = np.uint8(np.clip(np.full((400, 400, 3), (185, 145, 120)) + noise, 0, 255))
    for _ in range(150):
        point = tuple(int(value) for value in rng.integers(18, 382, 2))
        cv2.circle(pixels, point, 2, (120, 90, 65), -1)
    mask = np.zeros((400, 400), dtype='uint8')
    cv2.circle(mask, (200, 200), 45, 255, -1)
    pixels[mask > 0] = (85, 58, 40)
    return Image.fromarray(pixels), Image.fromarray(mask)


def perturbations(photo, mask):
    """Expectations are preset by construction, never copied from gate outputs."""
    matrix = cv2.getRotationMatrix2D((199.5, 199.5), 3, 1.03)
    matrix[:, 2] += (5, -4)
    affine_photo = Image.fromarray(cv2.warpAffine(np.asarray(photo), matrix, photo.size,
                                                 borderMode=cv2.BORDER_REFLECT))
    affine_mask = Image.fromarray(cv2.warpAffine(np.asarray(mask), matrix, mask.size,
                                                flags=cv2.INTER_NEAREST))
    lighter = Image.fromarray(np.uint8(np.clip(np.asarray(photo).astype('int16') + 10, 0, 255)))
    dark = Image.fromarray(np.uint8(np.asarray(photo).astype('float64') * 0.12))
    return [
        ('unchanged', photo.copy(), mask.copy(), 'yes', {'operation': 'identity'}),
        ('affine_mild', affine_photo, affine_mask, 'yes', {'operation': 'affine', 'matrix': matrix.tolist()}),
        ('brightness_mild', lighter, mask.copy(), 'yes', {'operation': 'add_rgb', 'offset': 10}),
        ('blur_severe', photo.filter(ImageFilter.GaussianBlur(15)), mask.copy(), 'no',
         {'operation': 'gaussian_blur', 'radius': 15}),
        ('dark_severe', dark, mask.copy(), 'no', {'operation': 'multiply_rgb', 'factor': 0.12}),
    ]


def synthetic_benchmark(output, originals=4, seed=20261030, split='development'):
    """Produce six cases per original, including similar-looking different originals."""
    if not 2 <= originals <= 1000:
        raise ValueError('Use between 2 and 1000 synthetic originals.')
    if not 0 <= seed < 1_000_000_000:
        raise ValueError('Seed must be between 0 and 999999999.')
    if split not in SPLIT_OFFSETS:
        raise ValueError('Unknown split.')
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Synthetic benchmark requires a new or empty output directory.')
    output.mkdir(parents=True, exist_ok=True)
    image_dir = output / 'synthetic_images'
    image_dir.mkdir()
    # The seed identity is independent of the split label, so combining manifests
    # catches accidentally reused originals even when users rename partitions.
    seeds = [seed + SPLIT_OFFSETS[split] + index for index in range(originals)]
    originals_data = [synthetic_original(value) for value in seeds]
    visits, pair_manifest, rows, details = [], [], [], []

    def save_visit(photo, mask, record_id, source_seed, captured_at):
        original_id = f'{GENERATOR_VERSION}-seed-{source_seed}'
        image_path, mask_path = image_dir / (record_id + '.png'), image_dir / (record_id + '-mask.png')
        photo.save(image_path)
        mask.save(mask_path)
        row = dict(record_id=record_id, person_id=original_id, lesion_id=original_id,
                   captured_at=captured_at, split=split, image=str(image_path), mask=str(mask_path),
                   image_sha256=digest(image_path), mask_sha256=digest(mask_path),
                   source_original_id=original_id, source='synthetic_phantom',
                   identity_source='generator_seed', contour_reviewer='generated_not_human')
        visits.append(row)
        return row

    bases = [save_visit(photo, mask, f'original-{index:04d}', value, '2000-01-01')
             for index, (value, (photo, mask)) in enumerate(zip(seeds, originals_data))]
    for index, (photo, mask) in enumerate(originals_data):
        base = bases[index]
        cases = perturbations(photo, mask)
        other_index = (index + 1) % originals
        other_photo, other_mask = originals_data[other_index]
        cases.append(('different_original', other_photo, other_mask, 'no',
                      {'operation': 'different_seed', 'source_seed': seeds[other_index]}))
        for name, current, current_mask, expected, parameters in cases:
            pair_id = f'phantom-{index:04d}-{name}'
            source_seed = seeds[other_index] if name == 'different_original' else seeds[index]
            visit = save_visit(current, current_mask, pair_id, source_seed, '2000-01-02')
            pair = dict(pair_id=pair_id, previous_id=base['record_id'], current_id=visit['record_id'],
                        previous_original_id=base['source_original_id'], current_original_id=visit['source_original_id'],
                        reference_identity='different' if name == 'different_original' else 'same',
                        reference_comparable=expected, capture_group=name,
                        reference_source='synthetic_construction', parameters=json.dumps(parameters, sort_keys=True))
            pair_manifest.append(pair)
            pair_rows, pair_details = evaluate_pair([photo, mask, current, current_mask], pair, base['person_id'], split)
            rows.extend(pair_rows)
            details.extend(pair_details)
    validate(visits)
    write_csv(output / 'visits.csv', visits, list(visits[0]))
    write_csv(output / 'synthetic_pairs.csv', pair_manifest, list(pair_manifest[0]))
    summary = save_results(output, rows, details, 'synthetic_expectations')
    summary['synthetic_originals'] = originals
    summary['synthetic_pairs'] = len(pair_manifest)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    source = Path(__file__).parent
    provenance = dict(generator=GENERATOR_VERSION, seed=seed, split=split, original_seeds=seeds,
                      date_note='Dates are fixed placeholders, not longitudinal visits.',
                      python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, pillow=PIL.__version__,
                      visits_sha256=digest(output / 'visits.csv'), pairs_sha256=digest(output / 'synthetic_pairs.csv'),
                      code={name: digest(source / name) for name in
                            ('research_synthetic.py', 'research_evaluation.py', 'longitudinal_analysis.py', 'capture_guide.py')})
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    return summary
