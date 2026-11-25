"""No live calls in unit tests; actual benchmark workflow uses native Ollama."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import wbs_benchmark as b
import test_wbs_decomposition as fixtures

class WbsBenchmarkTests(unittest.TestCase):
    def test_frozen_fixture_shared_with_acceptance(self):
        doc,extra=b.approved_fixture()
        for case in b.CASES:
            src,blank=b.fixture(case)
            self.assertEqual(src['document'],doc)
            self.assertEqual(src['policy'],b.ps.contract(doc,extra))
            self.assertEqual(len(b.d.packages(blank)),6)
            self.assertTrue(all(p[k] is None for p in b.d.packages(blank).values() for k in b.w.DETAIL_FIELDS))
            self.assertEqual(b.fixture_id(case),b.fixture_id(case))
            self.assertTrue(b.ps.assess(src['proposal'],doc,src['policy'])['passed'])
        self.assertNotEqual(b.fixture_id('A'),b.fixture_id('B'))
    def test_uses_actual_quality_gate_not_alternative_score(self):
        src,blank=b.fixture('A')
        e=b.d.run(fixtures.synthetic(blank,[]),src,blank)
        self.assertTrue(e['ready'])
        calls=[dict(phase=a['phase'],coverage='complete',status='ok',source='ollama_native',
            input_tokens=10,output_tokens=5,total_tokens=15,elapsed_ms=20) for batch in e['history'] for a in batch['attempts']]
        result=b.measure(e,calls,src,blank)
        self.assertTrue(result['quality_pass']);self.assertEqual(result['total_tokens'],30)
        calls[0]['coverage']='partial'
        self.assertFalse(b.measure(e,calls,src,blank)['quality_pass'])
        self.assertIsNone(b.measure(e,calls,src,blank)['total_tokens'])
        forged=copy.deepcopy(e);forged['history'][0]['attempts'][0]['request']['schema_digest']='bad'
        with self.assertRaises(ValueError):b.measure(forged,calls,src,blank)
    def test_failure_not_qualified(self):
        src,blank=b.fixture('B')
        e=b.d.run(lambda *args:'{}',src,blank)
        self.assertFalse(b.measure(e,[],src,blank)['quality_pass'])
    def test_resource_evidence_fail_closed(self):
        r=dict(memory_limit=b.LIMIT,swap_limit=b.LIMIT,cgroup_limit_bytes=b.LIMIT,cpu_limit=2,network='none',
            running=True,oom_killed=False,restart_count=0,peak_bytes=1000,events={'oom':0,'oom_kill':0})
        self.assertTrue(b.resource_pass(r))
        for update in ({'peak_bytes':None},{'events':{}},{'events':{'oom':1,'oom_kill':0}},
                       {'network':'bridge'},{'restart_count':1},{'memory_limit':b.LIMIT+1}):
            self.assertFalse(b.resource_pass(dict(r,**update)))
    def test_qualification_requires_all_trials_same_model_digest(self):
        commit='a'*40
        rows=[]
        for c in b.CASES:
            src,blank=b.fixture(c)
            e=b.d.run(fixtures.synthetic(blank,[]),src,blank)
            for r in b.REPEATS:
                ident=dict(model=b.MODELS[0],digest='d'*64,ollama_version='x')
                calls=[dict(phase=a['phase'],model=b.MODELS[0],coverage='complete',status='ok',source='ollama_native',
                    input_tokens=10,output_tokens=5,total_tokens=15,elapsed_ms=20) for batch in e['history'] for a in batch['attempts']]
                wr=dict(schema=b.PROTOCOL,origin='actual_local_model',model=b.MODELS[0],case=c,repeat=r,
                    source_commit=commit,fixture_digest=b.fixture_id(c),pm_artifact_sha256=b.PM_ARTIFACT_SHA256,
                    production_adopted=False,semantic_reviewed=False,identity=ident,identity_after=copy.deepcopy(ident),
                    calls=calls,evidence=e,metrics=b.measure(e,calls,src,blank))
                resource=dict(memory_limit=b.LIMIT,swap_limit=b.LIMIT,cgroup_limit_bytes=b.LIMIT,cpu_limit=2,network='none',
                    running=True,oom_killed=False,restart_count=0,peak_bytes=1000,events={'oom':0,'oom_kill':0})
                rows.append(dict(model=b.MODELS[0],case=c,repeat=r,source_commit=commit,fixture_digest=b.fixture_id(c),
                    status='PASS',qualified=True,worker_exit=0,resources=resource,worker=wr))
        self.assertEqual(b.summarize(b.MODELS[0],rows,commit,{})['qualification'],'QUALIFIED')
        self.assertEqual(b.summarize(b.MODELS[0],rows[:-1],commit,{})['qualification'],'NOT_QUALIFIED')
        other=copy.deepcopy(rows);other[0]['worker']['identity']['digest']='e'*64
        self.assertEqual(b.summarize(b.MODELS[0],other,commit,{})['qualification'],'NOT_QUALIFIED')
        other=copy.deepcopy(rows);other[0].update(status='QUALITY_BLOCK',qualified=False)
        self.assertEqual(b.summarize(b.MODELS[0],other,commit,{})['qualification'],'NOT_QUALIFIED')
        forged=copy.deepcopy(rows);forged[0]['resources']['events']['oom']=1
        self.assertEqual(b.summarize(b.MODELS[0],forged,commit,{})['qualification'],'NOT_QUALIFIED')
        forged=copy.deepcopy(rows);forged[0]['worker']['evidence']['candidate_digest']='forged'
        forged[0]['worker']['evidence']['history'][0]['attempts'][0]['request']['schema_digest']='bad'
        self.assertEqual(b.summarize(b.MODELS[0],forged,commit,{})['qualification'],'NOT_QUALIFIED')
    def test_fixed_configuration_and_percentiles(self):
        self.assertEqual(len(b.MODELS),6);self.assertEqual(b.d.BATCH,3)
        self.assertEqual(b.d.MAX_OUTPUT,1536);self.assertEqual(b.CONTEXT,8192)
        self.assertEqual(b.percentile([1,2,3,4],.95),4)
        self.assertIsNone(b.percentile([], .95))
        self.assertTrue(b.pinned_image('ollama/ollama@sha256:'+'a'*64,'ollama/ollama'))
        self.assertFalse(b.pinned_image('ollama/ollama:latest','ollama/ollama'))
