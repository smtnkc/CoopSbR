#!/usr/bin/env python3
"""Convert annotated gene orders and a supplied orthology table to one permutation.

Does not infer orthology from sequence or infer chromosome correspondence.
"""
import argparse
import csv
import hashlib
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def genes(path):
    records = defaultdict(list)
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as f:
        for line in f:
            if line.startswith('##FASTA'):
                break
            if line.startswith('#') or not line.strip():
                continue
            columns = line.rstrip('\n').split('\t')
            if len(columns) != 9:
                raise ValueError('Expected nine GFF3 columns')
            if columns[2] != 'gene':
                continue
            attrs = dict(x.split('=', 1) for x in columns[8].split(';') if '=' in x)
            if 'ID' not in attrs:
                raise ValueError('GFF3 gene without ID')
            start, end = int(columns[3]), int(columns[4])
            if start < 1 or end < start:
                raise ValueError('Invalid GFF3 coordinates')
            identifier = unquote(attrs.get('gene_id', attrs['ID']))
            if 'gene_id' not in attrs and identifier.startswith('gene:'):
                identifier = identifier[5:]
            records[identifier].append((columns[0], start, end, columns[6]))
    return records



def drop_start_ties(matches):
    ref_starts=Counter((r[2][0],r[2][1]) for r in matches)
    query_starts=Counter((r[3][0],r[3][1]) for r in matches)
    retained=[];rejected=[]
    for a,b,ref,qry in matches:
        if ref_starts[(ref[0],ref[1])]>1 or query_starts[(qry[0],qry[1])]>1:
            rejected.append(dict(reference_gene=a,query_gene=b,reason='ambiguous_coordinate_start'))
        else:retained.append((a,b,ref,qry))
    return retained,rejected


def prepare(reference, query, orthologs, ref_chrom, query_chrom, out, minimum, sources):
    for key in ('reference_assembly', 'query_assembly', 'orthology_source'):
        if not isinstance(sources.get(key), str) or not sources[key].strip():
            raise ValueError(f'Missing source provenance: {key}')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Output directory must be empty')
    ref, qry = genes(reference), genes(query)
    with Path(orthologs).open() as f:
        reader = csv.DictReader(f, delimiter='\t')
        if not {'reference_gene', 'query_gene'}.issubset(reader.fieldnames or []):
            raise ValueError('Orthology TSV needs reference_gene and query_gene columns matching GFF3 IDs')
        pairs = [(r['reference_gene'], r['query_gene']) for r in reader]
    rc, qc = Counter(a for a,b in pairs), Counter(b for a,b in pairs)
    kept, rejected = [], []
    for a, b in pairs:
        reason = None
        if not a or not b:
            reason = 'missing_id'
        elif rc[a] != 1 or qc[b] != 1:
            reason = 'non_one_to_one_table'
        elif len(ref[a]) != 1 or len(qry[b]) != 1:
            reason = 'missing_or_duplicate_annotation'
        elif ref[a][0][0] != ref_chrom or qry[b][0][0] != query_chrom:
            reason = 'outside_selected_chromosome'
        if reason:
            rejected.append(dict(reference_gene=a, query_gene=b, reason=reason))
        else:
            kept.append((a,b,ref[a][0],qry[b][0]))
    before_ties=len(kept)
    kept,tied=drop_start_ties(kept)
    rejected.extend(tied)
    if len(kept) < minimum:
        raise ValueError(f'Only {len(kept)} retained markers; eligibility requires {minimum}')
    # Starts are now unique; the complete sort keys remain deterministic.
    reference_order = sorted(kept, key=lambda x:(x[2][1],x[2][2],x[0]))
    labels = {r[0]:i+1 for i,r in enumerate(reference_order)}
    query_order = sorted(kept, key=lambda x:(x[3][1],x[3][2],x[1]))
    values = [labels[r[0]] for r in query_order]
    path = out/'permutation.txt'
    path.write_text(f'{len(values)}\n'+' '.join(map(str,values))+'\n')
    with (out/'mapping.tsv').open('w') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(['label','reference_gene','query_gene','reference_start','reference_end','query_start','query_end','reference_strand','query_strand'])
        for a,b,r,q in reference_order:
            w.writerow([labels[a],a,b,r[1],r[2],q[1],q[2],r[3],q[3]])
    (out/'rejected.json').write_text(json.dumps(rejected,indent=2)+'\n')
    provenance = dict(sources=sources,reference_gff_sha256=sha(reference),query_gff_sha256=sha(query),
                      orthologs_sha256=sha(orthologs),reference_chromosome=ref_chrom,
                      query_chromosome=query_chrom,orientation='ignored unsigned model',
                      minimum_markers=minimum,retained=len(values),rejected=len(rejected),
                      coordinate_tie_policy='exclude all pairs sharing a reference or query start',
                      coordinate_tie_removed=before_ties-len(kept))
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    # Label is based on content, not a machine-specific path.
    case = dict(id='real-'+sha(path)[:16]+'-'+sha(out/'provenance.json')[:8],split='real',family='real',n=len(values),k=None,
                path=path.name,sha256=sha(path),provenance='provenance.json',
                provenance_sha256=sha(out/'provenance.json'))
    (out/'manifest.json').write_text(json.dumps(dict(schema=1,seed=42,cases=[case]),indent=2)+'\n')
    return provenance


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('reference-gff','query-gff','orthologs','out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--reference-chromosome', required=True)
    p.add_argument('--query-chromosome', required=True)
    p.add_argument('--sources', type=Path, required=True, help='JSON: reference_assembly, query_assembly, orthology_source')
    p.add_argument('--min-markers', type=int, default=1024)
    a = p.parse_args()
    if a.min_markers < 1:
        p.error('Minimum marker count must be positive')
    print(json.dumps(prepare(a.reference_gff,a.query_gff,a.orthologs,
                            a.reference_chromosome,a.query_chromosome,a.out,a.min_markers,json.loads(a.sources.read_text()))))


if __name__ == '__main__':
    main()
