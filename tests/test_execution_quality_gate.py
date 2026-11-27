import copy,sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import execution_quality_gate as g

class ExecutionGateTests(unittest.TestCase):
    def setUp(self):
        self.pid='p';self.jid='j';self.binding=dict(adoption_version=1,package_id='W',binding_digest='b'*64,spec_digest='c'*64)
        self.source=dict(project_id='p',job_id='j',**self.binding,acceptance=[dict(id='AC')],
                         candidates={'B':dict(digest='d'*64)})
        x=dict(runtime='python',module='main',function='add',arguments=[2,3],assertion=dict(operator='equals',value=5))
        self.cases=[dict(id='T-'+k,criterion_id='AC',kind=k,scenario='Scenario '+k,expected='Expected '+k,execution=copy.deepcopy(x)) for k in g.tp.KINDS]
        cases,cov=g.tp.coverage(self.source,self.cases,g.tp.V2)
        self.e=dict(schema=g.tp.V2,project_id='p',job_id='j',version=1,source=self.source,
                    source_digest=g.pp.digest(self.source),cases=cases,coverage=cov,**g.FLAGS)
        self.e['assertion_contract_digest']=g.tp.contract_digest(self.e)
        self.plan=dict(digest=g.pp.digest(self.e),snapshot=self.e)
        self.p=dict(project_id='p',job_id='j',state='TEST_PLAN_COVERAGE_PASS',assertion_status='ASSERTION_CONTRACT_READY',
            latest_version=1,history=[self.plan],source_digest=self.e['source_digest'],assertion_contract_digest=self.e['assertion_contract_digest'],**g.FLAGS)
        self.q=dict(project_id='p',job_id='j',state='QA_QC_EVIDENCE_PASS',checks={k:'PASS' for k in g.qc.CHECKS},
            findings=[],selected='B',binding=self.binding,receipts=dict(candidate_selection='e'*64,sandbox='f'*64),**g.FLAGS)
        self.q['evidence_digest']=g.pp.digest(self.q)
        self.src=dict(project_id='p',job_id='j',plan_version=1,plan_digest=self.plan['digest'],
            source_digest=self.e['source_digest'],assertion_contract_digest=self.e['assertion_contract_digest'],
            selected='B',selection_digest='e'*64,sandbox_digest='f'*64,candidate_digest='d'*64,git=dict(source_sha256='d'*64))
        self.report=dict(schema='orbit.acceptance-runner-report.v1',source=self.src,actor='reviewer',image='python@sha256:'+'0'*64,
            runtime='docker',network='none',workspace='read-only',results=[dict(case_id=t['id'],criterion_id='AC',kind=t['kind'],
            assertion_digest=g.pp.digest(t['execution']),path='main.py',module_sha256='a'*64,status='PASS',executed=True,
            reason='ASSERTION_MATCH',observation='returned',value_digest=g.pp.digest(5)) for t in cases],
            executed_count=3,case_count=3,gate='PASS',persisted=False,**g.FLAGS)
        self.s=dict(schema='orbit.assertion-run-receipt.v1',project_id='p',job_id='j',version=1,previous_digest=None,
                    report=self.report,report_digest=g.pp.digest(self.report),
                    summary=g.registry.validate_report(self.report,self.src,cases),created_at='stamp',**g.FLAGS)
        self.receipt=dict(digest=g.pp.digest(self.s),snapshot=self.s)
        self.r=dict(project_id='p',job_id='j',state='EXECUTION_RECORDED_PASS',latest_version=1,history=[self.receipt],current_receipt=self.receipt,**g.FLAGS)
    def evaluate(self):return g.evaluate(self.pid,self.jid,self.q,self.p,self.r)
    def rehash(self):
        self.s['report_digest']=g.pp.digest(self.report);self.receipt['digest']=g.pp.digest(self.s)
    def test_exact_pass_and_authority_flags(self):
        v=self.evaluate();self.assertEqual(v['state'],'EXECUTION_QUALITY_PASS')
        self.assertEqual(v['coverage']['executed_count'],3)
        self.assertTrue(all(v[k] is False for k in g.FLAGS))
        self.assertEqual(v['evidence_digest'],g.pp.digest({k:x for k,x in v.items() if k!='evidence_digest'}))
    def test_missing_receipt_and_legacy_qc_block(self):
        self.r.update(state='AWAITING_EXECUTION',history=[],latest_version=0,current_receipt=None)
        self.assertEqual(self.evaluate()['state'],'BLOCK')
        self.assertEqual(self.evaluate()['checks']['execution_receipt'],'BLOCK')
        self.q['state']='BLOCK'
        self.assertEqual(self.evaluate()['checks']['legacy_qc'],'BLOCK')
    def test_stale_receipt(self):
        self.r.update(state='STALE',current_receipt=None)
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_incomplete_or_unexecuted_never_pass(self):
        for mode in ('missing','unexecuted','wrong_value'):
            old=copy.deepcopy(self.report['results'])
            if mode=='missing':self.report['results'].pop()
            elif mode=='unexecuted':self.report['results'][0]['executed']=False
            else:self.report['results'][0]['value_digest']=g.pp.digest(99)
            self.rehash();self.assertEqual(self.evaluate()['state'],'BLOCK')
            self.report['results']=old
    def test_cross_binding_selection_or_plan_mismatch(self):
        for key in ('selection_digest','sandbox_digest','plan_digest','source_digest','candidate_digest','assertion_contract_digest'):
            old=self.src[key];self.src[key]='9'*64;self.rehash()
            v=self.evaluate();self.assertEqual(v['state'],'BLOCK');self.assertEqual(v['checks']['cross_binding'],'BLOCK')
            self.src[key]=old
    def test_legacy_plan_or_tampered_receipt(self):
        self.p['assertion_status']='NOT_READY'
        self.assertEqual(self.evaluate()['state'],'BLOCK')
        self.p['assertion_status']='ASSERTION_CONTRACT_READY'
        self.receipt['digest']='0'*64
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_require_current_exact_digest(self):
        c=sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        v=self.evaluate()
        with patch.object(g,'view',return_value=v):
            with self.assertRaises(ValueError):g.require_current(c,None,'p','j',v['evidence_digest'])
            c.execute('BEGIN')
            self.assertEqual(g.require_current(c,None,'p','j',v['evidence_digest']),v)
            with self.assertRaises(ValueError):g.require_current(c,None,'p','j','old')
    def test_cross_scope_and_unknown_authority(self):
        self.r['project_id']='other'
        self.assertEqual(self.evaluate()['state'],'BLOCK')
        self.r['project_id']='p';self.r['execution_authorized']=True
        self.assertEqual(self.evaluate()['state'],'BLOCK')

if __name__=='__main__':unittest.main()
