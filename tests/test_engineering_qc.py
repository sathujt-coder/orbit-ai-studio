"""Deterministic QC projection; real HTTP/Git/Docker acceptance in Chromium."""
import copy
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_qc as qc
import auth_policy

class EngineeringQCTests(unittest.TestCase):
    def setUp(self):
        H=lambda x:x*64
        self.binding=dict(adoption_version=1,package_id='P',binding_digest=H('a'),spec_digest=H('b'))
        self.b=dict(job_id='j',state='BOUND',**self.binding)
        src=dict(project_id='p',job_id='j',**self.binding,candidates={'A':{'digest':H('c')},'B':{'digest':H('d')}},
                 acceptance=[{'id':'AC1'}])
        self.q=dict(state='HUMAN_QA_PASS',source=src,source_digest=H('e'),receipt=dict(digest=H('f'),criteria=[dict(id='AC1',verdict='PASS')]))
        self.s=dict(state='SELECTED',source=dict(bound_evidence=copy.deepcopy(src)),receipt=dict(digest=H('1'),selected='B',selected_digest=H('d')))
        self.r=dict(state='PASS',source_digest=H('2'),receipt=dict(digest=H('3'),selected='B',selection_digest=H('1'),
            git={k:dict(source_sha256=v['digest']) for k,v in src['candidates'].items()},
            lanes={k:dict(sha256=v['digest'],status='passed',test_count=1) for k,v in src['candidates'].items()}))
        self.f=dict(state='QUALITY_EVIDENCE_PASS',source_digest=H('4'),counts=dict(OPEN=0,READY_FOR_RETEST=0,CLOSED=1),defects=[dict(id='D1')],
            source=dict(project_id='p',job_id='j',binding=self.binding,qa=dict(receipt_digest=H('f'),source_digest=H('e')),
            sandbox=dict(receipt_digest=H('3'),source_digest=H('2'))))
        self.m=dict(job_id='j',state='COMPLETION_EVIDENCE_CONFIRMED',source=dict(qa_digest=H('f')),receipt=dict(digest=H('5'),selected='B',selected_digest=H('d')))
        self.d=dict(state='CREATED_DRAFT',plan_digest=H('6'),receipt=dict(status='CREATED_DRAFT',plan_digest=H('6'),remote=dict(draft=True),**qc.FLAGS))
        for obj,name,val in ((qc.sc,'evidence',self.b),(qc.qa,'view',self.q),(qc.sel,'view',self.s),(qc.sb,'view',self.r),
                             (qc.quality,'view',self.f),(qc.draft,'view',self.d),(qc.dc,'view',dict(items=[self.m]))):
            p=patch.object(obj,name,return_value=val);p.start();self.addCleanup(p.stop)

    def view(self):return qc.view(None,None,'p','j')

    def test_pass_deterministic_and_no_authority(self):
        result=self.view()
        self.assertEqual(result['state'],'QA_QC_EVIDENCE_PASS')
        self.assertEqual(result,self.view())
        self.assertEqual(result['evidence_digest'],qc.pp.digest({k:v for k,v in result.items() if k!='evidence_digest'}))
        self.assertTrue(all(result[k] is False for k in qc.FLAGS))
        self.assertFalse(result['remote_live_verified'])
        self.assertEqual(result['findings'],[])

    def test_open_defect_blocks_even_if_draft_exists(self):
        self.f.update(state='BLOCK',counts=dict(OPEN=1,READY_FOR_RETEST=0,CLOSED=0))
        result=self.view()
        self.assertEqual(result['state'],'BLOCK')
        self.assertEqual(result['checks']['draft'],'PASS')
        self.assertEqual(result['checks']['defects'],'BLOCK')

    def test_stale_qa_and_sandbox_block(self):
        self.q['state']='STALE';self.r['state']='STALE'
        result=self.view()
        self.assertEqual(result['state'],'BLOCK')
        self.assertEqual(result['checks']['human_qa'],'BLOCK')
        self.assertEqual(result['checks']['sandbox'],'BLOCK')

    def test_conflicting_candidate_receipts_block(self):
        self.m['receipt']['selected']='A'
        self.assertEqual(self.view()['checks']['cross_binding'],'BLOCK')

    def test_missing_lane_or_zero_tests_block(self):
        self.r['receipt']['lanes']['A']['test_count']=0
        self.assertEqual(self.view()['checks']['cross_binding'],'BLOCK')
        del self.r['receipt']['lanes']['A']
        self.assertEqual(self.view()['state'],'BLOCK')

    def test_unknown_project_and_malformed_receipt_fail_closed(self):
        self.q['receipt']['criteria']=None
        self.assertEqual(self.view()['state'],'BLOCK')
        qc.sc.evidence.side_effect=ValueError('Other project secret')
        result=self.view()
        self.assertIsNone(result['binding'])
        self.assertEqual(result['receipts'],{})
        self.assertNotIn('secret',str(result))

    def test_read_only_route_and_no_draft_authority(self):
        path='/api/projects/p/engineering/qc/j'
        self.assertEqual(auth_policy.scope(None,'GET',path),('p','read'))
        self.assertIsNone(auth_policy.scope(None,'POST',path))
        self.d['receipt']['remote']['draft']=False
        self.assertEqual(self.view()['checks']['draft'],'BLOCK')

if __name__=='__main__':unittest.main()
