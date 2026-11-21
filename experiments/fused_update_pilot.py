"""Measure fused reversal and summary production on paired inputs."""
import argparse
import csv
import hashlib
import json
import random
import statistics
import subprocess
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PILOT_METHODS = ('cooperative-replicated', 'cooperative-fused-full', 'cooperative-fused-changed')
MAIN_METHODS = (*PILOT_METHODS, 'graph')
LABELS = dict(zip(MAIN_METHODS, ('baseline', 'full', 'changed', 'graph')))
BARRIERS_PER_REVERSAL = dict(zip(PILOT_METHODS, (4, 3, 3)))
SIZES = {2048, 32768, 131072}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(main):
    synthetic = ROOT / 'datasets/comparisons/graph-size-sweep-v1'
    real = ROOT / 'datasets/comparisons/graph-v1'
    expected = json.loads((synthetic / 'expected-traces.json').read_text())['cases']
    with (ROOT / 'reports/graph-reference-20261118/per-input.csv').open() as f:
        for row in csv.DictReader(f):
            if row['family'] == 'real':
                expected[row['case_id']] = row
    cases = []
    for corpus in (synthetic, real):
        for row in json.loads((corpus / 'manifest.json').read_text())['cases']:
            if corpus == synthetic:
                if main and row['split'] != 'main':
                    continue
                if not main and (row['split'] != 'pilot' or row['n'] not in SIZES):
                    continue
            if corpus == real and row['split'] != 'real':
                continue
            cases.append((row, corpus / row['path'], expected[row['id']]['trace_sha256']))
    if len(cases) != (76 if main else 18):
        raise ValueError("Unexpected corpus coverage")
    random.Random(42).shuffle(cases)
    return cases


def load_supplement(path):
    rows = json.loads(path.read_text())['cases']
    if not rows or len({row['id'] for row in rows}) != len(rows):
        raise ValueError('Supplement must contain distinct cases')
    cases = [(row, path.parent / row['path'], row['trace_sha256']) for row in rows]
    random.Random(42).shuffle(cases)
    return cases


def command(args):
    return subprocess.check_output(args, text=True, timeout=60)


