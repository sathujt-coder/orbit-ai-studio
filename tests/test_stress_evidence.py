import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from soak_acceptance import evaluate
from stress_common import Evidence,latency

class StressEvidenceTests(unittest.TestCase):
    def evidence(self):
        report={'schema':'orbit.offline-stress.v1','profile':'soak24h','gate':'PASS','duration_gate':'PASS','elapsed_seconds':86400,'waves':288,'requests':6912,'agent_counts':{str(i):288 for i in range(24)},'started_at':1000,'finished_at':87400}
        samples=[{'gate':'PASS','container_id':'fixture','sampled_at':i} for i in range(1000,87401,30)]
        return report,samples
    def test_synthetic_acceptance_logic(self):
        r,s=self.evidence();self.assertEqual(evaluate(r,s)['gate'],'PASS')
    def test_short_smoke_never_24h(self):
        r,s=self.evidence();r.update(profile='smoke',duration_gate='NOT_RUN',elapsed_seconds=30)
        self.assertEqual(evaluate(r,s)['gate'],'BLOCK')
    def test_missing_agent_or_container_gap(self):
        r,s=self.evidence();r['agent_counts'].pop('0');self.assertEqual(evaluate(r,s)['gate'],'BLOCK')
        r,s=self.evidence();del s[100:105];self.assertEqual(evaluate(r,s)['gate'],'BLOCK')
    def test_container_restart_oom_or_incomplete_report(self):
        r,s=self.evidence();s[-1]['container_id']='other';self.assertEqual(evaluate(r,s)['gate'],'BLOCK')
        r,s=self.evidence();s[0]['gate']='BLOCK';self.assertEqual(evaluate(r,s)['gate'],'BLOCK')
        r,s=self.evidence();r['gate']='RUNNING';self.assertEqual(evaluate(r,s)['gate'],'BLOCK')
    def test_evidence_exclusive_and_running_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json';e=Evidence(p,'fixture','smoke')
            with self.assertRaises(FileExistsError):Evidence(p,'fixture','smoke')
            e.data['requests']=24;e.save();self.assertEqual(json.loads(p.read_text())['gate'],'RUNNING')
    def test_latency_percentiles(self):
        self.assertEqual(latency([3,1,2,4]),{'count':4,'p50_ms':2,'p95_ms':4,'max_ms':4})
