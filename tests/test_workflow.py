import argparse
import json
import gzip
import csv
import shutil
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import campaign
import generate_inputs
import prepare_genomes
import analyze
import prepare_real_corpus
import validate_corpus

parser=argparse.ArgumentParser()
parser.add_argument('--binary',type=Path,required=True)
parser.add_argument('--checker',type=Path,required=True)
args,other=parser.parse_known_args()
BINARY=args.binary.resolve()
CHECKER=args.checker.resolve()
sys.argv=[sys.argv[0]]+other

class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def invoke(self,*command,ok=True):
        p=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode==0,ok,p.stderr)
        return p
    def corpus(self,name='data'):
        path=self.root/name
        generate_inputs.generate(path,[10,33],[4],1,1)
        return path/'manifest.json'
    def test_distinct_reproducible_corpora(self):
        a=self.corpus('a');b=self.corpus('b')
        self.assertEqual(a.read_bytes(),b.read_bytes())
        cases=json.loads(a.read_text())['cases']
        pilot={r['sha256'] for r in cases if r['split']=='pilot'}
        main={r['sha256'] for r in cases if r['split']=='main'}
        self.assertTrue(pilot.isdisjoint(main))
        self.assertEqual(len({r['sha256'] for r in cases}),len(cases))
    def test_cli_replay_and_json_escaping(self):
        path=self.root/'input.txt';path.write_text('6\n3 6 5 2 1 4\n')
        trace=self.root/'quoted"trace.txt'
        p=self.invoke(BINARY,'--mode','seq','--input',path,'--trace',trace,'--warmups',1,'--repetitions',3,'--debug-state')
        rows=[json.loads(s) for s in p.stdout.splitlines()]
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]['coordination'],'sequential')
        for r in rows:
            self.invoke(CHECKER,path,r['trace_path'])
        corrupt=self.root/'bad.trace';corrupt.write_text('COOPSBR_TRACE_V1 6 1\n0 8\n')
        self.invoke(CHECKER,path,corrupt,ok=False)
        for text in ('2\n1 1\n','2\n0 2\n','2\n1 2 3\n','0\n'):
            path.write_text(text)
            self.invoke(BINARY,'--input',path,'--trace',trace,ok=False)
    def test_budget_and_watchdog(self):
        directory=self.root/'run';campaign.initialize(directory,24)
        with self.assertRaises(ValueError):campaign.initialize(directory,24)
        b=campaign.Budget(directory);b.enter('pilot')
        start=time.monotonic()
        rows,status=campaign.capture([sys.executable,'-c','import time;time.sleep(30)'],b,'pilot',.15,
                                     self.root/'out',self.root/'err')
        self.assertEqual(status,'timeout');self.assertEqual(rows,[])
        self.assertLess(time.monotonic()-start,3)
        b.state['elapsed_seconds']=24*3600+1;b.checkpoint()
        self.assertEqual(b.remaining('pilot'),0)
        _,status=campaign.capture([sys.executable,'-c','raise Exception()'],b,'pilot',10,
                                 self.root/'out',self.root/'err')
        self.assertEqual(status,'budget_skip')
    def test_short_study_deadline_survives_resume(self):
        directory=self.root/'short';campaign.initialize(directory,24,wall_minutes=1)
        b=campaign.Budget(directory);b.enter('pilot');start=b.state['start_wall']
        self.assertLessEqual(b.remaining('pilot'),54)
        b.state['elapsed_seconds']=55;b.checkpoint()
        self.assertEqual(b.remaining('pilot'),0)
        b.enter('buffer');self.assertGreater(b.remaining('buffer'),0)
        b.close();b=campaign.Budget(directory)
        self.assertEqual(b.state['start_wall'],start)
        self.assertEqual(b.remaining('pilot'),0)
        b.state['elapsed_seconds']=61;b.checkpoint()
        self.assertEqual(b.remaining('buffer'),0)
        b.close()

    def test_resume_forecast_and_analysis(self):
        manifest=self.corpus()
        directory=self.root/'run';campaign.initialize(directory,24)
        script=ROOT/'scripts/campaign.py'
        common=[sys.executable,script,'run','--campaign',directory,'--manifest',manifest,
                '--variants','SEQ','--binary',BINARY,'--checker',CHECKER]
        self.invoke(*common,'--stage','synthetic','--split','main',ok=False) # No pilot: fail closed.
        self.invoke(*common,'--stage','pilot','--split','pilot')
        before=(directory/'results.jsonl').read_bytes()
        start=json.loads((directory/'state.json').read_text())['start_wall']
        self.invoke(*common,'--stage','pilot','--split','pilot')
        self.assertEqual(before,(directory/'results.jsonl').read_bytes())
        self.assertEqual(start,json.loads((directory/'state.json').read_text())['start_wall'])
        self.invoke(*common,'--stage','synthetic','--split','main')
        result=analyze.analyze(directory,self.root/'report','synthetic')
        self.assertEqual(result['complete_input_variants'],4)
        self.assertEqual(result['paired_inputs'],0)
        b=campaign.Budget(directory)
        campaign.pin(b,'example','a')
        with self.assertRaises(ValueError):campaign.pin(b,'example','b')
    def test_separately_pinned_experimental_revision(self):
        manifest=self.corpus()
        directory=self.root/'run';campaign.initialize(directory,24)
        script=ROOT/'scripts/campaign.py'
        common=[sys.executable,script,'run','--campaign',directory,'--manifest',manifest,
                '--variants','SEQ','--checker',CHECKER]
        self.invoke(*common,'--binary',BINARY,'--stage','pilot','--split','pilot')
        wrapper=self.root/'wrapper'
        wrapper.write_text('#!'+sys.executable+'\nimport os,sys\nos.execv('+repr(str(BINARY))+',['+repr(str(BINARY))+']+sys.argv[1:])\n')
        wrapper.chmod(0o700)
        tagged=common+['--binary',wrapper,'--label','EXP-SEQ']
        self.invoke(*tagged,'--stage','pilot','--split','pilot')
        self.invoke(*tagged,'--stage','synthetic','--split','main')
        state=json.loads((directory/'state.json').read_text())
        self.assertEqual(state['pinned']['binary_sha256'],campaign.sha(BINARY))
        self.assertEqual(state['pinned']['binary_sha256:EXP-SEQ'],campaign.sha(wrapper))
        before=(directory/'results.jsonl').read_bytes()
        self.invoke(*tagged,'--stage','synthetic','--split','main')
        self.assertEqual(before,(directory/'results.jsonl').read_bytes())
        self.assertEqual(state['start_wall'],json.loads((directory/'state.json').read_text())['start_wall'])
        wrapper.write_text(wrapper.read_text()+'\n')
        self.invoke(*tagged,'--stage','pilot','--split','pilot',ok=False)
        self.assertEqual(before,(directory/'results.jsonl').read_bytes())
        self.invoke(*common,'--binary',BINARY,'--label','SEQ','--stage','pilot','--split','pilot',ok=False)
        self.invoke(*common,'--binary',BINARY,'--reduction','scalar','--stage','pilot','--split','pilot',ok=False)

    def test_interleaved_experimental_definitions(self):
        manifest=self.corpus()
        directory=self.root/'run';campaign.initialize(directory,24)
        definitions=self.root/'variants.json'
        payload=dict(schema=1,variants={'EXP-A':{'base':'SEQ'},'EXP-B':{'base':'SEQ'}})
        definitions.write_text(json.dumps(payload))
        common=[sys.executable,ROOT/'scripts/campaign.py','run','--campaign',directory,
                '--manifest',manifest,'--binary',BINARY,'--checker',CHECKER,
                '--experimental-variants',definitions]
        self.invoke(*common,'--stage','pilot','--split','pilot')
        self.invoke(*common,'--stage','synthetic','--split','main')
        rows=list(campaign.latest(directory).values())
        main=[r for r in rows if r['stage']=='synthetic' and r['status']=='verified' and not r['warmup']]
        self.assertEqual(len(main),24)
        self.assertEqual({r['variant'] for r in main},{'EXP-A','EXP-B'})
        before=(directory/'results.jsonl').read_bytes()
        self.invoke(*common,'--stage','synthetic','--split','main')
        self.assertEqual(before,(directory/'results.jsonl').read_bytes())
        payload['variants']['EXP-A']['base']='GPU-INC'
        definitions.write_text(json.dumps(payload))
        self.invoke(*common,'--stage','pilot','--split','pilot',ok=False)
        self.assertEqual(before,(directory/'results.jsonl').read_bytes())

    def test_shuffled_main_pairs_are_pinned_on_resume(self):
        path=self.root/'data'
        generate_inputs.generate(path,[10,33],[4],2,1)
        manifest=path/'manifest.json'
        directory=self.root/'run';campaign.initialize(directory,24)
        definitions=self.root/'variants.json'
        definitions.write_text(json.dumps(dict(schema=1,variants={'EXP-A':{'base':'SEQ'},'EXP-B':{'base':'SEQ'}})))
        common=[sys.executable,ROOT/'scripts/campaign.py','run','--campaign',directory,
                '--manifest',manifest,'--experimental-variants',definitions,'--binary',BINARY,'--checker',CHECKER]
        self.invoke(*common,'--stage','pilot','--split','pilot')
        self.invoke(*common,'--stage','synthetic','--split','main','--shuffle-cases')
        rows=list(campaign.latest(directory).values())
        jobs=[r for r in rows if r.get('event')=='batch' and r['stage']=='synthetic']
        expected={c['id'] for c in json.loads(manifest.read_text())['cases'] if c['split']=='main'}
        self.assertEqual({r['case_id'] for r in jobs},expected)
        self.assertEqual(len(jobs),16)
        for a,b in zip(jobs[::2],jobs[1::2]):
            self.assertEqual(a['case_id'],b['case_id'])
            self.assertEqual({a['variant'],b['variant']},{'EXP-A','EXP-B'})
        self.assertNotEqual([r['n'] for r in jobs],sorted(r['n'] for r in jobs))
        before=(directory/'results.jsonl').read_bytes()
        start=json.loads((directory/'state.json').read_text())['start_wall']
        self.invoke(*common,'--stage','synthetic','--split','main','--shuffle-cases')
        self.assertEqual(before,(directory/'results.jsonl').read_bytes())
        self.assertEqual(start,json.loads((directory/'state.json').read_text())['start_wall'])
        self.invoke(*common,'--stage','synthetic','--split','main',ok=False)
        self.assertEqual(before,(directory/'results.jsonl').read_bytes())

    def test_partial_checkpoint_and_live_status(self):
        directory=self.root/'run';campaign.initialize(directory,24)
        b=campaign.Budget(directory);b.enter('pilot')
        self.invoke(sys.executable,ROOT/'scripts/campaign.py','status','--campaign',directory)
        def record(row):
            row.update(id='partial',status='produced')
            b.append(row)
        code='import json,time; print(json.dumps(dict(schema=1)),flush=True); time.sleep(30)'
        _,status=campaign.capture([sys.executable,'-c',code],b,'pilot',.15,
                                  self.root/'out',self.root/'err',record)
        self.assertEqual(status,'timeout')
        self.assertIn('partial',campaign.latest(directory))
        b.close()
        with (directory/'results.jsonl').open('ab') as f:f.write(b'{"interrupted":')
        resumed=campaign.Budget(directory)
        self.assertIn('partial',campaign.latest(directory))
        self.assertTrue((directory/'interrupted-tail.bin').exists())
        resumed.close()
    def test_timed_out_pilot_cell_blocks_forecast(self):
        directory=self.root/'run';campaign.initialize(directory,24)
        b=campaign.Budget(directory);b.enter('synthetic')
        b.append(dict(id='sample',stage='pilot',status='verified',family='uniform',n=10,k=None,
                      variant='SEQ',end_to_end_ms=1,context_ms=0))
        b.append(dict(id='batch',event='batch',stage='pilot',status='timeout',family='uniform',n=10,k=None,variant='SEQ'))
        with self.assertRaises(ValueError):
            campaign.forecast(b,'synthetic',[dict(id='case',family='uniform',n=10,k=None)],['SEQ'],b.config['main'])
        b.close()
    def test_compressed_ensembl_gene_identifiers(self):
        path=self.root/'ensembl.gff3.gz'
        with gzip.open(path,'wt') as f:
            f.write('arm\tsource\tgene\t1\t50\t.\t+\t.\tID=gene:FBgn1;gene_id=FBgn1\n')
            f.write('arm\tsource\tgene\t100\t150\t.\t-\t.\tID=gene:LOC2\n')
        self.assertEqual(set(prepare_genomes.genes(path)),{'FBgn1','LOC2'})
    def test_complementary_orthology_dumps_and_strict_filter(self):
        columns=['gene_stable_id','species','homology_gene_stable_id','homology_species',
                 'homology_type','is_high_confidence','homology_id','goc_score','wga_coverage']
        a=self.root/'ref.tsv.gz';b=self.root/'query.tsv.gz'
        def row(x,y,t,h,identifier,reverse=False):
            return dict(zip(columns,[y if reverse else x,'query' if reverse else 'reference',
                        x if reverse else y,'reference' if reverse else 'query',t,h,identifier,'100','NULL']))
        def write(path,rows):
            with gzip.open(path,'wt') as f:
                w=csv.DictWriter(f,fieldnames=columns,delimiter='\t');w.writeheader();w.writerows(rows)
        first=row('a','x','ortholog_one2one','1','1')
        write(a,[first,row('a','y','ortholog_one2many','1','2'),row('c','z','ortholog_one2one','0','3')])
        write(b,[row('a','x','ortholog_one2one','1','1',True),row('d','w','ortholog_one2one','1','4',True)])
        relations,dups=prepare_real_corpus.collect_homologies([a,b],'reference',{'query':'q'})
        self.assertEqual(len(relations['query']),4);self.assertEqual(dups['query'],1)
        loci=lambda ids:{key:[('arm',1,10,'+')] for key in ids}
        kept,rejected=prepare_real_corpus.strict_pairs(relations['query'],loci('acd'),loci('xyzw'))
        self.assertEqual([(r['reference_gene'],r['query_gene']) for r in kept],[('d','w')])
        self.assertEqual(len(rejected),3)
    def test_corpus_construction_trace_validation(self):
        path=self.corpus()
        self.assertTrue(validate_corpus.validate(path)['valid'])
        manifest=json.loads(path.read_text())
        target=next(c for c in manifest['cases'] if c['family']=='semi')
        trace_path=path.parent/target['generation_trace']
        trace=json.loads(trace_path.read_text());trace[0]=[0,0]
        trace_path.write_text(json.dumps(trace)+'\n')
        target['generation_trace_sha256']=campaign.sha(trace_path)
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):validate_corpus.validate(path)
    def test_coordinate_ties_exclude_entire_marker_group(self):
        matches=[('a','x',('arm',1,30,'+'),('arm',100,130,'+')),
                 ('b','y',('arm',1,50,'-'),('arm',200,230,'+')),
                 ('c','z',('arm',300,350,'+'),('arm',400,450,'-'))]
        kept,rejected=prepare_genomes.drop_start_ties(matches)
        self.assertEqual([r[0] for r in kept],['c'])
        self.assertEqual(len(rejected),2)
    def test_gene_orders_and_filtering(self):
        ref=self.root/'ref.gff';qry=self.root/'qry.gff';orth=self.root/'orth.tsv'
        def gff(ids):
            return ''.join(f'arm\ttest\tgene\t{i*100+1}\t{i*100+50}\t.\t-\t.\tID={gene}\n' for i,gene in enumerate(ids))
        ref.write_text(gff(['a','b','c']));qry.write_text(gff(['z','x','y']))
        orth.write_text('reference_gene\tquery_gene\na\tx\nb\ty\nc\tz\n')
        sources=dict(reference_assembly='fixture-ref',query_assembly='fixture-qry',orthology_source='test fixture',reference_chromosome_length=1000,query_chromosome_length=1000)
        result=prepare_genomes.prepare(ref,qry,orth,'arm','arm',self.root/'real',3,sources)
        self.assertEqual(result['retained'],3)
        self.assertEqual((self.root/'real/permutation.txt').read_text().split(),['3','3','1','2'])
        shutil.copyfile(orth,self.root/'real/orthologs.tsv')
        self.assertTrue(validate_corpus.validate(self.root/'real/manifest.json')['valid'])
        mapping=self.root/'real/mapping.tsv'
        with mapping.open() as f: rows=list(csv.DictReader(f,delimiter='\t'))
        rows[0]['query_start']='500'
        with mapping.open('w') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter='\t');w.writeheader();w.writerows(rows)
        with self.assertRaises(ValueError):validate_corpus.validate(self.root/'real/manifest.json')
        orth.write_text('reference_gene\tquery_gene\na\tx\na\tx\nb\ty\nc\tz\n')
        result=prepare_genomes.prepare(ref,qry,orth,'arm','arm',self.root/'filtered',2,sources)
        self.assertEqual(result['retained'],2)
        self.assertEqual(result['rejected'],2)

if __name__=='__main__':unittest.main()
