"""Retry defect continuity regressions; HTTP acceptance uses production recovery."""
import sqlite3
import unittest
from unittest.mock import patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_quality as eq
import bound_recovery as br
import agent_queue as aq

class DefectContinuityTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.addCleanup(self.c.close)
        self.c.executescript("""CREATE TABLE projects(id PRIMARY KEY);
            CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY,project_id,queue_id,adoption_version,package_id,binding_digest,spec_digest,actor);
            CREATE TABLE studio_bound_retries(job_id PRIMARY KEY,previous_job_id,project_id);
            CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);
            INSERT INTO projects VALUES('p');
            INSERT INTO studio_coding_bindings VALUES('old','p','q1',1,'P','b','s','owner');""")
        eq.ensure_schema(self.c)
        self.queues={'q1':dict(id='q1',coding_job_id='old',actor='owner',kind='coding',retry_of=None)}
        self.valid=patch.object(br,'validate_retry');self.validate=self.valid.start();self.addCleanup(self.valid.stop)
        for obj,name,kwargs in [(aq,'get',dict(side_effect=lambda c,p,q:self.queues[q])),
                (eq.pp,'check_role',dict(return_value=None)),(eq,'source',dict(side_effect=self.source))]:
            p=patch.object(obj,name,**kwargs);p.start();self.addCleanup(p.stop)
        self.evidence={}
        self.event('old','OPEN',0)

    def source(self,c,db,pid,jid):
        return dict(project_id=pid,job_id=jid,binding=dict(adoption_version=1,package_id='P',binding_digest='b',spec_digest='s'),
                    qa=dict(state='BLOCK',source_digest=None,receipt_digest=None),
                    sandbox=dict(state='BLOCK',source_digest=None,version=0,receipt_digest=None),
                    **eq.FLAGS)|self.evidence.get(jid,{})

    def event(self,jid,action,version):
        body=dict(action=action,defect_id='D1',expected_version=version,source_digest=eq.pp.digest(self.source(self.c,None,'p',jid)),
            rationale='Explicit defect continuity regression evidence.',confirmation='DEFECT '+action+' '+jid+' D1')
        if action=='OPEN':body.update(title='Known retry defect',severity='HIGH',category='TEST')
        return eq.record(self.c,None,'p',jid,'owner',body,'stamp')

    def retry(self,job='new',qid='q2',prior='old',previous='q1'):
        self.c.execute('INSERT INTO studio_coding_bindings VALUES(?,?,?,?,?,?,?,?)',(job,'p',qid,1,'P','b','s','owner'))
        self.c.execute('INSERT INTO studio_bound_retries VALUES(?,?,?)',(job,prior,'p'))
        self.queues[qid]=dict(id=qid,coding_job_id=job,actor='owner',kind='coding',retry_of=previous)

    def test_inherited_defect_blocks_and_old_attempt_frozen(self):
        self.retry()
        view=eq.view(self.c,None,'p','new')
        self.assertEqual(view['lineage'],['old','new'])
        self.assertEqual(view['counts']['OPEN'],1)
        self.assertEqual(view['defects'][0]['origin_job_id'],'old')
        with self.assertRaises(ValueError):self.event('old','READY_FOR_RETEST',1)
        with self.assertRaises(ValueError):self.event('new','OPEN',0)
        with self.assertRaises(ValueError):eq.guard_no_open_defects(self.c,'p','new')
        self.assertTrue(self.validate.called)

    def test_current_handoff_and_fresh_retest(self):
        self.retry()
        self.event('new','READY_FOR_RETEST',1)
        with self.assertRaises(ValueError):self.event('new','CLOSED',2)
        self.evidence['new']=dict(qa=dict(state='HUMAN_QA_PASS',source_digest='qs',receipt_digest='qr'),
            sandbox=dict(state='PASS',source_digest='ss',version=1,receipt_digest='sr'))
        self.event('new','CLOSED',2)
        view=eq.view(self.c,None,'p','new')
        self.assertEqual(view['state'],'QUALITY_EVIDENCE_PASS')
        self.assertEqual([x['event']['job_id'] for x in view['defects'][0]['history']],['old','new','new'])
        eq.guard_no_open_defects(self.c,'p','new')
        self.evidence['new']['qa']['receipt_digest']='changed'
        self.assertEqual(eq.view(self.c,None,'p','new')['state'],'BLOCK')

    def test_multi_attempt_inherits_ready_but_requires_current_handoff(self):
        self.retry();self.event('new','READY_FOR_RETEST',1)
        self.retry('third','q3','new','q2')
        self.evidence['third']=dict(qa=dict(state='HUMAN_QA_PASS',source_digest='qs',receipt_digest='qr'),
            sandbox=dict(state='PASS',source_digest='ss',version=1,receipt_digest='sr'))
        with self.assertRaises(ValueError):self.event('third','CLOSED',2)
        self.event('third','REOPEN',2)
        self.event('third','READY_FOR_RETEST',3)
        self.assertEqual(eq.view(self.c,None,'p','third')['counts']['READY_FOR_RETEST'],1)

    def test_lineage_tamper_and_cross_project_block(self):
        self.retry()
        self.queues['q2']['retry_of']='wrong'
        with self.assertRaises(ValueError):eq.history(self.c,'p','new')
        self.assertEqual(eq.view(self.c,None,'p','new')['state'],'BLOCK')
        with self.assertRaises(ValueError):eq.history(self.c,'other','new')

    def test_invalid_retry_receipt_blocks(self):
        self.retry();self.validate.side_effect=ValueError('Invalid bound retry receipt')
        with self.assertRaises(ValueError):eq.guard_no_open_defects(self.c,'p','new')
        self.assertEqual(eq.view(self.c,None,'p','new')['state'],'BLOCK')

if __name__=='__main__':unittest.main()
