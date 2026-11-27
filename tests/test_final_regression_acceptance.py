import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import engineering_final_regression_acceptance as f

class FinalRegressionTests(unittest.TestCase):
    def setUp(self):
        self.chain=[dict(digest=str(i),snapshot={}) for i in range(1,5)]
        self.final={};self.gate={}
        for name,index,state in (('failed',3,'BLOCK'),('recovered',4,'PASS')):
            report=dict(gate=state,executed_count=3,case_count=3)
            digest=f.g.pp.digest(report)
            self.chain[index-1]['snapshot']['report_digest']=digest
            trace=dict(gate=state,attempted_order=['a','b','c'],unattempted_order=[],schedule=dict(execution_order=['a','b','c']))
            snap=dict(execution_version=index,execution_receipt_digest=str(index),report_digest=digest,
                      priority=trace,priority_digest=f.g.pp.digest(trace),**f.g.FLAGS)
            r=dict(snapshot=snap,digest=f.g.pp.digest(snap))
            self.final[name]=dict(registry=dict(history=self.chain[:index]),result=dict(report=report,priority_receipt=r))
            self.gate[name]=dict(state='BLOCK' if state=='BLOCK' else 'REGRESSION_QUALITY_PASS',priority_receipt=r,
                checks={k:('PASS' if state=='PASS' or k=='durable_priority_receipt' else 'BLOCK') for k in f.g.CHECKS})
        self.final['stale']=dict(registry=dict(history=self.chain))
        for name in ('missing','before_recovery','stale'):
            self.gate[name]=dict(state='BLOCK',priority_receipt=None,checks=dict(execution_quality='PASS',durable_priority_receipt='BLOCK'))
        for v in self.gate.values():
            v.update(full_regression_required=True,selective_execution_authorized=False,**f.g.FLAGS)
            v['evidence_digest']=f.g.pp.digest(v)
        a=self.final['failed']['result']['priority_receipt'];b=self.final['recovered']['result']['priority_receipt']
        self.d=dict(schema='orbit.final-regression-lifecycle.v1',
                    history={k:dict(execution_history=self.chain[:n],priority_history=r,priority_audit_count=len(r))
                             for k,n,r in (('missing',2,[]),('failed',3,[a]),('recovered',4,[a,b]),('stale',4,[a,b]))},
                    guard={**{k:True for k in f.REJECTIONS},'recovered':self.gate['recovered']})
    def test_complete_lifecycle(self):f.validate_lifecycle(self.d,self.gate,self.final)
    def test_missing_historical_failure_rejected(self):
        self.d['history']['stale']['priority_history']=[]
        with self.assertRaises(ValueError):f.validate_lifecycle(self.d,self.gate,self.final)
    def test_wrong_guard_or_missing_rejection(self):
        for k in f.REJECTIONS:
            d=copy.deepcopy(self.d);d['guard'][k]=False
            with self.assertRaises(ValueError):f.validate_lifecycle(d,self.gate,self.final)
    def test_changed_audit_count_rejected(self):
        self.d['history']['recovered']['priority_audit_count']=3
        with self.assertRaises(ValueError):f.validate_lifecycle(self.d,self.gate,self.final)
    def test_wrong_receipt_digest_rejected(self):
        self.final['failed']['result']['priority_receipt']['digest']='bad'
        with self.assertRaises(ValueError):f.validate_lifecycle(self.d,self.gate,self.final)
    def test_chain_digest_exact_and_complete(self):
        h={k:'a'*64 for k in f.NAMES};d=f.chain_digest(h)
        self.assertEqual(f.chain_digest(dict(reversed(list(h.items())))),d)
        h['git_change']='b'*64;self.assertNotEqual(f.chain_digest(h),d)
        del h['git_change']
        with self.assertRaises(ValueError):f.chain_digest(h)
if __name__=='__main__':unittest.main()
