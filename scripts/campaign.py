#!/usr/bin/env python3
"""Bounded, checkpointed experiment execution; no shell or credential handling."""
import argparse
import fcntl
import hashlib
import json
import os
import random
import selectors
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'experiments/budget.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    temp = path.with_suffix('.tmp')
    with temp.open('w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def latest(directory):
    rows = {}
    path = directory / 'results.jsonl'
    if path.exists():
        with path.open() as f:
            for line in f:
                if not line.endswith('\n'):
                    break
                row = json.loads(line)
                rows[row['id']] = row
    return rows


class Budget:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.lock = (self.directory / '.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.path = self.directory / 'state.json'
        self.state = json.loads(self.path.read_text())
        self.config = json.loads((self.directory / 'budget.json').read_text())
        if self.state['config_sha256'] != sha(self.directory / 'budget.json'):
            raise ValueError('Campaign configuration changed')
        if self.state['hours'] not in (24, 48) or self.config['hard_limit_hours'] != 48:
            raise ValueError('Invalid reservation limit')
        if self.state['host'] != socket.gethostname():
            raise ValueError('Resume execution on the original workstation')
        log = self.directory/'results.jsonl'
        if log.exists():
            data = log.read_bytes()
            if data and not data.endswith(b'\n'):
                end = data.rfind(b'\n')+1
                (self.directory/'interrupted-tail.bin').write_bytes(data[end:])
                with log.open('r+b') as f:
                    f.truncate(end)
        self.caps = self.config['stage_hours'][str(self.state['hours'])]
        if any(v <= 0 for v in self.caps.values()) or sum(self.caps.values()) != self.state['hours']:
            raise ValueError('Stage caps do not sum to the reservation')

    def close(self):
        lock = getattr(self, 'lock', None)
        if lock is not None and not lock.closed:
            lock.close()

    def __del__(self):
        self.close()

    def elapsed(self):
        return max(self.state['elapsed_seconds'], time.time()-self.state['start_wall'],
                   time.monotonic()-self.state['start_monotonic'])

    def checkpoint(self):
        self.state['elapsed_seconds'] = self.elapsed()
        save(self.path, self.state)

    def enter(self, stage):
        if stage not in self.caps:
            raise ValueError('Unknown stage')
        self.state['stages'].setdefault(stage, self.elapsed())
        self.checkpoint()

    def remaining(self, stage):
        elapsed = self.elapsed()
        reserve = 0 if stage == 'buffer' else self.caps['buffer'] * 3600
        remaining=min(self.state['hours']*3600-elapsed-reserve,
                      self.caps[stage]*3600-(elapsed-self.state['stages'][stage]))
        if 'wall_limit_seconds' in self.state:
            short_reserve=0 if stage=='buffer' else self.state['wall_reserve_seconds']
            remaining=min(remaining,self.state['wall_limit_seconds']-elapsed-short_reserve)
        return max(0,remaining)

    def append(self, row):
        row['campaign_elapsed_seconds'] = self.elapsed()
        with (self.directory/'results.jsonl').open('a') as f:
            f.write(json.dumps(row, sort_keys=True)+'\n')
            f.flush()
            os.fsync(f.fileno())
        self.checkpoint()


def initialize(directory, hours, wall_minutes=None):
    if hours not in (24, 48):
        raise ValueError('Reservation must be 24 or 48 hours')
    if wall_minutes is not None and not 1 <= wall_minutes <= hours*60:
        raise ValueError('Invalid short wall-clock limit')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError('Campaign directory must be empty; never reinitialize a campaign')
    config = json.loads(CONFIG.read_text())
    save(directory/'budget.json', config)
    state=dict(schema=1, hours=hours, start_wall=time.time(),
         start_monotonic=time.monotonic(), elapsed_seconds=0, stages={},
         host=socket.gethostname(), config_sha256=sha(directory/'budget.json'), pinned={})
    if wall_minutes is not None:
        state.update(wall_limit_seconds=wall_minutes*60,wall_reserve_seconds=min(900,wall_minutes*6))
    save(directory/'state.json',state)
    (directory/'traces').mkdir()
    provenance = {}
    for name, command in {
        'commit': ['git','-C',str(ROOT),'rev-parse','HEAD'],
        'compiler': ['/usr/bin/g++','--version'],
        'cuda_compiler': ['nvcc','--version'],
        'gpu': ['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'],
    }.items():
        try:
            r = subprocess.run(command, capture_output=True, text=True, timeout=5)
            provenance[name] = r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            provenance[name] = None
    dirty = subprocess.run(['git','-C',str(ROOT),'diff','--quiet'], capture_output=True)
    provenance['tracked_source_dirty'] = dirty.returncode != 0
    provenance['python'] = sys.version
    provenance['environment_lock_sha256'] = sha(ROOT/'environment/linux-64.explicit.txt') if (ROOT/'environment/linux-64.explicit.txt').exists() else None
    save(directory/'provenance.json', provenance)
    print(json.dumps(dict(campaign=str(directory), hours=hours, started=True)))


def terminate(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=1)
    except ProcessLookupError:
        pass


def capture(command, budget, stage, call_timeout, output, stderr_path, on_row=None):
    """Reset the per-call watchdog only on complete JSON output from a solve."""
    if budget.remaining(stage) < 4:
        return [], 'budget_skip'
    rows, pending = [], b''
    watchdog = time.monotonic()+min(call_timeout, budget.remaining(stage)-3)
    process = None
    selector = None
    with stderr_path.open('wb') as errors, output.open('wb') as raw:
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                       start_new_session=True, bufsize=0)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            reason = None
            while selector.get_map():
                if budget.remaining(stage) <= 3:
                    reason = 'budget_skip'
                    break
                if time.monotonic() >= watchdog:
                    reason = 'timeout'
                    break
                for key, _ in selector.select(timeout=0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    raw.write(chunk)
                    pending += chunk
                    if len(pending) > 1024*1024:
                        raise ValueError('Oversized solver output')
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        row = json.loads(line)
                        if not isinstance(row, dict) or row.get('schema') != 1:
                            raise ValueError('Invalid solver output schema')
                        rows.append(row)
                        if on_row is not None:
                            on_row(row)
                        watchdog = time.monotonic()+min(call_timeout, max(0, budget.remaining(stage)-3))
            selector.close()
            if reason:
                terminate(process)
            else:
                process.wait(timeout=1)
                reason = 'ok' if process.returncode == 0 and not pending else 'failed'
            return rows, reason
        finally:
            if selector is not None:
                selector.close()
            if process is not None:
                terminate(process)
                process.stdout.close()


def pin(budget, key, value):
    previous = budget.state['pinned'].setdefault(key, value)
    if previous != value:
        raise ValueError(f'{key} changed; cannot mix revisions/configurations on resume')
    budget.checkpoint()


def verify(budget, stage, checker):
    records = latest(budget.directory)
    if any(r['status'] in ('correctness_failed','trace_mismatch') for r in records.values()):
        raise ValueError('Campaign contains a correctness failure')
    reference = {}
    for row in records.values():
        if row['status'] == 'verified':
            old = reference.setdefault(row['case_id'], row['trace_sha256'])
            if old != row['trace_sha256']:
                raise ValueError('Previously verified traces disagree')
    for key, row in records.items():
        if row['status'] != 'produced':
            continue
        timeout = min(60, budget.remaining(stage)-3)
        if timeout <= 0:
            break
        path = Path(row['trace_path'])
        if not path.is_file() or sha(row['input_path']) != row['input_sha256']:
            raise ValueError('Input or trace changed before verification')
        with (budget.directory/'verify.stderr').open('ab') as errors:
            p = subprocess.Popen([str(checker), row['input_path'], str(path)],
                                 stdout=subprocess.PIPE, stderr=errors, start_new_session=True)
            try:
                out, _ = p.communicate(timeout=timeout)
            except BaseException:
                terminate(p)
                raise
        if p.returncode != 0:
            row['status'] = 'correctness_failed'
            budget.append(row)
            raise ValueError('Independent reversal replay failed')
        checked = json.loads(out)
        if checked.get('verified') is not True or checked['n'] != row['n'] or checked['reversals'] != row['reversals']:
            raise ValueError('Checker/solver output mismatch')
        digest = sha(path)
        if row['case_id'] in reference and reference[row['case_id']] != digest:
            row['status'] = 'trace_mismatch'
            budget.append(row)
            raise ValueError('Trace differs between versions or repetitions')
        reference[row['case_id']] = digest
        row.update(status='verified', trace_sha256=digest)
        budget.append(row)


def forecast(budget, stage, cases, variants, protocol):
    rates = {}
    unsafe = set()
    all_rows = list(latest(budget.directory).values())
    for row in all_rows:
        if row.get('stage') != 'pilot':
            continue
        if row.get('event') == 'batch' and row['status'] in ('timeout','failed'):
            unsafe.add((row['family'], row['n'], row.get('k'), row['variant']))
        if row['status'] == 'verified':
            key = (row['family'], row['n'], row.get('k'), row['variant'])
            rates[key] = max(rates.get(key, 0), (row['end_to_end_ms']+row.get('context_ms', 0))/1000)
        elif row.get('event') == 'batch' and row['status'] == 'ok' and row.get('calls',0):
            key = (row['family'], row['n'], row.get('k'), row['variant'])
            rates[key] = max(rates.get(key, 0), row['wall_seconds']/row['calls'])
    seconds = 0
    missing = []
    for case in cases:
        for variant in variants:
            job = f'{stage}:{case["id"]}:{variant}'
            completed = sum(r.get('job') == job and r['status'] == 'verified' and not r['warmup'] for r in all_rows)
            remaining = max(0, protocol['repetitions']-completed)
            if not remaining:
                continue
            key = (case['family'], case['n'], case.get('k'), variant)
            if key not in rates or key in unsafe:
                missing.append(list(key))
            else:
                seconds += 2 * rates[key] * (protocol['warmups']+remaining)
    result = dict(stage=stage, conservative_seconds=seconds, missing_cells=missing,
                  available_seconds=budget.remaining(stage))
    result['fits'] = not missing and seconds < result['available_seconds']
    save(budget.directory/f'{stage}-forecast.json', result)
    if not result['fits']:
        raise ValueError('Main-stage forecast does not fit or has missing pilot cells; inspect forecast JSON and reduce a NEW manifest before main execution')
    return result


def run(a):
    if a.max_instances is not None and a.max_instances < 1:
        raise ValueError('max-instances must be positive')
    budget = Budget(a.campaign)
    budget.enter(a.stage)
    manifest_path = a.manifest.resolve()
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema') != 1 or manifest.get('seed') != 42:
        raise ValueError('Expected schema-1 seed-42 manifest')
    binary, checker = a.binary.resolve(), a.checker.resolve()
    binary_digest = sha(binary)
    pin(budget, 'checker_sha256', sha(checker))
    pin(budget, 'manifest:'+str(manifest_path), sha(manifest_path))
    variants = dict(budget.config['variants'], **budget.config['extra_variants'])
    experimental = {}
    definitions = getattr(a, 'experimental_variants', None)
    if definitions:
        if getattr(a, 'label', None) or getattr(a, 'reduction', None):
            raise ValueError('Choose a variant file or a single experimental label')
        definitions = definitions.resolve()
        payload = json.loads(definitions.read_text())
        if payload.get('schema')!=1 or not isinstance(payload.get('variants'),dict) or not payload['variants']:
            raise ValueError('Expected nonempty schema-1 experimental variant definitions')
        pin(budget, 'experimental_definitions:'+str(definitions), sha(definitions))
        for label, definition in payload['variants'].items():
            if (label in variants or not label.startswith('EXP-') or len(label)>48 or
                    not all(c.isascii() and (c.isalnum() or c=='-') for c in label)):
                raise ValueError('Experimental labels must be unique EXP- identifiers')
            if not isinstance(definition,dict) or set(definition)-{'base','reduction'}:
                raise ValueError('Unexpected experimental variant fields')
            base, reduction = definition.get('base'), definition.get('reduction')
            if base not in budget.config['variants'] and base not in budget.config['extra_variants']:
                raise ValueError('Unknown experimental base variant')
            if reduction not in (None,'summary','scalar') or (base=='SEQ' and reduction):
                raise ValueError('Invalid experimental reduction')
            flags = list(variants[base]) + (['--reduction',reduction] if reduction else [])
            variants[label] = flags
            experimental[label] = dict(base=base, flags=flags)
    selected = a.variants or (list(experimental) if experimental else list(budget.config['variants']))
    if len(set(selected)) != len(selected) or any(v not in variants for v in selected):
        raise ValueError('Invalid variant selection')
    label = getattr(a, 'label', None)
    reduction = getattr(a, 'reduction', None)
    if experimental:
        if any(v not in experimental for v in selected):
            raise ValueError('Only experimental labels may use the variant-file binary')
        for variant in selected:
            pin(budget, 'variant_definition:'+variant, experimental[variant])
            pin(budget, 'binary_sha256:'+variant, binary_digest)
    elif label:
        if (len(selected)!=1 or label in variants or not label.startswith('EXP-') or
                len(label)>48 or not all(c.isascii() and (c.isalnum() or c=='-') for c in label)):
            raise ValueError('Use a unique EXP- label with exactly one base variant')
        base = selected[0]
        flags = list(variants[base])
        if reduction:
            if base=='SEQ':
                raise ValueError('Reduction selection is GPU-only')
            flags += ['--reduction', reduction]
        pin(budget, 'variant_definition:'+label, dict(base=base, flags=flags))
        pin(budget, 'binary_sha256:'+label, binary_digest)
        variants[label] = flags
        selected = [label]
    else:
        if reduction:
            raise ValueError('An explicit reduction requires a new experimental label')
        pin(budget, 'binary_sha256', binary_digest)
    protocol = budget.config['pilot' if a.stage == 'pilot' else 'main']
    schedule_key = f'{a.stage}:{a.split}:'+','.join(selected)
    ids = [c['id'] for c in manifest['cases'] if c['split'] == a.split]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate case IDs')
    rng = random.Random(42)
    cells = {}
    for c in manifest['cases']:
        if c['split'] == a.split:
            cells.setdefault((c['n'], c['family'], c.get('k')), []).append(c)
    # Ascending lengths bound pilot growth; independent cells at a length are balanced.
    schedule = []
    for n in sorted({k[0] for k in cells}):
        groups = [k for k in cells if k[0] == n]
        rng.shuffle(groups)
        for group in groups:
            cases = cells[group][:a.max_instances] if a.max_instances else cells[group]
            for case in cases:
                order = selected.copy()
                rng.shuffle(order)
                schedule.extend((case, variant) for variant in order)
    if getattr(a, 'shuffle_cases', False):
        if a.stage=='pilot':
            raise ValueError('Pilot cases must retain bounded ascending-length order')
        paired={}
        for case,variant in schedule:
            paired.setdefault(case['id'],[]).append((case,variant))
        case_pairs=list(paired.values())
        rng.shuffle(case_pairs)
        schedule=[item for pair in case_pairs for item in pair]
    verify(budget, a.stage, checker)
    if a.stage != 'pilot':
        unique_cases = {c['id']: c for c, _ in schedule}
        forecast(budget, a.stage, list(unique_cases.values()), selected, protocol)
    pin(budget, schedule_key, [[c['id'], v] for c, v in schedule])
    if a.forecast_only:
        return
    blocked = set()
    for row in latest(budget.directory).values():
        if row.get('event') == 'batch' and row.get('stage') == a.stage and row['status'] in ('timeout','failed'):
            blocked.add((row['family'], row['variant']))
    for case, variant in schedule:
        records = latest(budget.directory)
        if any(r['status'] in ('correctness_failed','trace_mismatch') for r in records.values()):
            raise ValueError('Campaign has a correctness failure; inspect it before continuing')
        job = f'{a.stage}:{case["id"]}:{variant}'
        if any(r.get('job') == job and r['status'] in ('timeout','failed','budget_skip') for r in records.values()):
            continue
        completed = {r['sample'] for r in records.values() if r.get('job') == job and
                     r['status'] in ('verified','produced') and not r['warmup']}
        if len(completed) == protocol['repetitions']:
            continue
        if completed and completed != set(range(max(completed)+1)):
            raise ValueError('Non-contiguous checkpoint samples')
        if budget.remaining(a.stage) <= 4:
            break
        # After a timeout, do not keep testing larger cases of that family/version.
        if (case['family'], variant) in blocked and a.stage == 'pilot':
            continue
        path = (manifest_path.parent/case['path']).resolve()
        if sha(path) != case['sha256']:
            raise ValueError('Input checksum mismatch')
        attempt = sum(r.get('job') == job and r.get('event') == 'batch' for r in records.values())
        budget.append(dict(id=f'{job}:batch:{attempt}', job=job, event='batch', stage=a.stage,
                           case_id=case['id'], family=case['family'], n=case['n'], k=case.get('k'), variant=variant, status='running'))
        token = hashlib.sha256(job.encode()).hexdigest()[:20]+f'-a{attempt}'
        prefix = budget.directory/'traces'/token
        offset = len(completed)
        if sha(binary) != binary_digest:
            raise ValueError('Solver changed during execution')
        command = [str(binary), '--input', str(path), '--trace', str(prefix),
                   '--warmups', str(protocol['warmups']), '--repetitions', str(protocol['repetitions']-offset),
                   '--sample-offset', str(offset)] + variants[variant]
        started = time.monotonic()
        def record(row):
            if not isinstance(row.get('warmup'), bool) or not isinstance(row.get('sample'), int):
                raise ValueError('Invalid sample metadata')
            bound = protocol['warmups'] if row['warmup'] else protocol['repetitions']
            lower = 0 if row['warmup'] else offset
            if not lower <= row['sample'] < bound:
                raise ValueError('Unexpected sample index')
            if row.get('debug') or row.get('instrumented') or row.get('policy') != 'extreme-strip-v1' or row.get('n') != case['n']:
                raise ValueError('Unexpected solver result')
            trace = Path(row['trace_path']).resolve()
            if trace.parent != (budget.directory/'traces').resolve() or not trace.name.startswith(token):
                raise ValueError('Unexpected trace location')
            ident = f'{job}:warm:{attempt}:{row["sample"]}' if row['warmup'] else f'{job}:sample:{row["sample"]}'
            if ident in records:
                raise ValueError('Refusing to overwrite a completed sample')
            row.update(id=ident, job=job, stage=a.stage, case_id=case['id'], family=case['family'],
                       k=case.get('k'), variant=variant, status='produced', input_path=str(path),
                       input_sha256=case['sha256'], binary_sha256=binary_digest)
            budget.append(row)
            records[ident] = dict(row)
        rows, status = capture(command, budget, a.stage, protocol['call_timeout_seconds'],
                               budget.directory/f'{token}.stdout', budget.directory/f'{token}.stderr', record)
        expected = protocol['warmups'] + protocol['repetitions']-offset
        if status == 'ok' and len(rows) != expected:
            status = 'failed'
        verify(budget, a.stage, checker)
        budget.append(dict(id=f'{job}:batch:{attempt}', job=job, event='batch', stage=a.stage,
                           case_id=case['id'], family=case['family'], n=case['n'], k=case.get('k'),
                           variant=variant, status=status, wall_seconds=time.monotonic()-started,
                           calls=len(rows)))
        if status == 'failed':
            raise ValueError('Solver batch failed; inspect saved stderr before continuing')
        if status == 'timeout':
            blocked.add((case['family'], variant))
        print(json.dumps(dict(job=job, status=status, calls=len(rows), remaining_seconds=round(budget.remaining(a.stage),1))), flush=True)
        if status == 'budget_skip':
            break


def execute(a):
    budget = Budget(a.campaign)
    budget.enter(a.stage)
    command = a.program[1:] if a.program[:1] == ['--'] else a.program
    if not command or a.timeout <= 0:
        raise ValueError('Provide a command after -- and a positive timeout')
    timeout = min(a.timeout, budget.remaining(a.stage)-3)
    if timeout <= 0:
        raise ValueError('No budget remaining')
    ident = f'exec:{a.stage}:{time.time_ns()}'
    log = budget.directory/f'{ident.replace(":","-")}.log'
    started = time.monotonic()
    with log.open('wb') as f:
        process = subprocess.Popen(command, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            try:
                process.wait(timeout=timeout)
                status = 'ok' if process.returncode == 0 else 'failed'
            except subprocess.TimeoutExpired:
                status = 'timeout'
        finally:
            terminate(process)
    budget.append(dict(id=ident, event='command', stage=a.stage, status=status,
                       command=command, wall_seconds=time.monotonic()-started))
    print(log.read_text(errors='replace')[-12000:])
    if status != 'ok':
        raise ValueError(f'Command ended with {status}; see saved log')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    q = sub.add_parser('init')
    q.add_argument('--campaign', type=Path, required=True)
    q.add_argument('--hours', type=int, choices=(24,48), default=24)
    q.add_argument('--wall-minutes', type=int, help='Additional persistent short-study deadline')
    q = sub.add_parser('run')
    q.add_argument('--campaign', type=Path, required=True)
    q.add_argument('--manifest', type=Path, required=True)
    q.add_argument('--stage', choices=('pilot','synthetic','real','ablation','diagnostics'), required=True)
    q.add_argument('--split', choices=('pilot','main','real'), required=True)
    q.add_argument('--binary', type=Path, default=ROOT/'build/cuda/coopsbr')
    q.add_argument('--checker', type=Path, default=ROOT/'build/cuda/coopsbr-check')
    q.add_argument('--variants', nargs='+')
    q.add_argument('--experimental-variants', type=Path, help='Pinned additive variant definitions for interleaved execution')
    q.add_argument('--label', help='Unique EXP- label for one separately pinned binary/configuration')
    q.add_argument('--reduction', choices=('summary','scalar'))
    q.add_argument('--shuffle-cases', action='store_true', help='Shuffle main input pairs across sizes while keeping methods adjacent')
    q.add_argument('--max-instances', type=int)
    q.add_argument('--forecast-only', action='store_true')
    q = sub.add_parser('verify')
    q.add_argument('--campaign', type=Path, required=True)
    q.add_argument('--checker', type=Path, default=ROOT/'build/cuda/coopsbr-check')
    q = sub.add_parser('exec')
    q.add_argument('--campaign', type=Path, required=True)
    q.add_argument('--stage', choices=('checks','diagnostics','buffer'), required=True)
    q.add_argument('--timeout', type=float, default=180)
    q.add_argument('program', nargs=argparse.REMAINDER)
    q = sub.add_parser('status')
    q.add_argument('--campaign', type=Path, required=True)
    a = p.parse_args()
    if a.command == 'init':
        initialize(a.campaign, a.hours, a.wall_minutes)
    elif a.command == 'run':
        run(a)
    elif a.command == 'exec':
        execute(a)
    elif a.command == 'verify':
        b = Budget(a.campaign)
        b.enter('buffer')
        pin(b, 'checker_sha256', sha(a.checker))
        verify(b, 'buffer', a.checker.resolve())
    else:
        state = json.loads((a.campaign/'state.json').read_text())
        elapsed = max(state['elapsed_seconds'], time.time()-state['start_wall'])
        limit=min(state['hours']*3600,state.get('wall_limit_seconds',state['hours']*3600))
        print(json.dumps(dict(elapsed_seconds=elapsed, limit_hours=limit/3600,
                             remaining_seconds=max(0,limit-elapsed)), indent=2))


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError('terminated')))
    try:
        main()
    except (OSError,ValueError,RuntimeError,InterruptedError,subprocess.SubprocessError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
