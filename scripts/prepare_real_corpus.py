#!/usr/bin/env python3
"""Rebuild the fixed Ensembl-63 chromosome-arm corpus from checksum-pinned files."""
import argparse
import csv
import gzip
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit
from prepare_genomes import genes, prepare, drop_start_ties

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,data):
    Path(path).write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')


def fetch(record,raw):
    name=record['filename']
    if Path(name).name!=name:
        raise ValueError('Source filename must be a basename')
    target=raw/name
    if target.exists():
        if sha(target)!=record['sha256']:
            raise ValueError(f'Existing source differs from pinned checksum: {name}')
        return target
    url=urlsplit(record['url'])
    if url.scheme!='https' or url.hostname not in ('ftp.ebi.ac.uk','api.ncbi.nlm.nih.gov'):
        raise ValueError('Unexpected download source')
    temp=target.with_suffix(target.suffix+'.part')
    subprocess.run(['curl','--fail','--location','--retry','2','--max-time','180','--output',str(temp),record['url']],check=True)
    if sha(temp)!=record['sha256']:
        raise ValueError(f'Download checksum mismatch: {name}')
    temp.replace(target)
    return target


def collect_homologies(paths,reference,targets):
    """Both species files are needed: provider dumps are complementary subsets."""
    result={target:{} for target in targets}
    duplicates=Counter()
    for path in paths:
        with gzip.open(path,'rt') as f:
            for row in csv.DictReader(f,delimiter='\t'):
                if row['species']==reference and row['homology_species'] in targets:
                    target=row['homology_species'];a=row['gene_stable_id'];b=row['homology_gene_stable_id']
                elif row['homology_species']==reference and row['species'] in targets:
                    target=row['species'];a=row['homology_gene_stable_id'];b=row['gene_stable_id']
                else:
                    continue
                key=(a,b)
                value=dict(reference_gene=a,query_gene=b,homology_type=row['homology_type'],
                           is_high_confidence=row['is_high_confidence'],homology_id=row['homology_id'],
                           goc_score=row.get('goc_score'),wga_coverage=row.get('wga_coverage'))
                if key in result[target]:
                    if result[target][key]!=value:
                        raise ValueError('Conflicting duplicate homology')
                    duplicates[target]+=1
                result[target][key]=value
    return result,duplicates


def strict_pairs(relations,reference_genes,query_genes):
    rc=Counter(a for a,b in relations)
    qc=Counter(b for a,b in relations)
    kept=[];rejected=[]
    for (a,b),row in sorted(relations.items()):
        reason=None
        if row['homology_type']!='ortholog_one2one':reason='not_ortholog_one2one'
        elif row['is_high_confidence']!='1':reason='not_provider_high_confidence'
        elif rc[a]!=1 or qc[b]!=1:reason='ambiguous_cross_species_relationship'
        elif len(reference_genes.get(a,[]))!=1 or len(query_genes.get(b,[]))!=1:reason='missing_or_duplicate_gene_locus'
        if reason:rejected.append(dict(row,reason=reason))
        else:kept.append(row)
    return kept,rejected


def annotation_metadata(path,assembly,entries):
    regions={};build=None
    with gzip.open(path,'rt') as f:
        for line in f:
            if line.startswith('##sequence-region'):
                _,name,start,end=line.split()
                bounds=(int(start),int(end))
                if name in regions and regions[name]!=bounds:raise ValueError('Conflicting sequence bounds')
                regions[name]=bounds
            elif line.startswith('#!genome-build-accession '):build=line.split()[-1]
    if build!=assembly:raise ValueError('Annotation does not match pinned assembly accession')
    for loci in entries.values():
        for chrom,start,end,strand in loci:
            if chrom not in regions or not regions[chrom][0]<=start<=end<=regions[chrom][1]:
                raise ValueError('Gene outside declared sequence bounds')
    return regions


