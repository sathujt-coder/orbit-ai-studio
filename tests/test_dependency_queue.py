import sys
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import dependency_queue as dq
import project_planning as pp
import auth_policy

class DependencyQueueTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY,project_id,queue_id,adoption_version,package_id,binding_digest,spec_digest,actor,created_at); CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);")
        dq.ensure_schema(self.c)
        self.src=dict(project_id='p',adoption_version=1,package_id='P',binding_digest='b',spec_digest=pp.digest('fixture specification'),prerequisites=[dict(package_id='R',version=1,digest='r')])
        self.body=dict(adoption_version=1,package_id='P',binding_digest='b',source_digest=pp.digest(self.src),confirmation='QUEUE DEPENDENT WORK PACKAGE')
        for obj,name,value in [(dq,'source',self.src),(pp,'check_role',None),(dq.wb,'source',{}),(dq.sc,'spec_for','fixture specification')]:
            p=patch.object(obj,name,return_value=value);p.start();self.addCleanup(p.stop)
    def test_pin_and_revalidate(self):
        dq.record(self.c,'p','developer',self.body,'j','q','fixture specification','t')
        row=self.c.execute('SELECT * FROM studio_coding_bindings').fetchone()
        self.assertEqual(dq.checked_package(self.c,'p',row),{})
        self.src['prerequisites'][0]['version']=2
        with self.assertRaises(ValueError):dq.checked_package(self.c,'p',row)
        with self.assertRaises(ValueError):dq.checked_package(self.c,'other',row)
    def test_confirmation_and_permission(self):
        for change in (dict(source_digest='bad'),dict(confirmation='yes'),dict(adoption_version=True)):
            with self.assertRaises(ValueError):dq.request(self.c,'p','developer',dict(self.body,**change))
        with patch.object(pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):dq.request(self.c,'p','viewer',self.body)
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/engineering/dependent-coding'),('p','write'))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_queue_sources').fetchone()[0],0)
