"""Run warmed, trace-verified CPU–GPU pairs on the CoopSbR workstation."""

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time


GPU_COORDINATION = 'cooperative-fused-changed'
SEED = 42


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def command(args, timeout=20):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr.strip()}')
    return result.stdout.strip()


def write_json(path, data):
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(data, indent=2) + '\n')
    pending.replace(path)


def schedule(cases):
    rng = random.Random(SEED)
    real = [case for case in cases if case['min_block_bp'] or case['family'] == 'drosophila']
    cells = defaultdict(list)
    for case in cases:
        if case['family'] in ('uniform', 'semi'):
            cells[(case['n'], case['family'])].append(case)
    orders = {}
    for case in real:
        orders[case['id']] = [True] * 3 + [False] * 3
        rng.shuffle(orders[case['id']])
    result = []
    for round_index in range(6):
        rng.shuffle(real)
        result.extend((case, round_index + 1, 5, orders[case['id']][round_index]) for case in real)
    synthetic = []
    for cell_index, key in enumerate(sorted(cells)):
        cell = cells[key]
        rng.shuffle(cell)
        synthetic.extend((case, 1, 3, (index + cell_index) % 2 == 0) for index, case in enumerate(cell))
    rng.shuffle(synthetic)
    return result + synthetic


def measure(binary, checker, case, path, method, repetitions, scratch):
    prefix = scratch / method
    args = [binary, '--input', path, '--trace', prefix, '--warmups', '1', '--repetitions', str(repetitions)]
    if method == 'cpu':
        args.extend(('--mode', 'seq'))
    else:
        args.extend(('--mode', 'gpu-full', '--update', 'full', '--candidate', 'local',
                     '--reduction', 'scalar', '--coord', GPU_COORDINATION, '--threads', '128'))
    rows = [json.loads(line) for line in command(args, timeout=1200).splitlines()]
    expected_samples = [(True, 0)] + [(False, i) for i in range(repetitions)]
    if [(row['warmup'], row['sample']) for row in rows] != expected_samples:
        raise ValueError(f'Wrong sample count: {case["id"]} {method}')
    for row in rows:
        expected_coord = 'sequential' if method == 'cpu' else GPU_COORDINATION
        expected_barriers = 0 if method == 'cpu' else 3 * case['reversals'] + 2
        expected_threads = 1 if method == 'cpu' else 128
        if (row['coordination'] != expected_coord or row['n'] != case['n']
                or row['reversals'] != case['reversals'] or row['grid_barriers'] != expected_barriers
                or row['threads'] != expected_threads or row['debug'] or row['instrumented']
                or row['update'] != 'full' or (method == 'gpu' and
                    (row['candidate'], row['reduction']) != ('local', 'scalar'))):
            raise ValueError(f'Solver configuration mismatch: {case["id"]} {method}')
        for metric in ('paired_wall_ms', 'end_to_end_ms', 'sort_ms'):
            if not math.isfinite(row[metric]) or row[metric] <= 0:
                raise ValueError(f'Invalid {metric}: {case["id"]} {method}')
        trace = Path(row.pop('trace_path'))
        checked = json.loads(command([checker, path, trace], timeout=90))
        if (not checked['verified'] or checked['n'] != case['n']
                or checked['reversals'] != case['reversals'] or sha(trace) != case['trace_sha256']):
            raise ValueError(f'Trace certificate mismatch: {case["id"]} {method}')
        row['trace_sha256'] = case['trace_sha256']
        row['verified'] = True
        trace.unlink()
    return rows


def run(options):
    start = time.monotonic()
    input_manifest = json.loads(options.manifest.read_text())
    cases = input_manifest['cases']
    planned = schedule(cases)
    out = options.out
    records = out / 'records'
    records.mkdir(parents=True, exist_ok=True)
    gpu = command(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'])
    if not gpu.startswith('NVIDIA RTX 6000 Ada Generation,') or '\n' in gpu:
        raise RuntimeError(f'Unexpected benchmark GPU: {gpu}')
    if command(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader']):
        raise RuntimeError('GPU already has an active compute process')
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                if line.startswith('model name')), 'unknown')
    provenance = {
        'solver_source_commit': input_manifest['solver_source_commit'], 'gpu': gpu, 'cpu': cpu,
        'cpu_affinity': sorted(os.sched_getaffinity(0)), 'manifest_sha256': sha(options.manifest),
        'solver_sha256': sha(options.binary), 'checker_sha256': sha(options.checker),
        'runner_sha256': sha(Path(__file__)), 'seed': SEED, 'planned_pairs': len(planned),
        'primary_metric': 'paired_wall_ms', 'warmup_per_method_per_pair': 1,
    }
    previous = out / 'provenance.json'
    if previous.exists() and json.loads(previous.read_text()) != provenance:
        raise RuntimeError('Existing measurements have different provenance')
    write_json(previous, provenance)
    paths = {}
    for case in cases:
        path = (options.inputs / case['path']).resolve()
        if sha(path) != case['input_sha256']:
            raise ValueError(f'Input checksum mismatch: {case["id"]}')
        paths[case['id']] = path
    write_json(out / 'design.json', {
        'pairs': [dict(case_id=case['id'], round=round_id, timed_per_method=reps,
                       order=['cpu', 'gpu'] if cpu_first else ['gpu', 'cpu'])
                  for case, round_id, reps, cpu_first in planned],
    })
    for index, (case, round_id, reps, cpu_first) in enumerate(planned, start=1):
        record = records / f'{index:03d}-{case["id"]}-r{round_id}.json'
        if record.exists():
            continue
        order = ('cpu', 'gpu') if cpu_first else ('gpu', 'cpu')
        path = paths[case['id']]
        with tempfile.TemporaryDirectory(prefix='traces-', dir=out) as directory:
            measurements = {method: measure(options.binary, options.checker, case, path, method, reps, Path(directory))
                            for method in order}
        write_json(record, dict(case_id=case['id'], n=case['n'], round=round_id, order=order,
                                input_sha256=case['input_sha256'], measurements=measurements))
        print(f'{index}/{len(planned)}  {case["id"]} r{round_id}  {"→".join(order)}', flush=True)
    if command(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader']):
        raise RuntimeError('Unexpected GPU compute process at experiment completion')
    write_json(out / 'complete.json', dict(verified_pairs=len(planned), elapsed_seconds=time.monotonic()-start))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('manifest', 'inputs', 'out', 'binary', 'checker'):
        parser.add_argument(f'--{arg}', required=True, type=lambda value: Path(value).resolve())
    run(parser.parse_args())
