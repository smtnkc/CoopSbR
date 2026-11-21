"""Verify a complete fused-update main run and render its paired comparison."""
import argparse
import csv
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path
from statistics import median

from fused_update_pilot import MAIN_METHODS, LABELS, load_cases, write_csv, ROOT

COMPARISONS = {
    'Graph / four barriers': ('graph', 'baseline'),
    'Graph / full copy': ('graph', 'full'),
    'Graph / changed intervals': ('graph', 'changed'),
    'Four barriers / full copy': ('baseline', 'full'),
    'Four barriers / changed intervals': ('baseline', 'changed'),
    'Full copy / changed intervals': ('full', 'changed'),
}
METRICS = ('sort_ms', 'end_to_end_ms')
DISPLAY = {
    'graph': 'Conditional CUDA Graph',
    'baseline': 'Cooperative · 4 barriers',
    'full': 'Fused full copy · 3 barriers',
    'changed': 'Fused changed intervals · 3 barriers',
}


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(run):
    require((run / 'exit-status').read_text().strip() == '0', 'Run did not finish successfully')
    metadata = json.loads((run / 'provenance.json').read_text())
    pilot = json.loads((ROOT / 'reports/fused-update-pilot-20261120/provenance.json').read_text())
    for field in ('solver_sha256', 'checker_sha256'):
        require(metadata[field] == pilot[field], f'Unexpected binary hash: {field}')
    require(metadata['split'] == 'main' and metadata['methods'] == list(MAIN_METHODS)
            and metadata['verified_calls'] == 1216, 'Unexpected declared protocol')
    known = {row['id']: (row, file, trace_sha) for row, file, trace_sha in load_cases(main=True)}
    raw = [json.loads(line) for line in (run / 'measurements.jsonl').read_text().splitlines()]
    require(len(raw) == 1216, 'Incomplete verified measurements')
    samples = defaultdict(list)
    blocks = defaultdict(set)
    for row in raw:
        case, _, trace_hash = known[row['case_id']]
        method = row['coordination']
        require(method in MAIN_METHODS and row['trace_sha256'] == trace_hash
                and row['input_sha256'] == case['sha256'], 'Unexpected trace, input or backend')
        require(row['n'] == case['n'] and row['family'] == case['family']
                and row['threads'] == 128 and row['update'] == 'full' and row['candidate'] == 'local'
                and row['reduction'] == 'scalar' and not row['debug'] and not row['instrumented'],
                'Unmatched benchmark configuration')
        require(row['grid_barriers'] == (0 if method == 'graph' else
                (4 if method == MAIN_METHODS[0] else 3)*row['reversals']+2), 'Invalid barrier count')
        if method == 'graph':
            require(row['graph_launches'] == 1 and row['graph_setup_ms'] > 0
                    and row['graph_teardown_ms'] >= 0, 'Invalid Graph setup and teardown')
        samples[row['case_id'], method].append(row)
        blocks[row['case_id']].add(row['blocks'])
    pairs = read_csv(run / 'pairs.csv')
    require(len(pairs) == 76 and {row['case_id'] for row in pairs} == set(known), 'Missing input medians')
    require(list(dict.fromkeys(row['case_id'] for row in raw)) == [row['case_id'] for row in pairs],
            'Unexpected input order in raw records')
    for index, pair in enumerate(pairs):
        case = pair['case_id']
        methods = [pair[f'method_{i}'] for i in (1, 2, 3, 4)]
        require(set(methods) == set(MAIN_METHODS), 'Unmatched methods')
        bundle = raw[index*16:(index+1)*16]
        require([r['coordination'] for r in bundle] == [method for method in methods for _ in range(4)]
                and {r['case_id'] for r in bundle} == {case}, 'Paired methods were not adjacent')
        require(blocks[case] == {int(pair['blocks'])}, 'Unmatched grid')
        for method in methods:
            measurements = samples[case, method]
            require([(r['warmup'], r['sample']) for r in measurements] ==
                    [(True, 0), (False, 0), (False, 1), (False, 2)], 'Incomplete sample sequence')
            for metric in METRICS:
                key = f'{LABELS[method]}_{metric}'
                value = median(r[metric] for r in measurements[1:])
                require(float(pair[key]) == value, 'Stored input median differs')
                pair[key] = value
        pairs[index]['n'] = int(pair['n'])
    return pairs, metadata


def percentile(ordered, fraction):
    index = (len(ordered)-1)*fraction
    lower = int(index)
    return ordered[lower]+(index-lower)*(ordered[min(lower+1, len(ordered)-1)]-ordered[lower])