def write_csv(path, rows):
    with path.open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def run(out, binary, checker, main, supplement=None):
    start = time.monotonic()
    if supplement is None:
        cases = load_cases(main)
        split = 'main' if main else 'pilot'
    else:
        cases = load_supplement(supplement)
        split = 'supplementary'
    selected = PILOT_METHODS if split == 'pilot' else MAIN_METHODS
    out.mkdir(exist_ok=True)
    traces = out / 'traces'
    traces.mkdir()
    active = command(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'])
    if active.strip():
        raise RuntimeError('GPU occupied at experiment start')
    methods_rng = random.Random(42)
    source = command(['git', '-C', str(ROOT), 'rev-parse', 'HEAD']).strip()
    host = command(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader']).strip()
    provenance = dict(source_commit=source, gpu=host, solver_sha256=sha(binary), checker_sha256=sha(checker),
                      seed=42, main_repetitions=3, warmups=1, methods=selected,
                      split=split)
    if supplement is not None:
        provenance.update(manifest_sha256=sha(supplement), runner_sha256=sha(Path(__file__)))
    if split != 'pilot':
        pilot = json.loads((ROOT / 'reports/fused-update-pilot-20261120/provenance.json').read_text())
        for field in ('solver_sha256', 'checker_sha256'):
            if provenance[field] != pilot[field]:
                raise ValueError(f'Run must reuse the validated pilot binary: {field}')
        provenance['solver_source_commit'] = pilot['source_commit']
    pairs = []
    with (out / 'measurements.jsonl').open('x') as log:
        for case, path, trace_sha in cases:
            if sha(path) != case['sha256']:
                raise ValueError(f'Input hash mismatch: {case["id"]}')
            methods = list(selected)
            methods_rng.shuffle(methods)
            grouped = {}
            for method in methods:
                prefix = traces / f'{case["id"]}-{method}'
                rows = [json.loads(line) for line in command([
                    str(binary), '--input', str(path), '--trace', str(prefix), '--mode', 'gpu-full',
                    '--update', 'full', '--reduction', 'scalar', '--candidate', 'local',
                    '--coord', method, '--threads', '128', '--warmups', '1', '--repetitions', '3',
                ]).splitlines()]
                if [(r['warmup'], r['sample']) for r in rows] != [(True, 0), (False, 0), (False, 1), (False, 2)]:
                    raise ValueError('Unexpected measurement protocol')
                for row in rows:
                    if (row['coordination'] != method or row['update'] != 'full' or row['reduction'] != 'scalar'
                            or row['candidate'] != 'local' or row['threads'] != 128 or row['n'] != case['n']
                            or row['debug'] or row['instrumented']):
                        raise ValueError('Unexpected solver configuration')
                    if method == 'graph':
                        if (row['grid_barriers'] != 0 or row['graph_launches'] != 1
                                or row['graph_setup_ms'] <= 0 or row['graph_teardown_ms'] < 0):
                            raise ValueError('Incorrect Graph accounting')
                    elif row['grid_barriers'] != BARRIERS_PER_REVERSAL[method]*row['reversals']+2:
                        raise ValueError('Incorrect barrier count')
                    trace = Path(row.pop('trace_path'))
                    checked = json.loads(command([str(checker), str(path), str(trace)]))
                    if (not checked['verified'] or checked['n'] != row['n']
                            or checked['reversals'] != row['reversals'] or sha(trace) != trace_sha):
                        raise ValueError(f'Trace certificate mismatch: {case["id"]} {method}')
                    row.update(case_id=case['id'], family=case['family'], k=case.get('k'),
                               trace_sha256=trace_sha, input_sha256=case['sha256'])
                    log.write(json.dumps(row)+'\n')
                log.flush()
                grouped[method] = rows
            rows = [r for group in grouped.values() for r in group]
            for field in ('n', 'blocks', 'threads', 'reversals', 'updated_elements', 'summary_elements', 'candidate_elements'):
                if len({r[field] for r in rows}) != 1:
                    raise ValueError(f'Unmatched {field}: {case["id"]}')
            span = case['n']+2
            trace = traces / f'{case["id"]}-{selected[0]}.sample-0'
            intervals = [tuple(map(int, line.split())) for line in trace.read_text().splitlines()[1:]]
            previous = (0, -1)
            copied = span  # Initial duplicate.
            for left, right in intervals:
                a, b = previous
                copied += (right-left+1) + (b-a+1) - max(0, min(right,b)-max(left,a)+1)
                previous = left, right
            pair = dict(case_id=case['id'], family=case['family'], n=case['n'], k=case.get('k'),
                        blocks=rows[0]['blocks'], reversals=len(intervals),
                        median_reversal_fraction=statistics.median((b-a+1)/case['n'] for a,b in intervals) if intervals else 0,
                        full_permutation_writes=span*len(intervals), changed_permutation_writes=copied,
                        baseline_permutation_writes=2*sum((b-a+1)//2 for a,b in intervals),
                        **{f'method_{i+1}': method for i, method in enumerate(methods)})
            for method in selected:
                label = LABELS[method]
                for metric in ('sort_ms', 'end_to_end_ms', 'allocated_bytes'):
                    pair[label+'_'+metric] = statistics.median(r[metric] for r in grouped[method][1:])
            for label in ('full', 'changed'):
                for metric in ('sort_ms', 'end_to_end_ms'):
                    pair[label+'_'+metric+'_ratio'] = pair['baseline_'+metric]/pair[label+'_'+metric]
            pairs.append(pair)
            print(f"Verified {len(pairs)}/{len(cases)}: {case['id']}", flush=True)
    groups = defaultdict(list)
    for row in pairs:
        if row['family'] != 'real':
            groups[row['n'], row['family']].append(row)
    cells = []
    for (n, family), rows in sorted(groups.items()):
        cell = dict(n=n, family=family, inputs=len(rows))
        for label in ('full', 'changed'):
            for metric in ('sort_ms', 'end_to_end_ms'):
                field = label+'_'+metric+'_ratio'
                cell[field] = statistics.median(r[field] for r in rows)
        cells.append(cell)
    write_csv(out / 'pairs.csv', pairs)
    if cells:
        write_csv(out / 'cells.csv', cells)
    active = command(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'])
    if active.strip():
        raise RuntimeError('Unexpected GPU compute process at experiment completion')
    real_inputs = sum(case['family'] == 'real' for case, _, _ in cases)
    provenance.update(verified_calls=len(cases)*len(selected)*4, elapsed_seconds=time.monotonic()-start,
                      real_inputs=real_inputs, synthetic_inputs=len(cases)-real_inputs)
    (out / 'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--checker', required=True, type=Path)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--main', action='store_true', help='Run all 70 main synthetic cases and four GPU methods')
    selection.add_argument('--supplement', type=Path,
                           help='Run the four GPU methods on a manifest with input and sequential trace hashes')
    options = parser.parse_args()
    run(options.out.resolve(), options.binary.resolve(), options.checker.resolve(),
        options.main, options.supplement)
