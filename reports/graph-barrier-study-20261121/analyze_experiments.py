"""Validate the matched GPU measurements and reproduce contrasts from raw records."""

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
from itertools import product
import json
from pathlib import Path
from statistics import median


CONTRASTS = {
    'graph_workspace': ('graph-fresh', 'graph-rebuild'),
    'graph_lifecycle': ('graph-rebuild', 'graph-reuse'),
    'graph_fresh_vs_coop': ('graph-fresh', 'coop'),
    'graph_reuse_vs_c4': ('graph-reuse', 'c4-reuse'),
    'graph_reuse_vs_coop': ('graph-reuse', 'coop-reuse'),
    'c4_reuse_vs_coop': ('c4-reuse', 'coop-reuse'),
    'c5_endpoint': ('c5-legacy', 'c5-serial'),
    'c5_parallel_sum': ('c5-serial', 'c5-parallel'),
    'replicated_choice': ('c5-parallel', 'c4'),
    'c5_legacy_vs_c4': ('c5-legacy', 'c4'),
    'out_of_place_split': ('c4', 'f4-split'),
    'fusion': ('f4-split', 'f3-full'),
    'restricted_writes': ('f3-full', 'coop'),
    'c4_vs_f3_full': ('c4', 'f3-full'),
    'c4_vs_coop': ('c4', 'coop'),
}
TIMING_FIELDS = ('end_to_end_ms', 'sort_ms', 'allocation_ms', 'h2d_ms', 'd2h_ms',
                 'graph_setup_ms', 'graph_teardown_ms', 'graph_lifecycle_fraction')
CORE = ('end_to_end_ms', 'sort_ms')


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def exact_bootstrap_median(values):
    # At five independent input pairs this enumerates all 5**5 resamples.
    medians = sorted(median(x) for x in product(values, repeat=len(values)))
    return tuple(medians[round(p * (len(medians)-1))] for p in (0.025, 0.975))


def load_data(manifest, results, real_only):
    provenance = json.loads((results/'provenance.json').read_text())
    if provenance['manifest_sha256'] != sha256(manifest.read_bytes()).hexdigest():
        raise ValueError('Input manifest checksum mismatch')
    cases = {c['id']:c for c in json.loads(manifest.read_text())['cases']}
    if real_only:
        cases = {key:c for key,c in cases.items() if c['family'] in {'drosophila','human-chimp'}}
    methods = provenance['methods']
    design = {(b['case_id'],b['round']):b for b in json.loads((results/'design.json').read_text())
              if b['case_id'] in cases}
    rounds = []
    counts = Counter()
    seen = set()
    for file in sorted((results/'records').glob('*.json')):
        record = json.loads(file.read_text())
        case_id = record['case_id']
        if case_id not in cases:
            continue
        key = (case_id,record['round'])
        if key in seen or key not in design:
            raise ValueError(f'Missing or duplicate match {key}')
        seen.add(key)
        case, block = cases[case_id], design[key]
        if record['input_sha256'] != case['input_sha256'] or record['order'] != block['order']:
            raise ValueError(f'Input or order mismatch {key}')
        grid = set()
        if set(record['measurements']) != set(methods):
            raise ValueError(f'Method coverage mismatch {key}')
        for method, data in record['measurements'].items():
            rows = data['rows']
            timed = [r for r in rows if not r['warmup']]
            if len(rows) != block['reps']+1 or len(timed) != block['reps']:
                raise ValueError(f'Sample count mismatch {key} {method}')
            barriers = methods[method][2]
            nbar = barriers*case['reversals']+2 if barriers else 0
            if any(not r['verified'] or r['trace_sha256']!=case['trace_sha256'] or r['n']!=case['n']
                   or r['reversals']!=case['reversals'] or r['grid_barriers']!=nbar for r in rows):
                raise ValueError(f'Invalid trace or barrier evidence {key} {method}')
            grid.update(r['blocks'] for r in rows)
            counts.update('warmups' if r['warmup'] else 'timed' for r in rows)
            for row in timed:
                row['graph_lifecycle_fraction']=(row['graph_setup_ms']+row['graph_teardown_ms'])/row['end_to_end_ms']
            entry = {k:median(r[k] for r in timed) for k in TIMING_FIELDS}
            rounds.append(dict(case_id=case_id, round=key[1], family=case['family'], n=case['n'],
                               reversals=case['reversals'], blocks=timed[0]['blocks'], method=method,
                               **entry, **data['lifecycle']))
        if len(grid)!=1:
            raise ValueError(f'Unmatched grids {key}')
    if seen != set(design):
        raise ValueError(f'Incomplete dataset: {len(seen)}/{len(design)} matched rounds')
    return rounds, counts, cases


