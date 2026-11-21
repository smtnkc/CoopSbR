#!/usr/bin/env python3
"""One seed-42 stream generates disjoint pilot/main corpora in recorded order."""
import argparse
import hashlib
import json
import platform
import random
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(out, sizes, ks, instances, pilot_instances):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Output directory must be empty; corpora are immutable')
    rng = random.Random(42)
    cases = []
    seen = set()
    for family in ('uniform', 'semi'):
        for n in sizes:
            for k in ([None] if family == 'uniform' else ks):
                for split, count in (('pilot', pilot_instances), ('main', instances)):
                    for instance in range(count):
                        for attempt in range(1000):
                            values = list(range(1, n + 1))
                            trace = []
                            if family == 'uniform':
                                rng.shuffle(values)
                            else:
                                for _ in range(k):
                                    l, r = sorted(rng.sample(range(n), 2))
                                    values[l:r+1] = reversed(values[l:r+1])
                                    trace.append([l, r])
                            data = f'{n}\n' + ' '.join(map(str, values)) + '\n'
                            digest = hashlib.sha256(data.encode()).hexdigest()
                            if digest not in seen:
                                seen.add(digest)
                                break
                        else:
                            raise ValueError('Cannot make distinct corpus at these parameters')
                        key = f'{split}-{family}-n{n}-k{k if k is not None else "na"}-{instance:03d}'
                        path = out / f'{key}.txt'
                        path.write_text(data)
                        record = dict(id=key, split=split, family=family, n=n, k=k,
                                      instance=instance, path=path.name, sha256=digest)
                        if family == 'semi':
                            trace_path = out / f'{key}.generation.json'
                            trace_path.write_text(json.dumps(trace) + '\n')
                            record.update(generation_trace=trace_path.name,
                                          generation_trace_sha256=sha(trace_path))
                        cases.append(record)
    manifest = dict(schema=1, seed=42, generator='python-random-MT19937',
                    python_version=platform.python_version(), sizes=sizes, ks=ks,
                    instances=instances, pilot_instances=pilot_instances, cases=cases)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--sizes', type=int, nargs='+', default=[1024, 4096, 16384])
    p.add_argument('--k', type=int, nargs='+', default=[4, 64, 1024])
    p.add_argument('--instances', type=int, default=10)
    p.add_argument('--pilot-instances', type=int, default=2)
    a = p.parse_args()
    if min(a.sizes) < 2 or min(a.k) < 1 or a.instances < 0 or a.pilot_instances < 0:
        p.error('Sizes >= 2, k >= 1, and nonnegative counts required')
    if len(set(a.sizes)) != len(a.sizes) or len(set(a.k)) != len(a.k):
        p.error('Duplicate size/k values are not allowed')
    result = generate(a.out, sorted(a.sizes), sorted(a.k), a.instances, a.pilot_instances)
    print(json.dumps(dict(cases=len(result['cases']), seed=42, manifest=str(a.out/'manifest.json'))))


if __name__ == '__main__':
    main()
