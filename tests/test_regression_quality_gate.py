import copy,sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import regression_quality_gate as g

class RegressionGateTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("""PRAGMA foreign_keys=ON;
          CREATE TABLE projects(id PRIMARY KEY);CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY);
          CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);
          INSERT INTO projects VALUES('p');INSERT INTO studio_coding_bindings VALUES('j');""")
        g.registry.ensure_schema(self.c);g.ensure_schema(self.c);g.ensure_schema(self.c)
        self.src=dict(project_id='p',job_id='j',selected='B',git=dict(commit='candidate'))
        self.x=dict(runtime='python',module='main',function='add',arguments=[2,3],assertion=dict(operator='equals',value=5))
        self.cases=[dict(id='T',criterion_id='AC',kind='POSITIVE',execution=self.x)]
        self.targets=[dict(path='main.py',module_sha256='a'*64)]
        row=dict(case_id='T',criterion_id='AC',kind='POSITIVE',assertion_digest=g.pp.digest(self.x),
                 **self.targets[0],required=True,impacted=True,reason='DIRECT_CHANGE')
        self.m=dict(schema='orbit.impacted-test-mapping.v1',state='IMPACTED_TEST_MAPPING_READY',project_id='p',job_id='j',
                    source=dict(runner_source=self.src),selected_comparison='baseline_to_B',
                    mappings={'baseline_to_B':dict(cases=[row],case_count=1,required_count=1,impacted_count=1,
                       to_commit='candidate',full_regression_required=True)},
                    full_regression_required=True,selective_execution_authorized=False,**g.FLAGS)
        self.m['evidence_digest']=g.pp.digest(self.m)
        self.schedule=g.priority.schedule(self.m,self.src,self.cases,self.targets,'baseline_to_B',self.m['evidence_digest'])
        self.setup_result()
    def setup_result(self,passed=True):
        result=dict(case_id='T',criterion_id='AC',kind='POSITIVE',assertion_digest=g.pp.digest(self.x),**self.targets[0],
                    status='PASS' if passed else 'FAIL',executed=True,reason='ASSERTION_MATCH' if passed else 'ASSERTION_MISMATCH',
                    observation='returned',value_digest=g.pp.digest(5 if passed else 6))
        self.report=dict(schema='orbit.acceptance-runner-report.v1',source=self.src,actor='reviewer',image='python@sha256:'+'0'*64,
                         runtime='docker',network='none',workspace='read-only',results=[result],executed_count=1,case_count=1,
                         gate='PASS' if passed else 'BLOCK',persisted=False,**g.FLAGS)
        summary=g.registry.validate_report(self.report,self.src,self.cases,self.targets)
        e=dict(schema='orbit.assertion-run-receipt.v1',project_id='p',job_id='j',version=1,previous_digest=None,
               report=self.report,report_digest=g.pp.digest(self.report),summary=summary,created_at='stamp',**g.FLAGS)
        self.run=dict(digest=g.pp.digest(e),snapshot=e)
        self.r=dict(project_id='p',job_id='j',state='EXECUTION_RECORDED_PASS' if passed else 'EXECUTION_RECORDED_BLOCK',
                    current_receipt=self.run,latest_version=1,history=[self.run],**g.FLAGS)
        self.q=dict(project_id='p',job_id='j',state='EXECUTION_QUALITY_PASS' if passed else 'BLOCK',
                    checks={k:'PASS' if passed else 'BLOCK' for k in g.execution.CHECKS},findings=[] if passed else ['failed'],
                    receipts=dict(execution=self.run['digest'],runner_report=e['report_digest']),coverage=summary,selected='B',**g.FLAGS)
        self.q['evidence_digest']=g.pp.digest(self.q)
        self.trace=g.priority.evidence(self.schedule,['T'],self.report)
        self.receipt=g.make_receipt('p','j',self.run,self.trace,self.schedule,self.cases,self.targets,'stamp')
    def evaluate(self,receipt=True):
        return g.evaluate('p','j',self.q,self.r,self.m,self.src,self.cases,self.targets,self.receipt if receipt else None)
    def insert_run(self):
        self.c.execute('INSERT INTO engineering_assertion_runs VALUES(?,?,?,?,?)',
                       ('p','j',1,g.pr.canonical(self.run['snapshot']),self.run['digest']))
    def append(self):
        return g.append(self.c,'p','j',self.run,self.trace,self.schedule,self.cases,self.targets,'stamp')
    def test_pass_exact_full_coverage(self):
        v=self.evaluate();self.assertEqual(v['state'],'REGRESSION_QUALITY_PASS')
        self.assertTrue(all(x=='PASS' for x in v['checks'].values()))
        self.assertTrue(v['full_regression_required']);self.assertFalse(v['selective_execution_authorized'])
    def test_missing_priority_or_old_gate_block(self):
        v=self.evaluate(False);self.assertEqual(v['state'],'BLOCK')
        self.assertEqual(v['checks']['execution_quality'],'PASS')
        self.assertEqual(v['checks']['durable_priority_receipt'],'BLOCK')
        self.q['state']='BLOCK'
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_failed_actual_receipt_block(self):
        self.setup_result(False);v=self.evaluate()
        self.assertEqual(v['checks']['durable_priority_receipt'],'PASS')
        self.assertEqual(v['checks']['mandatory_regression'],'BLOCK')
        self.assertEqual(v['state'],'BLOCK')
    def test_tampered_or_incomplete_trace_block(self):
        for kind in ('digest','order','waiver','run'):
            original=copy.deepcopy(self.receipt)
            if kind=='digest':self.receipt['digest']='bad'
            else:
                s=self.receipt['snapshot']
                if kind=='order':s['priority']['attempted_order']=[]
                elif kind=='waiver':s['priority']['schedule']['full_regression_required']=False
                else:s['execution_receipt_digest']='bad'
                self.receipt['digest']=g.pp.digest(s)
            self.assertEqual(self.evaluate()['state'],'BLOCK')
            self.receipt=original
    def test_stale_mapping_or_execution_block(self):
        self.m['state']='BLOCK'
        self.assertEqual(self.evaluate()['state'],'BLOCK')
        self.m['state']='IMPACTED_TEST_MAPPING_READY'
        self.r.update(state='STALE',current_receipt=None)
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_durable_immutable_fk_and_duplicate(self):
        self.c.execute('BEGIN');self.insert_run()
        self.assertEqual(self.append(),self.receipt);self.c.commit()
        self.assertEqual(g.load(self.c,'p','j',1),self.receipt)
        for sql in ('UPDATE engineering_regression_priority_receipts SET digest="bad"',
                    'DELETE FROM engineering_regression_priority_receipts',
                    'INSERT OR REPLACE INTO engineering_regression_priority_receipts SELECT * FROM engineering_regression_priority_receipts'):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
            self.c.rollback()
        self.assertEqual(g.load(self.c,'p','j',1),self.receipt)
    def test_missing_persisted_execution_rejected(self):
        self.c.execute('BEGIN')
        with self.assertRaises(ValueError):self.append()
        self.c.rollback()
    def test_atomic_rollback_priority_audit_failure(self):
        self.c.execute("CREATE TRIGGER fault BEFORE INSERT ON auth_audit BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            with self.c:
                self.insert_run();self.append()
        self.assertEqual(self.c.execute('SELECT count(*) FROM engineering_assertion_runs').fetchone()[0],0)
        self.assertIsNone(g.load(self.c,'p','j',1))
    def test_authorizer_explicit_priority_persistence(self):
        g.runner.restrict_cli_database(self.c,persist=True)
        self.c.execute('BEGIN');self.insert_run()
        with self.assertRaises(sqlite3.DatabaseError):self.append()
        self.c.rollback()
        g.runner.restrict_cli_database(self.c,persist=True,persist_priority=True)
        self.c.execute('BEGIN');self.insert_run();self.append();self.c.commit()
        with self.assertRaises(sqlite3.DatabaseError):self.c.execute('DELETE FROM engineering_regression_priority_receipts')
    def test_guard_exact_digest(self):
        v=self.evaluate()
        with patch.object(g,'view',return_value=v):
            with self.assertRaises(ValueError):g.require_current(self.c,None,'p','j',v['evidence_digest'])
            self.c.execute('BEGIN')
            with self.assertRaises(ValueError):g.require_current(self.c,None,'p','j','old')
            self.assertEqual(g.require_current(self.c,None,'p','j',v['evidence_digest']),v)
if __name__=='__main__':unittest.main()
