#!/usr/bin/env python3
"""Validate saved permutations, construction traces, and biological gene mappings."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(base,name):
    path=(base/name).resolve()
    if not path.is_relative_to(base.resolve()):
        raise ValueError('Published corpus paths must stay inside their directory')
    return path


def check_mapping(path,values,provenance):
    with path.open() as f:rows=list(csv.DictReader(f,delimiter='\t'))
    if len(rows)!=len(values):raise ValueError('Mapping length mismatch')
    for key in ('label','reference_gene','query_gene'):
        if len({r[key] for r in rows})!=len(rows):raise ValueError('Non-bijective gene mapping')
    reference=sorted(rows,key=lambda r:(int(r['reference_start']),int(r['reference_end']),r['reference_gene']))
    if [int(r['label']) for r in reference]!=list(range(1,len(values)+1)):
        raise ValueError('Reference labels disagree with gene coordinates')
    query=sorted(rows,key=lambda r:(int(r['query_start']),int(r['query_end']),r['query_gene']))
    if [int(r['label']) for r in query]!=values:raise ValueError('Permutation disagrees with query gene coordinates')
    if len({r['reference_start'] for r in rows})!=len(rows) or len({r['query_start'] for r in rows})!=len(rows):
        raise ValueError('Ambiguous coordinate start in retained mapping')
    sources=provenance['sources']
    for prefix in ('reference','query'):
        limit=sources[prefix+'_chromosome_length']
        for r in rows:
            if not 1<=int(r[prefix+'_start'])<=int(r[prefix+'_end'])<=limit:
                raise ValueError('Mapping interval outside named chromosome')
    return {prefix+'_start_ties':len(rows)-len({r[prefix+'_start'] for r in rows}) for prefix in ('reference','query')}


def validate(manifest_path):
    manifest_path=Path(manifest_path);base=manifest_path.parent
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('schema')!=1 or manifest.get('seed')!=42:raise ValueError('Unexpected manifest schema/seed')
    ids=set();synthetic_hashes=set();records=[]
    for case in manifest['cases']:
        if case['id'] in ids:raise ValueError('Duplicate case ID')
        ids.add(case['id'])
        path=inside(base,case['path'])
        if sha(path)!=case['sha256']:raise ValueError('Input checksum mismatch')
        tokens=path.read_text().split()
        if not tokens:raise ValueError('Empty input')
        n=int(tokens[0]);values=list(map(int,tokens[1:]))
        if n!=case['n'] or len(values)!=n or sorted(values)!=list(range(1,n+1)):
            raise ValueError('Invalid 1..n permutation')
        if case['family']!='real':
            if case['sha256'] in synthetic_hashes:raise ValueError('Repeated synthetic input or pilot/main leakage')
            synthetic_hashes.add(case['sha256'])
        if case['family']=='semi':
            trace_path=inside(base,case['generation_trace'])
            if sha(trace_path)!=case['generation_trace_sha256']:raise ValueError('Construction trace checksum mismatch')
            trace=json.loads(trace_path.read_text())
            if len(trace)!=case['k']:raise ValueError('Construction reversal count mismatch')
            replay=list(range(1,n+1))
            for r in trace:
                if len(r)!=2 or any(type(x)!=int for x in r) or not 0<=r[0]<r[1]<n:
                    raise ValueError('Invalid construction reversal')
                l,h=r;replay[l:h+1]=reversed(replay[l:h+1])
            if replay!=values:raise ValueError('Construction trace does not reconstruct the saved input')
        ties={}
        if case['family']=='real':
            prov_path=inside(base,case['provenance'])
            if sha(prov_path)!=case['provenance_sha256']:raise ValueError('Provenance checksum mismatch')
            provenance=json.loads(prov_path.read_text())
            ties=check_mapping(path.parent/'mapping.tsv',values,provenance)
            if sha(path.parent/'orthologs.tsv')!=provenance['orthologs_sha256']:
                raise ValueError('Orthology input changed')
        augmented=[0]+values+[n+1]
        bp=sum(abs(a-b)!=1 for a,b in zip(augmented,augmented[1:]))
        records.append(dict(id=case['id'],family=case['family'],split=case['split'],n=n,k=case.get('k'),
                            initial_breakpoints=bp,initial_strips=bp+1,**ties))
    checksums=base/'checksums.json'
    if checksums.exists():
        for name,expected in json.loads(checksums.read_text()).items():
            if sha(inside(base,name))!=expected:raise ValueError('Derived corpus checksum mismatch: '+name)
    return dict(schema=1,valid=True,cases=len(records),pilot_cases=sum(r['split']=='pilot' for r in records),
                main_cases=sum(r['split']=='main' for r in records),real_cases=sum(r['family']=='real' for r in records),
                instances=records)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path)
    a=p.parse_args();result=validate(a.manifest)
    text=json.dumps(result,indent=2,sort_keys=True)+'\n'
    if a.output:a.output.write_text(text)
    print(json.dumps({key:value for key,value in result.items() if key!='instances'}))

if __name__=='__main__':main()
