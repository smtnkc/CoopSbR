"""Measure the Graph lifecycle and cooperative ablations in matched blocks."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import subprocess
import tempfile
import time


# Value: CUDA coordination, reuse scope, barriers per completed reversal.
METHODS = {
    'c5-legacy': ('cooperative', 'none', 5),
    'c5-serial': ('cooperative-matched-serial', 'none', 5),
    'c5-parallel': ('cooperative-matched-parallel', 'none', 5),
    'c4': ('cooperative-replicated', 'none', 4),
    'f4-split': ('cooperative-split-full', 'none', 4),
    'f3-full': ('cooperative-fused-full', 'none', 3),
    'coop': ('cooperative-fused-changed', 'none', 3),
    'graph-fresh': ('graph', 'none', 0),
    'graph-rebuild': ('graph', 'workspace', 0),
    'graph-reuse': ('graph', 'graph', 0),
    'c4-reuse': ('cooperative-replicated', 'workspace', 4),
    'coop-reuse': ('cooperative-fused-changed', 'workspace', 3),
}
SEED = 42


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def command(args, timeout=120):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'{p.returncode}: {args[0]}: {p.stderr.strip()} {p.stdout[-1200:]}')
    return p


def write(path, data):
    tmp = path.with_suffix('.pending')
    tmp.write_text(json.dumps(data, allow_nan=False) + '\n')
    tmp.replace(path)


def design(cases):
    rng = random.Random(SEED)
    real = [c for c in cases if c['family'] in {'drosophila', 'human-chimp'}]
    real_order = {}
    for c in real:
        orders = []
        for _ in range(3):
            order = rng.sample(list(METHODS), len(METHODS))
            orders.extend([order, order[::-1]])
        rng.shuffle(orders)
        real_order[c['id']] = orders
    matrix = []
    for j in range(6):
        rng.shuffle(real)
        matrix.extend(dict(case_id=c['id'], round=j+1, reps=5, order=real_order[c['id']][j]) for c in real)
    synthetic = []
    cells = defaultdict(list)
    for c in cases:
        if c['family'] in {'uniform', 'semi'}:
            cells[(c['n'], c['family'])].append(c)
    for _, group in sorted(cells.items()):
        assert len(group) == 5
        rng.shuffle(group)
        orders = []
        for _ in range(2):
            order = rng.sample(list(METHODS), len(METHODS))
            orders.extend([order, order[::-1]])
        orders.append(rng.sample(list(METHODS), len(METHODS)))
        synthetic.extend(dict(case_id=c['id'], round=1, reps=3, order=order) for c, order in zip(group, orders))
    rng.shuffle(synthetic)
    return matrix + synthetic


def check_trace(checker, case, trace):
    checked = json.loads(command([checker, case['input_path'], trace]).stdout)
    if (not checked['verified'] or checked['n'] != case['n'] or checked['reversals'] != case['reversals']
            or sha(trace) != case['trace_sha256']):
        raise ValueError(f'Trace certificate mismatch: {case["id"]}')


def measure(binary, checker, case, method, repetitions, scratch, alternate=None):
    coordination, reuse, barriers = METHODS[method]
    prefix = scratch / method
    args = [binary, '--input', case['input_path'], '--trace', prefix, '--warmups', '1',
            '--repetitions', str(repetitions), '--mode', 'gpu-full', '--update', 'full',
            '--candidate', 'local', '--reduction', 'scalar', '--coord', coordination,
            '--threads', '128', '--matched-grid', '--reuse', reuse]
    if alternate:
        args += ['--alternate-input', alternate['input_path']]
    process = command(args, timeout=1200)
    rows = [json.loads(line) for line in process.stdout.splitlines()]
    expected = [(True, 0)] + [(False, i) for i in range(repetitions)]
    if [(x['warmup'], x['sample']) for x in rows] != expected:
        raise ValueError(f'Wrong sample count: {case["id"]}, {method}')
    if reuse == 'none':
        if process.stderr:
            raise ValueError(process.stderr)
        lifecycle = {'workspace_setup_ms': 0, 'workspace_teardown_ms': 0}
    else:
        lifecycle = json.loads(process.stderr)
        if any(not math.isfinite(lifecycle[k]) or lifecycle[k] <= 0
               for k in ('workspace_setup_ms', 'workspace_teardown_ms')):
            raise ValueError(f'Invalid reusable workspace timing: {case["id"]}, {method}')
    for row in rows:
        expected_index = int(bool(alternate) and not row['warmup'] and row['sample'] % 2 == 1)
        if row['input_index'] != expected_index:
            raise ValueError('Unexpected input order')
        active = alternate if expected_index else case
        nbar = barriers * active['reversals'] + 2 if barriers else 0
        if (row['coordination'], row['n'], row['reversals'], row['grid_barriers'], row['threads'], row['update'],
            row['candidate'], row['reduction'], row['debug'], row['instrumented']) != (
                coordination, active['n'], active['reversals'], nbar, 128, 'full', 'local', 'scalar', False, False):
            raise ValueError(f'Unexpected configuration: {active["id"]}, {method}')
        if barriers:
            if row['graph_launches'] != 0 or row['kernel_launches'] != 1:
                raise ValueError('Unexpected cooperative launch counts')
        elif (row['graph_launches'] != 1 or row['kernel_launches'] != 3+5*active['reversals']
              or row['graph_nodes'] != 9):
            raise ValueError('Unexpected conditional Graph launch counts')
        rebuilding = coordination == 'graph' and reuse != 'graph'
        for key in ('graph_setup_ms', 'graph_teardown_ms'):
            if not math.isfinite(row[key]) or rebuilding != (row[key] > 0):
                raise ValueError(f'Unexpected Graph lifecycle component: {method} {key}')
        if any(not math.isfinite(row[k]) or row[k] <= 0 for k in ('end_to_end_ms', 'sort_ms', 'h2d_ms', 'd2h_ms')):
            raise ValueError(f'Invalid timing for {active["id"]} {method}')
        trace = Path(row.pop('trace_path'))
        check_trace(checker, active, trace)
        trace.unlink()
        row.update(case_id=active['id'], trace_sha256=active['trace_sha256'], verified=True)
    return {'lifecycle': lifecycle, 'rows': rows}


def validate_work(measurements):
    rows = [row for result in measurements.values() for row in result['rows']]
    for field in ('n', 'blocks', 'threads', 'reversals', 'initial_breakpoints',
                  'candidate_elements', 'summary_elements', 'updated_elements'):
        if len({row[field] for row in rows}) != 1:
            raise ValueError(f'Unmatched per-input work or launch size: {field}')


def identity_case(binary, checker, size, root):
    file = root / 'identity.txt'
    file.write_text(str(size) + '\n' + ' '.join(map(str, range(1, size+1))) + '\n')
    ref = root / 'identity.trace'
    command([binary, '--input', file, '--trace', ref, '--mode', 'seq'])
    case = dict(id='identity-control', input_path=file, n=size, reversals=0, trace_sha256=sha(ref))
    check_trace(checker, case, ref)
    return case


def pilot(binary, checker, cases, results):
    by_id = {c['id']: c for c in cases}
    with tempfile.TemporaryDirectory(prefix='pilot-',dir=results) as folder:
        scratch = Path(folder)
        case = by_id['main-uniform-n2048-kna-000']
        identity = identity_case(binary, checker, case['n'], scratch)
        all_modes = {}
        for c in (identity, case, by_id['real-v1-dmel-dsim-3L'], by_id['hg38-panTro6-chr1-min250'],
                  by_id['hg38-panTro6-chr16-min250']):
            records = {m: measure(binary, checker, c, m, 2, scratch) for m in METHODS}
            validate_work(records)
            all_modes[c['id']] = len(records) * 3
        replay = {
            m: measure(binary, checker, case, m, 4, scratch, alternate=other)
            for m, other in [('graph-reuse', identity), ('graph-rebuild', identity), ('coop-reuse', identity)]
        }
        replay['graph-reuse-two-nonidentity'] = measure(binary, checker, case, 'graph-reuse', 4, scratch,
                                                          alternate=by_id['main-semi-n2048-k64-000'])
    write(results/'pilot.json', {'all_methods_calls_per_input': all_modes, 'alternating_reuse': replay})
    print('Pilot passed: identity, synthetic, fly and both primary chromosomes; alternating reuse verified.', flush=True)


def run(root):
    results = root/'results'
    records = results/'records'
    records.mkdir(parents=True, exist_ok=True)
    binary, checker = root/'build/coopsbr', root/'build/coopsbr-check'
    if command(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader']).stdout.strip():
        raise RuntimeError('GPU has an active compute process at the start')
    manifest = root/'cases.json'
    cases = json.loads(manifest.read_text())['cases']
    by_id = {c['id']:c for c in cases}
    for c in cases:
        c['input_path'] = root/'inputs'/c['path']
        if sha(c['input_path']) != c['input_sha256']:
            raise ValueError(f'Input checksum mismatch: {c["id"]}')
    matrix = design(cases)
    assert len(matrix) == 142
    provenance = dict(gpu=command(['nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader']).stdout.strip(),
                      source_commit=json.loads(manifest.read_text())['solver_source_commit'], seed=SEED,
                      runner_sha256=sha(Path(__file__)), manifest_sha256=sha(manifest), methods=METHODS,
                      solver_sha256=sha(binary), checker_sha256=sha(checker))
    previous = results/'provenance.json'
    if previous.exists() and json.loads(previous.read_text()) != json.loads(json.dumps(provenance)):
        raise RuntimeError('Existing partial results have different provenance')
    write(previous, provenance)
    write(results/'design.json', matrix)
    if not (results/'pilot.json').exists():
        pilot(binary, checker, cases, results)
    start = time.monotonic()
    for index, block in enumerate(matrix, 1):
        case = by_id[block['case_id']]
        path = records/f'{index:03d}-{case["id"]}-r{block["round"]}.json'
        if path.exists():
            continue
        with tempfile.TemporaryDirectory(prefix='traces-',dir=results) as folder:
            values = {m: measure(binary, checker, case, m, block['reps'], Path(folder)) for m in block['order']}
        validate_work(values)
        write(path, dict(**block, input_sha256=case['input_sha256'], measurements=values))
        print(f'{index}/{len(matrix)} {case["id"]} r{block["round"]}', flush=True)
    rng = random.Random(SEED+1)
    amortized = []
    for case_id in ('real-v1-dmel-dsim-3L','hg38-panTro6-chr1-min250','hg38-panTro6-chr16-min250'):
        for calls in (1, 10, 100):
            subset = ('graph-fresh', 'graph-reuse', 'c4-reuse', 'coop-reuse')
            for method in rng.sample(subset, len(subset)):
                with tempfile.TemporaryDirectory(prefix='amortized-',dir=results) as folder:
                    value = measure(binary, checker, by_id[case_id], method, calls, Path(folder))
                timed = [r['end_to_end_ms'] for r in value['rows'] if not r['warmup']]
                amortized.append(dict(case_id=case_id, calls=calls, method=method, lifecycle=value['lifecycle'],
                                      timed=timed, average_ms=(sum(timed)+sum(value['lifecycle'].values()))/calls))
    write(results/'amortized.json', amortized)
    if command(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader']).stdout.strip():
        raise RuntimeError('GPU has an unexpected compute process at the end')
    assert len(list(records.glob('*.json'))) == len(matrix)
    write(results/'complete.json', dict(pairs=len(matrix), cases=len(cases), methods=len(METHODS),
                                        elapsed_seconds=time.monotonic()-start))
    print('Verified full matched matrix and direct amortized batches.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    run(parser.parse_args().root.resolve())