def sequence_map(path,assembly):
    data=json.loads(path.read_text())
    result={}
    for row in data['reports']:
        if row['assembly_accession']!=assembly:raise ValueError('NCBI sequence report assembly mismatch')
        if row.get('role')=='assembled-molecule':
            name=row['chr_name']
            if name in result:raise ValueError('Ambiguous chromosome name')
            result[name]=row
    return result


def write_pairs(path,rows):
    columns=['reference_gene','query_gene','homology_type','is_high_confidence','homology_id','goc_score','wga_coverage']
    with path.open('w') as f:
        writer=csv.DictWriter(f,fieldnames=columns,delimiter='\t',lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def build(lock_path,raw,out):
    lock_path=Path(lock_path);lock=json.loads(lock_path.read_text());raw=Path(raw);out=Path(out)
    if lock['schema']!=1 or lock['ensembl_genomes_release']!=63:raise ValueError('Unexpected source lock')
    raw.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise ValueError('Derived output must be empty')
    files={key:fetch(value,raw) for key,value in lock['files'].items()}
    species=lock['species'];gene_sets={};regions={};sequences={}
    for name,info in species.items():
        gene_sets[name]=genes(files[name+'_gff'])
        regions[name]=annotation_metadata(files[name+'_gff'],info['assembly'],gene_sets[name])
        sequences[name]=sequence_map(files[name+'_sequences'],info['assembly'])
    targets={species[name]['ensembl_name']:name for name in ('dsim','dyak')}
    relations,duplicate_counts=collect_homologies([files[name+'_homologies'] for name in species],
                                                  species['dmel']['ensembl_name'],targets)
    cases=[];candidates=[];audit={};matrix=[]
    (out/'pairs').mkdir()
    for target,short in targets.items():
        kept,rejected=strict_pairs(relations[target],gene_sets['dmel'],gene_sets[short])
        if not kept:raise ValueError('No reliable one-to-one gene matches')
        write_pairs(out/'pairs'/f'dmel-{short}.tsv',kept)
        save(out/'pairs'/f'dmel-{short}.rejected.json',rejected)
        audit[short]=dict(reported_pairs=len(relations[target]),duplicate_rows=duplicate_counts[target],
                          strict_retained=len(kept),rejection_counts=dict(Counter(r['reason'] for r in rejected)))
        by_reference=defaultdict(list);counts=Counter()
        for row in kept:
            a=row['reference_gene'];b=row['query_gene']
            ref=gene_sets['dmel'][a][0];qry=gene_sets[short][b][0]
            by_reference[ref[0]].append(row)
            counts[(ref[0],qry[0])]+=1
        for (ref_chrom,query_chrom),count in sorted(counts.items()):
            matrix.append(dict(comparison=f'dmel-{short}',reference_chromosome=ref_chrom,
                               query_sequence=query_chrom,orthologs=count))
        eligible=[]
        for arm in lock['selection']['candidate_arms']:
            q=sequences[short].get(arm);r=sequences['dmel'].get(arm)
            if q is None or r is None:raise ValueError('Missing official named chromosome correspondence')
            query_chrom=q['genbank_accession']
            if regions['dmel'].get(arm)!=(1,r['length']) or regions[short].get(query_chrom)!=(1,q['length']):
                raise ValueError('Ensembl sequence lengths disagree with NCBI chromosome report')
            total=len(by_reference[arm]);same_arm=counts[(arm,query_chrom)]
            matching=[(row['reference_gene'],row['query_gene'],gene_sets['dmel'][row['reference_gene']][0],gene_sets[short][row['query_gene']][0])
                      for row in by_reference[arm] if gene_sets[short][row['query_gene']][0][0]==query_chrom]
            unambiguous,tied=drop_start_ties(matching)
            n=len(unambiguous)
            fidelity=same_arm/total if total else 0
            good=n>=lock['selection']['minimum_markers'] and fidelity>=lock['selection']['minimum_arm_fidelity']
            record=dict(comparison=f'dmel-{short}',arm=arm,query_sequence=query_chrom,
                        reference_arm_orthologs=total,same_arm_before_coordinate_filter=same_arm,coordinate_tie_removed=len(tied),
                        retained_markers=n,arm_fidelity=fidelity,eligible=good,
                        selected=False,reason='eligible' if good else 'size_or_arm_correspondence')
            candidates.append(record)
            if good:eligible.append(record)
        chosen=sorted(eligible,key=lambda r:(-r['retained_markers'],r['arm']))[:lock['selection']['arms_per_comparison']]
        if not chosen:raise ValueError('No eligible arms for a required species comparison')
        for record in eligible:
            if record not in chosen:record['reason']='declared_case_count_budget'
        for record in chosen:
            record['selected']=True;record['reason']='selected_by_marker_count_before_sorting'
            arm=record['arm'];folder=f'dmel-{short}-{arm}';directory=out/folder
            directory.mkdir()
            arm_table=directory/'orthologs.tsv'
            write_pairs(arm_table,by_reference[arm])
            sources=dict(reference_assembly=species['dmel']['assembly'],query_assembly=species[short]['assembly'],
                         reference_annotation=species['dmel']['annotation'],query_annotation=species[short]['annotation'],
                         orthology_source=lock['orthology_description'],source_lock_sha256=sha(lock_path),
                         ensembl_genomes_release=63,ensembl_compara_release=116,
                         homology_files=[lock['files'][name+'_homologies']['url'] for name in species],
                         reference_annotation_url=lock['files']['dmel_gff']['url'],
                         query_annotation_url=lock['files'][short+'_gff']['url'],
                         selection=lock['selection'],arm_fidelity=record['arm_fidelity'],
                         reference_chromosome_length=sequences['dmel'][arm]['length'],
                         query_chromosome_length=sequences[short][arm]['length'],
                         gene_id_mapping='Ensembl gene_id attribute, otherwise ID with gene: prefix removed',
                         chromosome_correspondence='NCBI named assembled molecules; validated sequence lengths')
            # prepare() requires an empty output, so use the already saved arm table as a separate input.
            staging=out/'pairs'/f'{folder}.input.tsv';arm_table.replace(staging);directory.rmdir()
            prepare(files['dmel_gff'],files[short+'_gff'],staging,arm,record['query_sequence'],directory,
                    lock['selection']['minimum_markers'],sources)
            staging.replace(directory/'orthologs.tsv')
            case_manifest=directory/'manifest.json';case_data=json.loads(case_manifest.read_text())
            case=case_data['cases'][0];case['id']='real-v1-'+folder;case['label']=folder
            save(case_manifest,case_data)
            public=dict(case)
            public['path']=folder+'/'+case['path'];public['provenance']=folder+'/'+case['provenance']
            cases.append(public)
    if len(cases)>6:raise ValueError('Real corpus exceeds reservation case budget')
    save(out/'manifest.json',dict(schema=1,seed=42,corpus='drosophila-ensembl63-v1',cases=cases,
                                 source_lock_sha256=sha(lock_path),selection=lock['selection']))
    save(out/'audit.json',dict(pair_filtering=audit,candidates=candidates,chromosome_matrix=matrix,
                               counts=dict(reference_gene_records=len(gene_sets['dmel']),
                                           simulans_gene_records=len(gene_sets['dsim']),yakuba_gene_records=len(gene_sets['dyak']))))
    for filename,rows,fields in [
        ('candidates.tsv',candidates,['comparison','arm','query_sequence','reference_arm_orthologs','same_arm_before_coordinate_filter','coordinate_tie_removed','retained_markers','arm_fidelity','eligible','selected','reason']),
        ('chromosome-matrix.tsv',matrix,['comparison','reference_chromosome','query_sequence','orthologs'])]:
        with (out/filename).open('w') as f:
            writer=csv.DictWriter(f,fieldnames=fields,delimiter='\t',lineterminator='\n');writer.writeheader();writer.writerows(rows)
    save(out/'checksums.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    return cases


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lock',type=Path,default=ROOT/'datasets/real/source-lock.json')
    p.add_argument('--raw',type=Path,default=ROOT/'data/raw/ensembl63')
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(dict(cases=build(a.lock,a.raw,a.out))))

if __name__=='__main__':main()
