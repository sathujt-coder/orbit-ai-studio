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

    def executable(self,v=0):
        b=self.body(v)
        for x in b['cases']:
            x['execution']=dict(runtime='python',module='main',function='add',arguments=[2,3],
                                assertion=dict(operator='equals',value=5))
        return b
    def test_legacy_upgrade_preserves_hash_and_no_execution(self):
        old=self.record();before=self.view()
        self.assertEqual(before['assertion_status'],'NOT_READY')
        self.record(self.executable(1));after=self.view()
        self.assertEqual(after['history'][0],before['history'][0])
        e=after['history'][1]['snapshot']
        self.assertEqual(e['previous_digest'],old['digest'])
        self.assertEqual(e['schema'],tp.V2)
        self.assertEqual(after['assertion_contract_digest'],tp.contract_digest(e))
        self.assertEqual(after['assertion_status'],'ASSERTION_CONTRACT_READY')
        self.assertEqual(after['execution_status'],'NOT_EXECUTED')
        self.assertTrue(all(after[k] is False for k in tp.FLAGS))
    def test_mixed_and_downgrade_rejected(self):
        b=self.executable();del b['cases'][0]['execution']
        with self.assertRaises(ValueError):self.record(b)
        self.record(self.executable())
        with self.assertRaises(ValueError):self.record(self.body(1))
        self.assertEqual(self.view()['latest_version'],1)
    def test_shell_and_unsafe_target_rejected(self):
        for key,value in [('runtime','shell'),('module','../main'),('module','os.path'),('function','__import__'),('function','x;ls'),('command','echo unsafe')]:
            b=self.executable();b['cases'][0]['execution'][key]=value
            with self.assertRaises(ValueError):self.record(b)
        self.assertEqual(self.view()['latest_version'],0)
    def test_exception_allowlist_and_exact_fields(self):
        b=self.executable();a=b['cases'][0]['execution']
        a['assertion']=dict(operator='raises',exception='TypeError')
        self.record(b)
        for value in [dict(operator='raises',exception='BaseException'),dict(operator='equals',value=5,command='ls'),dict(operator='eval',value='5')]:
            b=self.executable(1);b['cases'][0]['execution']['assertion']=value
            with self.assertRaises(ValueError):self.record(b)
    def test_bounded_json_data(self):
        deep=0
        for _ in range(12):deep=[deep]
        for value in [float('nan'),float('inf'),2**60,deep,'x'*3000,list(range(300)),{1:'bad'},'\ud800']:
            b=self.executable();b['cases'][0]['execution']['arguments']=[value]
            with self.assertRaises(ValueError):self.record(b)
    def test_assertion_digest_changes_and_stale_blocks(self):
        self.record(self.executable());first=self.view()
        b=self.executable(1);b['cases'][0]['execution']['assertion']['value']=6
        self.record(b);second=self.view()
        self.assertNotEqual(first['assertion_contract_digest'],second['assertion_contract_digest'])
        self.src['report_digest']='changed'
        stale=self.view()
        self.assertEqual(stale['state'],'STALE')
        self.assertEqual(stale['assertion_status'],'NOT_READY')
        self.assertIsNone(stale['assertion_contract_digest'])
        self.assertEqual(stale['history'],second['history'])
    def test_tampered_contract_digest_blocks_even_with_rehashed_snapshot(self):
        self.record(self.executable())
        e=self.view()['history'][0]['snapshot']
        e['assertion_contract_digest']='0'*64
        self.c.execute('DROP TRIGGER engineering_test_plan_no_update')
        self.c.execute('UPDATE engineering_test_plans SET snapshot=?,digest=?',(tp.pr.canonical(e),tp.pp.digest(e)))
        self.assertEqual(self.view()['state'],'BLOCK')
    def test_executable_requires_role_and_exact_source(self):
        with patch.object(tp.pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.record(self.executable())
        b=self.executable();b['source_digest']='stale'
        with self.assertRaises(ValueError):self.record(b)
        self.assertEqual(self.view()['latest_version'],0)

if __name__=='__main__':unittest.main()
