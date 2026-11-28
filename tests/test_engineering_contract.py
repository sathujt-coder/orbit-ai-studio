import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_contract as ec
import project_planning as pp
import dependency_graph as dg
import auth_policy

class EngineeringContractTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("CREATE TABLE studio_work_packages(project_id,adoption_version,package_id,snapshot,digest,PRIMARY KEY(project_id,adoption_version,package_id)); CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);")
        ec.ensure_schema(self.c)
        import wbs_dependency_extension as ext
        ext.ensure_schema(self.c)
        self.package=dict(id='P',kind='implement',depends_on=[],criteria=['AC'],action='Build')
        self.snap=dict(adoption_version=1,adoption_digest='a',bundle_digest='b',requirements_digest='r',wbs_digest='w',deliverable_id='D',requirement='R',outcome='O',package=self.package,acceptance=[dict(id='AC',text='Exact criterion')])
        self.graph=dg.analyze([dict(id='P',depends_on=[],effort_minutes=15)])
        self.w=dict(adoption=dict(current=dict(snapshot=dict(bundle=dict(dependency_graph=self.graph,wbs=dict(document=dict(deliverables=[dict(packages=[self.package])])))))))
        for obj,name,value in [(ec.wb,'source',self.snap),(ec.wbs,'view',self.w),(pp,'check_role',None)]:
            p=patch.object(obj,name,return_value=value);p.start();self.addCleanup(p.stop)
        self.persist()
    def persist(self):
        self.c.execute('INSERT OR REPLACE INTO studio_work_packages VALUES(?,?,?,?,?)',('p',1,'P',json.dumps(self.snap),pp.digest(self.snap)))
    def test_confirmation_and_tamper(self):
        src=ec.source(self.c,'p','P')
        body=dict(adoption_version=1,package_id='P',expected_version=0,source_digest=pp.digest(src),confirmation='CONFIRM ENGINEERING CONTRACT')
        self.assertFalse(ec.confirm(self.c,'p','reviewer',body,'t')['execution_authorized'])
        self.assertEqual(ec.view(self.c,'p')['contracts'][0]['state'],'CONFIRMED')
        with self.assertRaises(ValueError):ec.confirm(self.c,'p','reviewer',body,'t')
        self.c.execute("UPDATE engineering_contracts SET snapshot='{}'")
        self.assertEqual(ec.view(self.c,'p')['contracts'][0]['state'],'INVALID')
    def test_graph_mismatch_and_scope(self):
        self.graph['edges']=[dict(source='X',target='P')]
        with self.assertRaises(ValueError):ec.source(self.c,'p','P')
        with self.assertRaises(ValueError):ec.source(self.c,'other','P')
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/engineering/contracts/confirm'),('p','approve'))
    def test_dependent_and_stale(self):
        self.package['depends_on']=['X']
        self.w['adoption']['current']['snapshot']['bundle']['wbs']['document']['deliverables'][0]['packages'].append(dict(id='X',depends_on=[]))
        graph=dg.analyze([dict(id='X',depends_on=[],effort_minutes=15),dict(id='P',depends_on=['X'],effort_minutes=15)])
        self.w['adoption']['current']['snapshot']['bundle']['dependency_graph']=graph
        self.persist()
        src=ec.source(self.c,'p','P')
        self.assertEqual(src['structural_eligibility'],'BLOCK')
        with self.assertRaises(ValueError):ec.confirm(self.c,'p','reviewer',dict(adoption_version=1,package_id='P',expected_version=0,source_digest=pp.digest(src),confirmation='CONFIRM ENGINEERING CONTRACT'),'t')
        self.c.execute("UPDATE studio_work_packages SET digest='bad'")
        self.assertEqual(ec.view(self.c,'p')['contracts'][0]['state'],'STALE')
