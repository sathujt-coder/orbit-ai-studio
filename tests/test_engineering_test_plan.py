import sqlite3
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_test_plan as tp
import auth_policy

class AcceptanceTestPlanTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.addCleanup(self.c.close)
        self.c.executescript("""CREATE TABLE projects(id PRIMARY KEY);
          CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY);
          CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);
          INSERT INTO projects VALUES('p');INSERT INTO studio_coding_bindings VALUES('j');""")
        tp.ensure_schema(self.c)
        self.src=dict(project_id='p',job_id='j',acceptance=[dict(id='AC1'),dict(id='AC2')],report_digest='one')
        for obj,name,kw in ((tp.quality,'lineage',dict(return_value=['j'])),
                            (tp.qa,'source',dict(side_effect=lambda *a:self.src)),
                            (tp.pp,'check_role',dict(return_value=None))):
            p=patch.object(obj,name,**kw);p.start();self.addCleanup(p.stop)
    def body(self,v=0):
        return dict(source_digest=tp.pp.digest(self.src),expected_version=v,
            confirmation='CONFIRM ACCEPTANCE TEST PLAN j',
            cases=[dict(x,scenario='Explicit scenario for '+x['id'],expected='Expected observable result for '+x['id']) for x in tp.template(self.src)])
    def record(self,b=None):
        return tp.record(self.c,'p','j','reviewer',b or self.body(),'stamp')
    def view(self):return tp.view(self.c,'p','j')
    def test_exact_coverage_and_versions(self):
        self.assertEqual(self.view()['state'],'AWAITING_TEST_PLAN')
        a=self.record();b=self.record(self.body(1));v=self.view()
        self.assertEqual(v['state'],'TEST_PLAN_COVERAGE_PASS')
        self.assertEqual(v['execution_status'],'NOT_EXECUTED')
        self.assertEqual(v['history'][1]['snapshot']['previous_digest'],a['digest'])
        self.assertEqual(v['history'][1]['digest'],b['digest'])
        self.assertEqual(v['history'][1]['snapshot']['coverage']['criteria_covered'],2)
        self.assertTrue(all(v[k] is False for k in tp.FLAGS))
    def test_missing_kind_rejected(self):
        b=self.body();b['cases'].pop()
        with self.assertRaises(ValueError):self.record(b)
        self.assertEqual(self.view()['latest_version'],0)
    def test_duplicate_unknown_and_empty_placeholder_rejected(self):
        for change in ('duplicate','unknown','empty'):
            b=self.body()
            if change=='duplicate':b['cases'][1]['id']=b['cases'][0]['id']
            if change=='unknown':b['cases'][0]['criterion_id']='unknown'
            if change=='empty':b['cases'][0]['scenario']=''
            with self.assertRaises(ValueError):self.record(b)
    def test_stale_source_and_version(self):
        b=self.body();self.record(b)
        with self.assertRaises(ValueError):self.record(b)
        self.src['report_digest']='new'
        self.assertEqual(self.view()['state'],'STALE')
        with self.assertRaises(ValueError):self.record(dict(b,expected_version=1))
    def test_immutable_and_tampered_history(self):
        self.record();self.c.commit()
        for sql in ("UPDATE engineering_test_plans SET digest='bad'","DELETE FROM engineering_test_plans",
                    "INSERT OR REPLACE INTO engineering_test_plans SELECT * FROM engineering_test_plans"):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
            self.c.rollback()
        self.c.execute('DROP TRIGGER engineering_test_plan_no_update')
        self.c.execute("UPDATE engineering_test_plans SET digest='bad'")
        self.assertEqual(self.view()['state'],'BLOCK')
    def test_atomic_audit_failure(self):
        self.c.execute("CREATE TRIGGER bad_audit BEFORE INSERT ON auth_audit BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.record()
        self.assertEqual(self.view()['latest_version'],0)
    def test_role_scope_and_confirmation(self):
        path='/api/projects/p/engineering/test-plans/j'
        self.assertEqual(auth_policy.scope(self.c,'GET',path),('p','read'))
        self.assertEqual(auth_policy.scope(self.c,'POST',path),('p','approve'))
        with patch.object(tp.pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.record()
        with self.assertRaises(ValueError):self.record(dict(self.body(),confirmation='yes'))
        self.src['project_id']='other'
        self.assertEqual(self.view()['state'],'BLOCK')
    def test_superseded_job_rejected(self):
        self.record()
        tp.quality.lineage.side_effect=ValueError('superseded')
        self.assertEqual(self.view()['state'],'STALE')
        with self.assertRaises(ValueError):self.record(self.body(1))

if __name__=='__main__':unittest.main()
