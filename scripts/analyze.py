#!/usr/bin/env python3
"""Export verified measurements only; do not pool timing repeats as input samples."""
import argparse
import csv
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from campaign import latest


def quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    p = (len(ordered)-1)*q
    lo = int(p)
    return ordered[lo]+(ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(p-lo)


def write_csv(path, rows, columns):
    with path.open('w') as f:
        writer = csv.DictWriter(f, lineterminator='\n', fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def analyze(campaign, out, stage, plots=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Use a new output directory')
    config = json.loads((campaign/'budget.json').read_text())
    expected = config['pilot' if stage == 'pilot' else 'main']['repetitions']
    records = [r for r in latest(campaign).values() if r.get('stage') == stage]
    groups = defaultdict(list)
    for r in records:
        if r['status'] == 'verified' and not r['warmup'] and not r.get('instrumented'):
            groups[(r['case_id'],r['variant'])].append(r)
    good_jobs = {r['job'] for r in records if r.get('event')=='batch' and r['status']=='ok'}
    if any(r['status'] in ('correctness_failed','trace_mismatch') for r in records):
        raise ValueError('Correctness failure in campaign; do not export performance claims')
    cases = []
    for (case_id, variant), rows in sorted(groups.items()):
        r = rows[0]
        if len({v['trace_sha256'] for v in rows}) != 1:
            raise ValueError('Trace instability')
        cases.append(dict(case_id=case_id,variant=variant,family=r['family'],n=r['n'],k=r['k'],
            samples=len(rows),protocol_complete=len(rows)==expected and all(v['job'] in good_jobs for v in rows),reversals=r['reversals'],
            sort_ms=statistics.median(v['sort_ms'] for v in rows),
            end_to_end_ms=statistics.median(v['end_to_end_ms'] for v in rows),
            allocated_bytes=max(v['allocated_bytes'] for v in rows),
            kernel_launches=r['kernel_launches'],grid_barriers=r['grid_barriers'],
            updated_elements=r['updated_elements'],summary_elements=r.get('summary_elements',0),
            candidate_elements=r['candidate_elements'],candidate_copy_elements=r.get('candidate_copy_elements',0)))
    columns=['case_id','variant','family','n','k','samples','protocol_complete','reversals','sort_ms',
             'end_to_end_ms','allocated_bytes','kernel_launches','grid_barriers','updated_elements',
             'summary_elements','candidate_elements','candidate_copy_elements']
    write_csv(out/'per-input.csv',cases,columns)
    pairs = []
    index = {(r['case_id'],r['variant']):r for r in cases if r['protocol_complete']}
    for (case_id,variant), a in sorted(index.items()):
        if variant != 'GPU-FULL' or (case_id,'GPU-INC') not in index:
            continue
        b = index[(case_id,'GPU-INC')]
        if a['reversals'] != b['reversals'] or b['sort_ms'] <= 0 or b['end_to_end_ms'] <= 0:
            raise ValueError('Invalid paired result')
        pairs.append(dict(case_id=case_id,family=a['family'],n=a['n'],k=a['k'],
                          sorting_improvement=a['sort_ms']/b['sort_ms'],
                          end_to_end_improvement=a['end_to_end_ms']/b['end_to_end_ms']))
    write_csv(out/'paired.csv',pairs,['case_id','family','n','k','sorting_improvement','end_to_end_improvement'])
    cell_pairs = defaultdict(list)
    for r in pairs:
        # Each biological input remains a separate row, never a population of timing repeats.
        key=(r['family'],r['n'],r['k'],r['case_id'] if r['family']=='real' else '')
        cell_pairs[key].append(r['sorting_improvement'])
    rng = random.Random(42)
    cells=[]
    for (family,n,k,case_id),values in sorted(cell_pairs.items(),key=lambda x:str(x[0])):
        ci_low=ci_high=None
        if family!='real' and len(values)>=5:
            boot=[statistics.median(rng.choices(values,k=len(values))) for _ in range(10000)]
            ci_low,ci_high=quantile(boot,.025),quantile(boot,.975)
        cells.append(dict(family=family,n=n,k=k,case_id=case_id,input_pairs=len(values),
                          median=statistics.median(values),q25=quantile(values,.25),q75=quantile(values,.75),
                          ci95_low=ci_low,ci95_high=ci_high))
    write_csv(out/'cells.csv',cells,['family','n','k','case_id','input_pairs','median','q25','q75','ci95_low','ci95_high'])
    summary=dict(stage=stage,pilot_only=stage=='pilot',verified_input_variants=len(cases),complete_input_variants=len(index),
                 paired_inputs=len(pairs),status_counts=dict(Counter(r['status'] for r in records)),
                 incomplete_input_variants=sum(not r['protocol_complete'] for r in cases),
                 note='Pilot results are feasibility measurements, not paper performance claims.' if stage=='pilot' else
                      'Only verified complete pairs enter improvement summaries; see coverage and missing cases.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if plots and cases:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        for family in sorted({r['family'] for r in cases}):
            if family=='real':
                continue
            for k in sorted({r['k'] for r in cases if r['family']==family},key=str):
                fig,ax=plt.subplots(figsize=(6,4))
                for variant in sorted({r['variant'] for r in cases}):
                    by_n=defaultdict(list)
                    for r in cases:
                        if r['protocol_complete'] and r['family']==family and r['k']==k and r['variant']==variant:
                            by_n[r['n']].append(r['sort_ms'])
                    if by_n:
                        ns=sorted(by_n)
                        ax.plot(ns,[statistics.median(by_n[n]) for n in ns],marker='o',label=variant)
                ax.set(xscale='log',yscale='log',xlabel='Permutation length',ylabel='Sorting time (ms)',
                       title=f'{stage}: {family}, k={k}')
                ax.legend();fig.tight_layout()
                for suffix in ('png','pdf'):
                    fig.savefig(out/f'{family}-k{k}.{suffix}',dpi=180)
                plt.close(fig)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--stage',choices=('pilot','synthetic','real','ablation','diagnostics'),required=True)
    p.add_argument('--plots',action='store_true')
    a=p.parse_args()
    print(json.dumps(analyze(a.campaign,a.out,a.stage,a.plots)))
