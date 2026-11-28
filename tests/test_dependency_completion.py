import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import dependency_completion as dc
import project_planning as pp
import auth_policy

class DependencyCompletionTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY,project_id,adoption_version,package_id); INSERT INTO studio_coding_bindings VALUES('j','p',1,'P'); CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);")
        dc.ensure_schema(self.c)
        self.src=dict(project_id='p',job_id='j',adoption_version=1,package_id='P',report_id='r')
        self.decision=dict(selected='B',selected_digest='d',rationale='Trusted test fixture rationale.',decided_at='t')
        for obj,name,value in [(dc,'source',self.src),(dc,'selection',self.decision),(pp,'check_role',None)]:
            p=patch.object(obj,name,return_value=value);p.start();self.addCleanup(p.stop)
        self.body=dict(job_id='j',source_digest=pp.digest(self.src),expected_version=0,selected='B',rationale=self.decision['rationale'],confirmation='CONFIRM DEPENDENCY COMPLETION DEV-B j')
    def test_version_stale_and_tamper(self):
        self.assertFalse(dc.record(self.c,'p','reviewer',self.body,'t')['execution_authorized'])
        self.assertEqual(dc.view(self.c,'p')['items'][0]['state'],'COMPLETION_EVIDENCE_CONFIRMED')
        with self.assertRaises(ValueError):dc.record(self.c,'p','reviewer',self.body,'t')
        self.src['report_id']='new'
        self.assertEqual(dc.view(self.c,'p')['items'][0]['state'],'STALE')
        self.c.execute("UPDATE engineering_completions SET snapshot='{}'")
        self.assertEqual(dc.view(self.c,'p')['items'][0]['state'],'INVALID')
        self.assertEqual(dc.view(self.c,'other')['items'],[])
    def test_explicit_confirmation_and_role(self):
        for change in (dict(confirmation='yes'),dict(source_digest='wrong'),dict(expected_version=1),dict(selected='A')):
            with self.assertRaises(ValueError):dc.record(self.c,'p','reviewer',dict(self.body,**change),'t')
        with patch.object(pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):dc.record(self.c,'p','developer',self.body,'t')
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/engineering/completions/confirm'),('p','approve'))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_completions').fetchone()[0],0)
