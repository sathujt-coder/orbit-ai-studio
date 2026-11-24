import copy
import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from test_product_requirements import document
import product_requirements as pr
import project_planning as plan
import auth_store
import auth_policy

class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.execute('PRAGMA foreign_keys=ON')
        self.c.executescript("CREATE TABLE projects(id TEXT PRIMARY KEY); INSERT INTO projects VALUES('p'),('q');")
        auth_store.ensure_schema(self.c);pr.ensure_schema(self.c);plan.ensure_schema(self.c)
        for user,role in [('owner','owner'),('developer','developer'),('reviewer','reviewer'),('viewer','viewer')]:
            auth_store.create_user(self.c,user,'planning-fixture-password');auth_store.grant(self.c,user,'p',role)
    def tearDown(self):self.c.close()
    def req(self,version=0,approve=True):
        row=pr.save(self.c,'p','owner',dict(expected_version=version,document=document()),'t')['current']
        if approve:row=pr.approve(self.c,'p','reviewer',dict(version=row['version'],digest=row['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS'),'t')['current']
        return row
    def source(self,row):
        return dict(requirements_version=row['version'],requirements_digest=row['digest'])
    def seed(self,row,version=0,actor='owner'):
        return plan.save(self.c,'p',actor,dict(self.source(row),expected_version=version,confirmation='CREATE PLAN DRAFT'),'t',seed=True)
    def save(self,row,d,version=1,actor='developer'):
        return plan.save(self.c,'p',actor,dict(self.source(row),expected_version=version,document=d),'t')
    def approval(self,row,p,actor='reviewer',**kw):
        body=dict(self.source(row),version=p['version'],digest=p['digest'],confirmation='APPROVE PROJECT PLAN');body.update(kw)
        return plan.approve(self.c,'p',actor,body,'t2')
    def estimated(self,d):
        d=copy.deepcopy(d)
        for task in d['tasks']:task['effort_minutes']=30 if task['kind']=='implement' else 10
        return d
    def test_approved_input_and_stale_snapshot(self):
        self.assertFalse(plan.view(self.c,'p')['input_ready'])
        row=self.req(approve=False)
        with self.assertRaises(ValueError):self.seed(row)
        row=pr.approve(self.c,'p','reviewer',dict(version=row['version'],digest=row['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS'),'t')['current']
        with self.assertRaises(ValueError):self.seed(dict(row,digest='wrong'))
        with self.assertRaises(ValueError):self.seed(dict(row,version=True))
        seeded=self.seed(row)
        self.assertTrue(seeded['input_ready']);self.assertEqual(seeded['analysis']['task_count'],4)
        self.assertEqual(seeded['analysis']['total_effort_minutes'],None)
        self.assertFalse(seeded['execution_ready'])
        p=self.save(row,self.estimated(seeded['current']['document']))['current']
        approved=self.approval(row,p);self.assertTrue(approved['execution_ready'])
        new=self.req(1,approve=False)
        stale=plan.view(self.c,'p')
        self.assertTrue(stale['stale']);self.assertFalse(stale['execution_ready']);self.assertFalse(stale['input_ready'])
        with self.assertRaises(ValueError):self.seed(row,2)
        with self.assertRaises(ValueError):self.approval(row,p)
        self.assertEqual(plan.latest(self.c,'p')['version'],2)
        new=pr.approve(self.c,'p','reviewer',dict(version=new['version'],digest=new['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS'),'t')['current']
        self.assertTrue(plan.view(self.c,'p')['stale'])
        self.assertFalse(self.seed(new,2)['execution_ready'])
        self.assertEqual(self.c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        self.assertEqual(list(self.c.execute('PRAGMA foreign_key_check')),[])
    def test_scope_graph_and_estimate_validation(self):
        row=self.req();d=self.seed(row)['current']['document']
        for edit in (
            lambda x:x['tasks'][0].update(requirements=['REQ-999']),
            lambda x:x['tasks'][1].update(depends_on=['TASK-999']),
            lambda x:x['tasks'][0].update(depends_on=['TASK-2']),
            lambda x:x['tasks'][1].update(depends_on=[]),
            lambda x:x['tasks'][0].update(depends_on=['TASK-1']),
            lambda x:x['tasks'][1].update(id='TASK-1'),
            lambda x:x['tasks'].pop(),
            lambda x:x['tasks'][0].update(effort_minutes=True),
            lambda x:x['tasks'][0].update(effort_minutes=0)):
            bad=copy.deepcopy(d);edit(bad)
            with self.assertRaises(ValueError):self.save(row,bad)
        valid=self.estimated(d);data=self.save(row,valid)
        self.assertEqual(data['analysis']['total_effort_minutes'],80)
        self.assertEqual(data['analysis']['dependency_lower_bound_minutes'],40)
        order=data['analysis']['execution_order']
        self.assertLess(order.index('TASK-1'),order.index('TASK-2'))
        self.assertLess(order.index('TASK-3'),order.index('TASK-4'))
        self.assertEqual(data['analysis']['traceability']['REQ-1'],dict(implement=['TASK-1'],verify=['TASK-2']))
        with self.assertRaises(ValueError):self.save(row,valid,1)
    def test_verification_must_follow_every_implementation(self):
        row=self.req();d=self.seed(row)['current']['document']
        d['tasks'].append(dict(id='TASK-5',title='Additional work',kind='implement',requirements=['REQ-1'],depends_on=[],effort_minutes=None))
        with self.assertRaises(ValueError):self.save(row,d)
        d['tasks'][1]['depends_on'].append('TASK-5')
        self.assertTrue(self.save(row,d)['analysis']['traceability']['REQ-1']['implement']==['TASK-1','TASK-5'])
    def test_approval_and_permissions(self):
        row=self.req()
        for actor in ('viewer','reviewer'):
            with self.assertRaises(PermissionError):self.seed(row,actor=actor)
        d=self.seed(row);p=d['current']
        with self.assertRaises(ValueError):self.approval(row,p)
        p=self.save(row,self.estimated(p['document']))['current']
        for actor in ('viewer','developer'):
            with self.assertRaises(PermissionError):self.approval(row,p,actor)
        with self.assertRaises(ValueError):self.approval(row,p,digest='bad')
        with self.assertRaises(ValueError):self.approval(row,p,confirmation='yes')
        self.assertTrue(self.approval(row,p)['execution_ready'])
        with self.assertRaises(ValueError):self.approval(row,p)
        self.assertIsNone(plan.latest(self.c,'q'))
        with self.assertRaises(PermissionError):plan.save(self.c,'q','viewer',{},'t')
        fresh=self.save(row,p['document'],2)
        self.assertFalse(fresh['execution_ready']);self.assertEqual(fresh['history'][1]['approved_by'],'reviewer')
    def test_routes_and_input_integrity(self):
        for method,suffix,role in [('GET','','read'),('POST','','write'),('POST','/seed','write'),('POST','/approve','approve')]:
            self.assertEqual(auth_policy.scope(self.c,method,'/api/projects/p/planning'+suffix),('p',role))
        self.assertIsNone(auth_policy.scope(self.c,'POST','/api/projects/p/planning/run'))
        row=self.req()
        self.c.execute("UPDATE product_requirements SET digest='bad' WHERE project_id='p'")
        self.assertFalse(plan.view(self.c,'p')['input_ready'])
        with self.assertRaises(ValueError):self.seed(row)
