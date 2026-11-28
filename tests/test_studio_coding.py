import sys
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import studio_coding as sc
import project_planning as pp

class StudioCodingTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("""CREATE TABLE projects(id PRIMARY KEY); CREATE TABLE coding_jobs(id PRIMARY KEY,project_id,spec);
        CREATE TABLE agent_queue(id PRIMARY KEY,project_id,coding_job_id,kind,actor,status);
        CREATE TABLE studio_work_packages(project_id,adoption_version,package_id,snapshot,digest,PRIMARY KEY(project_id,adoption_version,package_id));
        CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);""")
        sc.ensure_schema(self.c)
        import wbs_dependency_extension as ext
        ext.ensure_schema(self.c)
        self.snap=dict(deliverable_id='D',requirement='R',outcome='Outcome',package=dict(id='P',kind='implement',depends_on=[],action='Build'),acceptance=[dict(id='AC',text='Exact criterion')])
        self.digest=pp.digest(self.snap)
        import json
        self.c.execute('INSERT INTO studio_work_packages VALUES(?,?,?,?,?)',('p',1,'P',json.dumps(self.snap),self.digest))
        self.body=dict(adoption_version=1,package_id='P',binding_digest=self.digest,confirmation='QUEUE ADOPTED WORK PACKAGE')
        for obj,name,value in [(sc.binding,'source',self.snap),(pp,'check_role',None)]:
            p=patch.object(obj,name,return_value=value);p.start();self.addCleanup(p.stop)
    def test_bound_spec_queue_and_stale_rejection(self):
        spec=sc.request(self.c,'p','owner',self.body)
        self.c.execute('INSERT INTO coding_jobs VALUES(?,?,?)',('j','p',spec))
        self.c.execute('INSERT INTO agent_queue VALUES(?,?,?,?,?,?)',('q','p','j','coding','owner','running'))
        sc.record(self.c,'p','owner',self.body,'j','q',spec,'t')
        self.assertEqual(sc.validate(self.c,'p','j','q'),self.snap)
        self.assertEqual(sc.evidence(self.c,'p','j')['state'],'BOUND')
        with self.assertRaises(ValueError):sc.request(self.c,'p','owner',self.body)
        with self.assertRaises(ValueError):sc.validate(self.c,'other','j','q')
        self.c.execute("UPDATE coding_jobs SET spec='tampered'")
        with self.assertRaises(ValueError):sc.validate(self.c,'p','j','q')
        self.assertEqual(sc.evidence(self.c,'p','j')['state'],'STALE')
        self.c.execute('UPDATE coding_jobs SET spec=?',(spec,))
        with patch.object(sc.binding,'source',side_effect=ValueError('stale')):
            with self.assertRaises(ValueError):sc.validate(self.c,'p','j','q')
    def test_explicit_confirmation_and_dependency_gate(self):
        for change in (dict(confirmation='yes'),dict(binding_digest='bad'),dict(adoption_version=2)):
            with self.assertRaises(ValueError):sc.request(self.c,'p','owner',dict(self.body,**change))
        with patch.object(pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):sc.request(self.c,'p','viewer',self.body)
        self.snap['package']['depends_on']=['other']
        import json
        digest=pp.digest(self.snap)
        self.c.execute('UPDATE studio_work_packages SET snapshot=?,digest=?',(json.dumps(self.snap),digest))
        with self.assertRaisesRegex(ValueError,'Dependent'):sc.request(self.c,'p','owner',dict(self.body,binding_digest=digest))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM studio_coding_bindings').fetchone()[0],0)
