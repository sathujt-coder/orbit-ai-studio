import copy, unittest
from unittest.mock import patch
import defect_retest_quality as q

def seal(v):
    v.pop('evidence_digest',None)
    v['evidence_digest']=q.pp.digest(v)
    return v

class RetestQualityTests(unittest.TestCase):
    def setUp(self):
        self.pid,self.jid='p','j'
        self.source=dict(project_id='p',job_id='j',candidate_digest='c'*64)
        self.report=dict(source=self.source,gate='PASS',results=[dict(case_id='case',assertion_digest='a'*64,status='PASS',executed=True)],**q.FLAGS)
        s=dict(project_id='p',job_id='j',report=self.report,report_digest=q.pp.digest(self.report),**q.FLAGS)
        self.run=dict(snapshot=s,digest=q.pp.digest(s))
        self.g=seal(dict(project_id='p',job_id='j',state='REGRESSION_QUALITY_PASS',checks={'mandatory':'PASS'},
                         full_regression_required=True,selective_execution_authorized=False,receipts={'execution':self.run['digest']},**q.FLAGS))
        self.d=seal(dict(project_id='p',job_id='j',state='NO_FINDINGS',findings=[],receipt_digest=self.run['digest'],regression_digest=self.g['evidence_digest'],**q.FLAGS))
        self.original=dict(finding_id='f',execution_digest='b'*64,classification={'severity':'LOW'},finding={'case_id':'case','assertion_digest':'a'*64})
        self.rd=q.pp.digest(self.original)
        self.reg={'f':[dict(snapshot=self.original,digest=self.rd)]}
        e=dict(action='CLOSE',repair=dict(execution_digest=self.run['digest'],candidate_digest='c'*64,regression_digest=self.g['evidence_digest']))
        self.item=dict(finding_id='f',registration_digest=self.rd,latest=True,severity='LOW',state='CLOSED',history=[dict(snapshot=e,digest=q.pp.digest(e))])
        self.v=seal(dict(project_id='p',job_id='j',state='READY',registry_state='NO_CURRENT_FINDINGS',current_execution=self.run['digest'],items=[self.item],quality_gate_override=False,automatic_closure=False,**q.FLAGS))
    def evaluate(self):
        return q.evaluate('p','j',self.v,self.d,self.g,self.reg,self.run)
    def test_current_closure_pass(self):
        v=self.evaluate()
        self.assertEqual(v['state'],'RETEST_QUALITY_PASS')
        self.assertEqual(v['items'][0]['status'],'CURRENT_CLOSURE')
        self.assertTrue(all(v[k] is False for k in q.FLAGS))
    def test_clean_inventory_pass(self):
        self.reg={};self.v['items']=[];seal(self.v)
        self.assertEqual(self.evaluate()['state'],'RETEST_QUALITY_PASS')
    def test_unresolved_low_blocks(self):
        self.item['state']='IN_PROGRESS';self.item['history']=[];seal(self.v)
        v=self.evaluate()
        self.assertEqual(v['state'],'BLOCK');self.assertEqual(v['items'][0]['status'],'UNRESOLVED')
    def test_stale_closure_blocks(self):
        self.item['history'][0]['snapshot']['repair']['execution_digest']='d'*64;seal(self.v)
        v=self.evaluate()
        self.assertEqual(v['state'],'BLOCK');self.assertEqual(v['items'][0]['status'],'STALE_RETEST')
    def test_regression_block_cannot_override(self):
        self.g['state']='BLOCK';seal(self.g);self.d['regression_digest']=self.g['evidence_digest'];seal(self.d)
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_missing_inventory_blocks(self):
        self.v['items']=[];seal(self.v)
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_forged_digest_blocks(self):
        self.v['evidence_digest']='f'*64
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_changed_assertion_blocks(self):
        self.original['finding']['assertion_digest']='e'*64
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_exact_guard(self):
        v=self.evaluate()
        with patch.object(q,'view',return_value=v):
            self.assertEqual(q.require_current(None,None,'p','j',v['evidence_digest']),v)
            with self.assertRaises(ValueError):q.require_current(None,None,'p','j','bad')
    def test_historical_unresolved_blocks(self):
        original=copy.deepcopy(self.original);original['execution_digest']='e'*64
        rd=q.pp.digest(original)
        self.reg['f'].insert(0,dict(snapshot=original,digest=rd))
        self.v['items'].insert(0,dict(self.item,registration_digest=rd,latest=False,state='OPEN',history=[]));seal(self.v)
        self.assertEqual(self.evaluate()['state'],'BLOCK')
if __name__=='__main__':unittest.main()
