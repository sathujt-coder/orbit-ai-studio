import copy
import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import product_requirements as pr
import auth_policy

def document():
    return dict(problem='Save useful links',goals=['Retrieve saved links'],users=['Readers'],
        scope=['Web'],out_of_scope=['Mobile'],assumptions=[],open_questions=[],
        requirements=[dict(id='REQ-1',kind='functional',description='Save link',priority='must',acceptance=['Saved link is listed']),
        dict(id='REQ-2',kind='nonfunctional',description='Project isolation',priority='must',acceptance=['Other project cannot read links'])],
        stories=[dict(id='US-1',actor='Reader',goal='Save links securely',benefit='Find links later',requirements=['REQ-1','REQ-2'])])

class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.c.row_factory=sqlite3.Row
        self.c.execute('PRAGMA foreign_keys=ON')
        self.c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)')
        self.c.executemany('INSERT INTO projects VALUES(?)',[('p',),('q',)])
        pr.ensure_schema(self.c)
    def tearDown(self):self.c.close()
    def save(self,version=0,doc=None):
        return pr.save(self.c,'p','author',dict(expected_version=version,document=doc if doc is not None else document()),'t')
    def approve(self,current,**overrides):
        body=dict(version=current['version'],digest=current['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS')
        body.update(overrides)
        return pr.approve(self.c,'p','reviewer',body,'t2')
    def test_revision_and_approval(self):
        d=self.save()
        self.assertFalse(d['planning_ready'])
        self.assertTrue(self.approve(d['current'])['planning_ready'])
        d2=self.save(1)
        self.assertFalse(d2['planning_ready'])
        self.assertEqual(d2['history'][1]['approved_by'],'reviewer')
        self.assertIsNone(pr.view(self.c,'q')['current'])
        with self.assertRaises(ValueError):self.approve(d['current'])
        with self.assertRaises(ValueError):self.save(1)
    def test_validation(self):
        for edit in (lambda d:d['requirements'].append(copy.deepcopy(d['requirements'][0])),
                     lambda d:d['stories'][0].update(requirements=['REQ-99']),
                     lambda d:d['stories'][0].update(requirements=['REQ-1']),
                     lambda d:d['requirements'][0].update(acceptance=[]),
                     lambda d:d['requirements'][1].update(kind='functional')):
            d=document();edit(d)
            with self.assertRaises(ValueError):self.save(doc=d)
    def test_gate(self):
        d=document();d['open_questions']=['Who approves?']
        row=self.save(doc=d)['current']
        with self.assertRaises(ValueError):self.approve(row)
        row=self.save(1)['current']
        with self.assertRaises(ValueError):self.approve(row,digest='wrong')
        with self.assertRaises(ValueError):self.approve(row,confirmation='yes')
        self.approve(row)
        with self.assertRaises(ValueError):self.approve(row)
    def test_scope(self):
        for method,path,role in [('GET','requirements','read'),('POST','requirements','write'),('POST','requirements/approve','approve')]:
            self.assertEqual(auth_policy.scope(self.c,method,'/api/projects/p/'+path),('p',role))
        self.assertIsNone(auth_policy.scope(self.c,'POST','/api/projects/p/requirements/extra'))
