import sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_assertion_registry as reg
import acceptance_runner as runner

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.addCleanup(self.c.close)
        self.c.executescript("""CREATE TABLE projects(id PRIMARY KEY);
          CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY);
          CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);
          INSERT INTO projects VALUES('p');INSERT INTO studio_coding_bindings VALUES('j');""")
        reg.ensure_schema(self.c)
        self.x=dict(runtime='python',module='main',function='add',arguments=[2,3],assertion=dict(operator='equals',value=5))
        self.cases=[dict(id='T',criterion_id='AC',kind='POSITIVE',execution=self.x)]
        self.targets=[dict(path='main.py',module_sha256='a'*64)]
        self.src=dict(project_id='p',job_id='j',plan_version=1,plan_digest='p1',source_digest='s1',
            assertion_contract_digest='a1',selected='B',candidate_digest='b'*64,git=dict(source_sha256='b'*64))
        self.plan=dict(digest='p1',snapshot=dict(schema=reg.tp.V2,source_digest='s1',assertion_contract_digest='a1',
            source=dict(candidates=dict(B=dict(digest='b'*64))),cases=self.cases))
        for obj,name,kw in ((reg.tp,'history',dict(return_value=[self.plan])),
                            (runner,'current',dict(side_effect=lambda *a:(self.src,self.cases,{},self.targets)))):
            p=patch.object(obj,name,**kw);p.start();self.addCleanup(p.stop)
    def report(self,status='PASS'):
        result=dict(case_id='T',criterion_id='AC',kind='POSITIVE',assertion_digest=reg.pp.digest(self.x),**self.targets[0])
        if status in ('PASS','FAIL'):
            result.update(status=status,executed=True,reason='ASSERTION_MATCH' if status=='PASS' else 'ASSERTION_MISMATCH',
                          observation='returned',value_digest=reg.pp.digest(5 if status=='PASS' else 6))
        else:result.update(status=status,executed=False,reason='TIMEOUT' if status=='ERROR' else 'TOTAL_TIMEOUT')
        return dict(schema='orbit.acceptance-runner-report.v1',source=self.src,actor='reviewer',image='python@sha256:'+'0'*64,
            runtime='docker',network='none',workspace='read-only',results=[result],executed_count=int(result['executed']),
            case_count=1,gate='PASS' if status=='PASS' else 'BLOCK',persisted=False,**reg.FLAGS)
    def append(self,v=0,report=None):
        self.c.execute('BEGIN')
        try:
            out=reg.append(self.c,'p','j',v,report or self.report(),self.src,self.cases,self.targets,'stamp')
            self.c.commit();return out
        except Exception:self.c.rollback();raise
    def view(self):return reg.view(self.c,None,'p','j')
    def test_chain_and_cas(self):
        self.assertEqual(self.view()['state'],'AWAITING_EXECUTION')
        a=self.append();b=self.append(1)
        self.assertEqual(b['snapshot']['previous_digest'],a['digest'])
        self.assertEqual(self.view()['history'],[a,b])
        with self.assertRaises(ValueError):self.append(1)
    def test_block_results_preserved(self):
        for i,status in enumerate(('FAIL','ERROR','NOT_EXECUTED')):
            self.append(i,self.report(status))
            self.assertEqual(self.view()['state'],'EXECUTION_RECORDED_BLOCK')
        self.assertEqual([x['snapshot']['report']['results'][0]['status'] for x in self.view()['history']],['FAIL','ERROR','NOT_EXECUTED'])
    def test_false_pass_missing_and_duplicate_rejected(self):
        for kind in ('unexecuted','wrong_value','missing','duplicate','wrong_module'):
            r=self.report()
            if kind=='unexecuted':r['results'][0]['executed']=False
            if kind=='wrong_value':r['results'][0]['value_digest']=reg.pp.digest(6)
            if kind=='missing':r['results']=[]
            if kind=='duplicate':r['results']*=2
            if kind=='wrong_module':r['results'][0]['module_sha256']='f'*64
            with self.assertRaises(ValueError):self.append(report=r)
        self.assertEqual(self.view()['latest_version'],0)
    def test_stale_and_historical_receipt(self):
        a=self.append()
        self.src=dict(self.src,selection_digest='changed')
        v=self.view();self.assertEqual(v['state'],'STALE')
        self.assertIsNone(v['current_receipt']);self.assertEqual(v['history'],[a])
    def test_immutable_sql_and_tamper(self):
        self.append()
        for sql in ("UPDATE engineering_assertion_runs SET digest='bad'",
                    "DELETE FROM engineering_assertion_runs",
                    "INSERT OR REPLACE INTO engineering_assertion_runs SELECT * FROM engineering_assertion_runs"):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
            self.c.rollback()
        self.c.execute('DROP TRIGGER engineering_assertion_run_no_update')
        self.c.execute("UPDATE engineering_assertion_runs SET digest='bad'")
        self.assertEqual(self.view()['state'],'BLOCK')
    def test_atomic_audit_rollback(self):
        self.c.execute("CREATE TRIGGER bad_audit BEFORE INSERT ON auth_audit BEGIN SELECT RAISE(ABORT,'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.append()
        self.assertEqual(self.view()['latest_version'],0)
    def test_cli_authorizer_only_explicit_registry_insert(self):
        runner.restrict_cli_database(self.c)
        with self.assertRaises(sqlite3.DatabaseError):self.append()
        runner.restrict_cli_database(self.c,persist=True)
        self.append()
        with self.assertRaises(sqlite3.DatabaseError):self.c.execute('DELETE FROM engineering_assertion_runs')
        self.assertEqual(self.view()['latest_version'],1)
    def test_historical_plan_binding(self):
        self.append()
        self.plan['digest']='other'
        self.assertEqual(self.view()['state'],'BLOCK')
if __name__=='__main__':unittest.main()