def summarize(pairs):
    grouped = defaultdict(list)
    for row in pairs:
        if row['family'] != 'real':
            grouped[row['n'], row['family']].append(row)
    require(len(grouped) == 14, 'Unexpected number of synthetic cells')
    rng = random.Random(42)
    cells = []
    for (n, family), rows in sorted(grouped.items()):
        require(len(rows) == 5, 'Expected five distinct input pairs per synthetic cell')
        boot = [rng.choices(range(len(rows)), k=len(rows)) for _ in range(10000)]
        for name, (reference, method) in COMPARISONS.items():
            for metric in METRICS:
                ratios = [r[f'{reference}_{metric}']/r[f'{method}_{metric}'] for r in rows]
                distribution = sorted(median(ratios[i] for i in indices) for indices in boot)
                cells.append(dict(n=n, family=family, comparison=name, metric=metric,
                                  inputs=len(rows), median_ratio=median(ratios), ci95_low=percentile(distribution, .025),
                                  ci95_high=percentile(distribution, .975), input_wins=sum(x>1 for x in ratios)))
    return cells


def draw(cells, pairs, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'pdf.fonttype': 42})
    colors = {'graph': '#64748b', 'baseline': '#2563a9', 'full': '#bb5115', 'changed': '#087f6d'}
    markers = {'baseline': 'o', 'full': 's', 'changed': 'D'}
    indices = {method: f'Graph / {label}' for method, label in
               [('baseline', 'four barriers'), ('full', 'full copy'), ('changed', 'changed intervals')]}
    fig = plt.figure(figsize=(12.5, 8.2), layout='constrained')
    layout = fig.add_gridspec(2, 2, height_ratios=[1, 1])
    upper = [fig.add_subplot(layout[0, i]) for i in range(2)]
    real_ax = fig.add_subplot(layout[1, :])
    tick_sizes = sorted({r['n'] for r in cells})
    plotted = [r for r in cells if r['metric'] == 'end_to_end_ms' and r['comparison'] in indices.values()]
    high = max(1.60, max(r['ci95_high'] for r in plotted)+.06)
    low = min(.98, min(r['ci95_low'] for r in plotted)-.03)
    handles = {}
    for ax, family, title in zip(upper, ('uniform', 'semi'), ('A   Uniform permutations', 'B   Semi-random · k = 64')):
        handles['graph'] = ax.axhline(1, color=colors['graph'], linestyle='--', linewidth=1.4)
        for method, comparison in indices.items():
            rows = [r for r in plotted if r['family'] == family and r['comparison'] == comparison]
            values = [r['median_ratio'] for r in rows]
            handles[method] = ax.errorbar([r['n'] for r in rows], values,
                yerr=[[r['median_ratio']-r['ci95_low'] for r in rows],
                      [r['ci95_high']-r['median_ratio'] for r in rows]],
                color=colors[method], marker=markers[method], linewidth=1.8, markersize=5,
                elinewidth=1, capsize=2.5)
        ax.set_xscale('log', base=2)
        ax.set_xticks(tick_sizes, [f'{n:,}' for n in tick_sizes])
        ax.set_xlabel('Permutation length (markers)')
        ax.set_ylim(low, high)
        ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.2f×'))
        ax.set_title(title, loc='left', fontweight='bold')
        ax.grid(axis='y', color='#e2e8f0', linewidth=.8)
    upper[0].set_ylabel('End-to-end speedup vs. Graph')

    real = sorted([r for r in pairs if r['family'] == 'real'], key=lambda r:r['case_id'])
    for j, method in enumerate(DISPLAY):
        ratios = [r['graph_end_to_end_ms']/r[f'{method}_end_to_end_ms'] for r in real]
        real_ax.bar([i+(j-1.5)*.18 for i in range(len(real))], ratios, width=.16, color=colors[method])
    real_ax.axhline(1, color=colors['graph'], linestyle='--', linewidth=1, zorder=0)
    real_ax.set_xticks(range(len(real)), [r['case_id'].replace('real-v1-dmel-','').replace('-', ' · ')
                                       for r in real])
    real_ax.set_ylim(0, max(1.6, real_ax.get_ylim()[1]))
    real_ax.set_ylabel('End-to-end speedup vs. Graph')
    real_ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.1f×'))
    real_ax.set_title('C   Real Drosophila chromosome-arm gene orders', loc='left', fontweight='bold')
    real_ax.grid(axis='y', color='#e2e8f0', linewidth=.8)
    real_ax.set_axisbelow(True)
    for ax in (*upper, real_ax):
        ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle('Four GPU execution protocols for unsigned reversal sorting', fontsize=17, fontweight='bold')
    fig.legend([handles[m] for m in DISPLAY], list(DISPLAY.values()),
               loc='outside lower center', ncols=2, frameon=False, fontsize=10)
    for ext in ('png', 'pdf'):
        fig.savefig(out/f'gpu-protocol-comparison.{ext}', dpi=200)
    plt.close(fig)


def analyze(run, out):
    pairs, provenance = verify(run)
    cells = summarize(pairs)
    out.mkdir()
    write_csv(out/'paired-cells.csv', cells)
    for name in ('pairs.csv', 'measurements.jsonl', 'provenance.json'):
        shutil.copy2(run/name, out/name)
    draw(cells, pairs, out)
    print(f"Validated {provenance['verified_calls']} calls across {len(pairs)} input groups.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    analyze(args.run, args.out)