def analyze(manifest, results, out, real_only):
    rounds, counts, cases = load_data(manifest, results, real_only)
    by_round = defaultdict(dict)
    component_groups = defaultdict(list)
    for row in rounds:
        by_round[(row['case_id'],row['round'])][row['method']] = row
        component_groups[(row['case_id'],row['method'])].append(row)
    comparisons = []
    groups = defaultdict(list)
    for (case_id, round_number), rows in by_round.items():
        case = cases[case_id]
        for name,(a,b) in CONTRASTS.items():
            for metric in CORE:
                before, after = rows[a][metric], rows[b][metric]
                row = dict(contrast=name, case_id=case_id, round=round_number, n=case['n'],
                           family=case['family'], reversals=case['reversals'], metric=metric,
                           baseline=a, comparison=b, baseline_ms=before, comparison_ms=after,
                           delta_ms=before-after, ratio=before/after)
                comparisons.append(row)
                groups[(name,case_id,metric)].append(row)
    inputs = []
    synthetic_groups = defaultdict(list)
    for (name,case_id,metric), rows in groups.items():
        case = cases[case_id]
        ratios = [r['ratio'] for r in rows]
        entry = dict(contrast=name, case_id=case_id, n=case['n'], family=case['family'],
                     chromosome=case['chromosome'], min_block_bp=case['min_block_bp'],
                     reversals=case['reversals'], metric=metric, rounds=len(rows),
                     baseline_ms=median(r['baseline_ms'] for r in rows),
                     comparison_ms=median(r['comparison_ms'] for r in rows),
                     delta_ms=median(r['delta_ms'] for r in rows), ratio=median(ratios),
                     ratio_min=min(ratios), ratio_max=max(ratios), above_parity=sum(x>1 for x in ratios))
        inputs.append(entry)
        if case['family'] in {'uniform','semi'}:
            synthetic_groups[(name,metric,case['family'],case['n'])].append(entry)
    cells = []
    for (name,metric,family,n), rows in sorted(synthetic_groups.items()):
        ratios = [r['ratio'] for r in rows]
        assert len(ratios)==5
        lower, upper = exact_bootstrap_median(ratios)
        cells.append(dict(contrast=name, metric=metric, family=family, n=n, inputs=5,
                          ratio_median=median(ratios), ratio_min=min(ratios), ratio_max=max(ratios),
                          bootstrap_low=lower, bootstrap_high=upper, above_parity=sum(x>1 for x in ratios),
                          median_delta_ms=median(r['delta_ms'] for r in rows)))
    components = []
    for (_,method), rows in component_groups.items():
        first=rows[0]
        components.append(dict(case_id=first['case_id'], family=first['family'], n=first['n'], blocks=first['blocks'],
                               method=method, **{k:median(r[k] for r in rows) for k in
                               (*TIMING_FIELDS,'workspace_setup_ms','workspace_teardown_ms')}))
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out/'matched-rounds.csv', comparisons)
    write_csv(out/'per-input.csv', inputs)
    write_csv(out/'timing-components.csv', components)
    if cells:
        write_csv(out/'synthetic-cells.csv',cells)
    if (results/'amortized.json').exists():
        amort = json.loads((results/'amortized.json').read_text())
        assert len(amort)==36
        write_csv(out/'amortized.csv', [dict(case_id=r['case_id'], calls=r['calls'], method=r['method'],
                                            average_ms=r['average_ms'], steady_median_ms=median(r['timed']),
                                            **r['lifecycle']) for r in amort])
    summary = dict(cases=len(cases), rounds=len(by_round), method_rounds=len(rounds), **counts)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--real-only', action='store_true')
    args=parser.parse_args()
    analyze(args.manifest,args.results,args.out,args.real_only)
