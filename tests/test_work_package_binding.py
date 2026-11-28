import sys
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import work_package_binding as b
import project_planning as pp
import auth_policy

class WorkPackageBindingTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("CREATE TABLE projects(id PRIMARY KEY); CREATE TABLE planning_adoptions(project_id,version,PRIMARY KEY(project_id,version)); CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);")
        b.ensure_schema(self.c)
        doc={'deliverables':[{'id':'D','requirement':'R','outcome':'Outcome','acceptance':[{'id':'AC','text':'Exact criterion'}],'packages':[{'id':'P','kind':'implement','criteria':['AC'],'depends_on':[],'action':'Build','output':'File','evidence':'Test'}]}]}
        bundle={'prd':{'version':1,'digest':'prd'},'wbs':{'version':2,'digest':pp.digest(doc),'document':doc}}
        snap={'bundle':bundle}
        self.row={'version':3,'digest':pp.digest(snap),'bundle_digest':pp.digest(bundle),'review_id':'review','evidence_digest':'review-digest','snapshot':snap}
        self.w={'adoption':{'status':'adopted','stale':False,'current':self.row}}
        self.body={'adoption_version':3,'bundle_digest':self.row['bundle_digest'],'package_id':'P','confirmation':'BIND ADOPTED WORK PACKAGE'}
        for target,name,value in [(b.wbs,'view',self.w),(pp,'require_input',{'version':1}),(pp,'check_role',None)]:
            p=patch.object(target,name,return_value=value);p.start();self.addCleanup(p.stop)
    def test_explicit_binding_and_staleness(self):
        result=b.bind(self.c,'p','owner',self.body,'t')
        self.assertEqual(result['snapshot']['acceptance'],[{'id':'AC','text':'Exact criterion'}])
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(b.view(self.c,'p',self.w)['bindings'][0]['state'],'BOUND')
        self.assertEqual(b.view(self.c,'other',self.w)['bindings'],[])
        with self.assertRaises(ValueError):b.bind(self.c,'p','owner',self.body,'t')
        self.w['adoption'].update(status='stale',stale=True)
        self.assertEqual(b.view(self.c,'p',self.w)['bindings'][0]['state'],'STALE')
    def test_reject_wrong_version_digest_package_and_role(self):
        for change in [{'adoption_version':2},{'bundle_digest':'wrong'},{'package_id':'missing'},{'confirmation':'yes'}]:
            with self.assertRaises(ValueError):b.bind(self.c,'p','owner',dict(self.body,**change),'t')
        with patch.object(pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):b.bind(self.c,'p','viewer',self.body,'t')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM studio_work_packages').fetchone()[0],0)
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/studio/work-packages/bind'),('p','write'))
