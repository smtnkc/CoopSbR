"""Validate the completed CPU–GPU experiment and summarize its paired ratios."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import median


METRICS = ('paired_wall_ms', 'end_to_end_ms', 'sort_ms')


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def analyze(manifest, results, output, real_only):
    cases = {row['id']: row for row in json.loads(manifest.read_text())['cases']}
    if real_only:
        cases = {key: value for key, value in cases.items() if value['family'] in ('human-chimp', 'drosophila')}
    design = json.loads((results / 'design.json').read_text())['pairs']
    expected = {(row['case_id'], row['round']): row for row in design if row['case_id'] in cases}
    records = {}
    sample_counts = Counter()
    for path in sorted((results / 'records').glob('*.json')):
        record = json.loads(path.read_text())
        if record['case_id'] not in cases:
            continue
        key = (record['case_id'], record['round'])
        case, plan = cases[key[0]], expected[key]
        if key in records or plan['order'] != record['order'] or case['input_sha256'] != record['input_sha256']:
            raise ValueError(f'Duplicate or mismatched pair: {key}')
        measurements = record['measurements']
        if set(measurements) != {'cpu', 'gpu'}:
            raise ValueError(f'Incomplete CPU–GPU pair: {key}')
        row = dict(case_id=key[0], round=key[1], first=plan['order'][0])
        for method in ('cpu', 'gpu'):
            samples = measurements[method]
            timed = [sample for sample in samples if not sample['warmup']]
            if len(samples) != plan['timed_per_method'] + 1 or len(timed) != plan['timed_per_method']:
                raise ValueError(f'Unexpected number of samples: {key} {method}')
            if any(not sample['verified'] or sample['trace_sha256'] != case['trace_sha256']
                   or sample['reversals'] != case['reversals'] or sample['n'] != case['n'] for sample in samples):
                raise ValueError(f'Trace evidence mismatch: {key} {method}')
            sample_counts.update('warmup' if sample['warmup'] else 'timed' for sample in samples)
            for metric in METRICS:
                row[f'{method}_{metric}'] = median(sample[metric] for sample in timed)
        for metric in METRICS:
            row[f'ratio_{metric}'] = row[f'cpu_{metric}'] / row[f'gpu_{metric}']
        records[key] = row
    if set(records) != set(expected):
        raise ValueError(f'Incomplete campaign: {len(records)} of {len(expected)} expected pairs')

    per_input = []
    for case in cases.values():
        rounds = [value for key, value in records.items() if key[0] == case['id']]
        ratio = [row['ratio_paired_wall_ms'] for row in rounds]
        row = dict(case_id=case['id'], family=case['family'], n=case['n'], k=case['k'],
                   chromosome=case['chromosome'], min_block_bp=case['min_block_bp'],
                   reversals=case['reversals'], paired_rounds=len(rounds))
        for field in ('cpu', 'gpu', 'ratio'):
            for metric in METRICS:
                key = f'{field}_{metric}'
                row[key] = median(item[key] for item in rounds)
        row.update(ratio_min=min(ratio), ratio_max=max(ratio), gpu_faster_rounds=sum(x > 1 for x in ratio))
        per_input.append(row)

    groups = defaultdict(list)
    for row in per_input:
        if row['family'] in ('uniform', 'semi'):
            groups[(row['n'], row['family'])].append(row)
    cells = []
    for (n, family), inputs in sorted(groups.items()):
        ratios = [row['ratio_paired_wall_ms'] for row in inputs]
        if len(inputs) != 5:
            raise ValueError(f'Expected five paired inputs: {n} {family}')
        cells.append(dict(n=n, family=family, inputs=len(inputs), reversals_median=median(row['reversals'] for row in inputs),
                          cpu_wall_ms_median=median(row['cpu_paired_wall_ms'] for row in inputs),
                          gpu_wall_ms_median=median(row['gpu_paired_wall_ms'] for row in inputs),
                          ratio_median=median(ratios), ratio_min=min(ratios), ratio_max=max(ratios),
                          gpu_faster_inputs=sum(x > 1 for x in ratios)))
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / 'paired-rounds.csv', list(records.values()))
    write_csv(output / 'per-input.csv', per_input)
    if cells:
        write_csv(output / 'synthetic-cells.csv', cells)
    coverage = {family: {'inputs': sum(row['family'] == family for row in per_input),
                         'gpu_faster': sum(row['family'] == family and row['ratio_paired_wall_ms'] > 1 for row in per_input)}
                for family in sorted({row['family'] for row in per_input})}
    stats = dict(verified_pairs=len(records), timed=sample_counts['timed'], warmups=sample_counts['warmup'], coverage=coverage)
    (output / 'summary.json').write_text(json.dumps(stats, indent=2) + '\n')
    return per_input, cells, stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--real-only', action='store_true', help='Analyze all real inputs while the synthetic run continues')
    options = parser.parse_args()
    _, _, summary = analyze(options.manifest, options.results, options.out, options.real_only)
    print(json.dumps(summary, indent=2))
