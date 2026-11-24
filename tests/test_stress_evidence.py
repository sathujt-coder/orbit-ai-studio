import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from soak_acceptance import evaluate
from stress_common import Evidence,latency

SOURCE='a'*40
class StressEvidenceTests(unittest.TestCase):
    def evidence(self):
        report={'schema':'orbit.offline-stress.v1','profile':'soak24h','gate':'PASS','duration_gate':'PASS','elapsed_seconds':86400,'waves':288,'requests':6912,'agent_counts':{d+'-'+l:288 for d in ('po','research','ba','pm','design','techlead','dev','qa','qc','security','devops','marketing') for l in 'AB'},'started_at':1000,'finished_at':87400,'source_commit':SOURCE,'ledger':{'ok':6912},'complete_calls':6912,'local_assumed_zero_calls':6912,'reservations':6912,'denials':0,'breakers':{'closed':2},'api_cost_usd':'0.000000000000','database':{'quick_check':'ok','foreign_key_violations':0},'monitoring_status':{'failures':0},'concurrency':{'active':0,'waiting':0,'counts':{'acquired':6912,'released':6912}}}
        samples=[{'gate':'PASS','container_id':'fixture','sampled_at':i,'memory_limit':6*1024**3,'memory_swap':6*1024**3,'cpu_cores':2,'network':'none','running':True,'oom_killed':False,'memory_events':{'oom':0,'oom_kill':0}} for i in range(1000,87401,30)]
        return report,samples
    def test_synthetic_acceptance_logic(self):
        r,s=self.evidence();self.assertEqual(evaluate(r,s,SOURCE)['gate'],'PASS')
    def test_short_smoke_never_24h(self):
        r,s=self.evidence();r.update(profile='smoke',duration_gate='NOT_RUN',elapsed_seconds=30)
        self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
    def test_missing_agent_or_container_gap(self):
        r,s=self.evidence();r['agent_counts'].pop('po-A');self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
        r,s=self.evidence();del s[100:105];self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
    def test_container_restart_oom_or_incomplete_report(self):
        r,s=self.evidence();s[-1]['container_id']='other';self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
        r,s=self.evidence();s[0]['gate']='BLOCK';self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
        r,s=self.evidence();r['gate']='RUNNING';self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
    def test_evidence_exclusive_and_running_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json';e=Evidence(p,'fixture','smoke')
            with self.assertRaises(FileExistsError):Evidence(p,'fixture','smoke')
            e.data['requests']=24;e.save();self.assertEqual(json.loads(p.read_text())['gate'],'RUNNING')
    def test_latency_percentiles(self):
        self.assertEqual(latency([3,1,2,4]),{'count':4,'p50_ms':2,'p95_ms':4,'max_ms':4})

    def test_source_commit_and_raw_evidence_required(self):
        r,s=self.evidence();self.assertEqual(evaluate(r,s,'b'*40)['gate'],'BLOCK')
        r,s=self.evidence();r['ledger']={'ok':6911};self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
        r,s=self.evidence();s[0]['memory_events']['oom']=1;self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
        r,s=self.evidence();s[0]['network']='bridge';self.assertEqual(evaluate(r,s,SOURCE)['gate'],'BLOCK')
