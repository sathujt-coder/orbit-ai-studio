import sys
import sqlite3
import json
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import studio_verification as qa
import project_planning as pp
import auth_policy

class StudioVerificationTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("""CREATE TABLE projects(id PRIMARY KEY); CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY);
        CREATE TABLE coding_verifications(id,project_id,job_id,verdict,report_json);
        CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);""")
        qa.ensure_schema(self.c)
        self.src=dict(project_id='p',job_id='j',acceptance=[dict(id='AC',text='Exact criterion')],report_id='r',report_digest='digest')
        self.p=patch.object(qa,'source',return_value=self.src);self.p.start();self.addCleanup(self.p.stop)
        p=patch.object(pp,'check_role',return_value=None);p.start();self.addCleanup(p.stop)
        self.body=dict(job_id='j',source_digest=pp.digest(self.src),expected_version=0,criteria=[dict(id='AC',verdict='PASS',rationale='Human inspected the exact criterion.')],confirmation='ATTEST WORK PACKAGE QA')
    def test_attestation_version_and_stale_evidence(self):
        result=qa.attest(self.c,'p','owner',self.body,'t')
        self.assertEqual(result['version'],1)
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(qa.view(self.c,'p','j')['state'],'HUMAN_QA_PASS')
        self.assertFalse(qa.view(self.c,'p','j')['dependency_completed'])
        with self.assertRaises(ValueError):qa.attest(self.c,'p','owner',self.body,'t')
        self.src['report_id']='new'
        self.assertEqual(qa.view(self.c,'p','j')['state'],'STALE')
    def test_exact_criteria_and_approval_role(self):
        for change in (dict(criteria=[]),dict(source_digest='wrong'),dict(confirmation='yes')):
            with self.assertRaises(ValueError):qa.attest(self.c,'p','owner',dict(self.body,**change),'t')
        with patch.object(pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):qa.attest(self.c,'p','developer',self.body,'t')
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/studio/work-packages/qa'),('p','approve'))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM studio_qa_receipts').fetchone()[0],0)
    def test_source_requires_current_project_and_real_verification(self):
        self.p.stop()
        b=dict(state='BOUND',queue_id='q',adoption_version=1,package_id='P',binding_digest='b',spec_digest='s')
        job=dict(project_id='p',manifest={},review_a={},review_b={})
        report=dict(project_id='p',job_id='j',verdict='passed',sandbox=dict(network='none'))
        self.c.execute('INSERT INTO coding_verifications VALUES(?,?,?,?,?)',('r','p','j','passed',json.dumps(report)))
        with patch.object(qa.sc,'evidence',return_value=b),patch.object(qa.agent_queue,'get',return_value={'status':'succeeded'}),patch.object(qa.sc,'checked_package',return_value={'acceptance':self.src['acceptance']}),patch.object(qa.coding_factory,'detail',return_value=job),patch.object(qa,'compare',side_effect=ValueError('demo or invalid')):
            with self.assertRaises(ValueError):qa.source(self.c,'p','j')
        with patch.object(qa.sc,'evidence',return_value=b),patch.object(qa.agent_queue,'get',return_value={'status':'succeeded'}),patch.object(qa.sc,'checked_package',return_value={'acceptance':self.src['acceptance']}),patch.object(qa.coding_factory,'detail',return_value=job),patch.object(qa,'compare',return_value={'candidates':{lane:{'digest':lane,'test_count':1} for lane in 'AB'}}):
            self.assertEqual(qa.source(self.c,'p','j')['report_id'],'r')
            with self.assertRaises(ValueError):qa.source(self.c,'other','j')
