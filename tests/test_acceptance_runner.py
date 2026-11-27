import hashlib,json,os,sqlite3,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import acceptance_runner as r
import auth_store

def contract(args=None,assertion=None):
    return dict(runtime='python',module='main',function='add',arguments=[2,3] if args is None else args,
                assertion=dict(operator='equals',value=5) if assertion is None else assertion)
def proposal(source,path='main.py'):
    return dict(files=[dict(path=path,content=source,sha256=hashlib.sha256(source.encode()).hexdigest())])
def obs(value):return json.dumps(dict(observation='returned',value=value)).encode()

class RunnerTests(unittest.TestCase):
    def test_exact_module_target(self):
        self.assertEqual(r.target(proposal('def add(a,b):return a+b'),contract())['path'],'main.py')
        for p in (proposal('def add(a,b):return a+b','nested/main.py'),proposal('from math import add'),
                  proposal('async def add(a,b):return a+b'),proposal('@decorator\ndef add(a,b):return a+b')):
            with self.assertRaises(ValueError):r.target(p,contract())
    def test_module_digest_mismatch(self):
        p=proposal('def add(a,b):return a+b');p['files'][0]['sha256']='bad'
        with self.assertRaises(ValueError):r.target(p,contract())
    def test_strict_json_equality(self):
        self.assertEqual(r.classify(obs(5),None,contract())['status'],'PASS')
        for v in (5.0,True,'5',None):
            self.assertEqual(r.classify(obs(v),None,contract())['status'],'FAIL')
    def test_exact_exception_only(self):
        x=contract(assertion=dict(operator='raises',exception='TypeError'))
        self.assertEqual(r.classify(b'{"observation":"raised","exception":"TypeError"}',None,x)['status'],'PASS')
        self.assertEqual(r.classify(b'{"observation":"raised","exception":"ValueError"}',None,x)['status'],'FAIL')
        self.assertEqual(r.classify(b'{"observation":"error","reason":"MODULE_OR_TARGET_ERROR"}',None,x)['status'],'ERROR')
    def test_no_observation_no_pass(self):
        for raw,error in [(b'',None),(b'PASS',None),(None,'TIMEOUT'),(None,'DOCKER_UNAVAILABLE'),(b'{"observation":"returned","value":5,"value":5}',None),(obs(5)+b'junk',None)]:
            result=r.classify(raw,error,contract())
            self.assertEqual(result['status'],'ERROR')
            self.assertFalse(result['executed'])
    def test_materialized_tamper_never_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'main.py').write_text('changed')
            meta=r.target(proposal('def add(a,b):return a+b'),contract())
            with patch.object(r,'transport') as t:
                with self.assertRaises(ValueError):r.execute_case(root,'image',dict(id='T',criterion_id='AC',kind='POSITIVE',execution=contract()),meta)
                t.assert_not_called()
    def test_explicit_confirmation_before_db(self):
        with self.assertRaises(PermissionError):r.run(None,None,'p','j','actor','a','b','c','d','no',image=None)
    def test_cli_audit_only_database_allows_actual_rbac(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            auth_store.ensure_schema(c)
            c.execute("INSERT INTO auth_users(id,password_hash) VALUES('reviewer','fixture'),('developer','fixture')")
            c.execute("INSERT INTO auth_memberships VALUES('reviewer','p','reviewer'),('developer','p','developer')")
            c.execute("CREATE TABLE engineering_test_plans(id INTEGER PRIMARY KEY)")
            c.execute("INSERT INTO engineering_test_plans VALUES(1)")
            c.commit()
            r.restrict_cli_database(c)
            r.pp.check_role(c,'p','reviewer','approve')
            with self.assertRaises(PermissionError):r.pp.check_role(c,'p','developer','approve')
            c.commit()
            self.assertEqual([x[0] for x in c.execute("SELECT outcome FROM auth_audit ORDER BY id")],['allowed','denied'])
            self.assertTrue(c.execute('PRAGMA database_list').fetchall())
            for sql in ("INSERT INTO engineering_test_plans VALUES(2)",
                        "UPDATE engineering_test_plans SET id=2","DELETE FROM engineering_test_plans",
                        "DELETE FROM auth_audit","UPDATE auth_memberships SET role='owner'",
                        "CREATE TABLE unsafe(id)","DROP TABLE engineering_test_plans","PRAGMA writable_schema=ON"):
                with self.assertRaises(sqlite3.DatabaseError):c.execute(sql)
            self.assertEqual([x[0] for x in c.execute("SELECT id FROM engineering_test_plans")],[1])
    def test_runner_two_real_rbac_checks_without_writer_lock_during_execution(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            auth_store.ensure_schema(c)
            c.execute("INSERT INTO auth_users(id,password_hash) VALUES('reviewer','fixture')")
            c.execute("INSERT INTO auth_memberships VALUES('reviewer','p','reviewer')")
            c.commit()
            r.restrict_cli_database(c)
            p=proposal('def add(a,b):return a+b')
            case=dict(id='T',criterion_id='AC',kind='POSITIVE',execution=contract())
            meta=r.target(p,case['execution'])
            source=dict(plan_digest='p1',source_digest='s1',assertion_contract_digest='a1',
                        sandbox_digest='b1',selected='B',git=dict(parent='base'))
            def materialize(db,pid,jid,lane,proposal,base,work):
                self.assertFalse(c.in_transaction)
                return r.vf._materialize_proposal(proposal,work),source['git']
            result=dict(case_id='T',executed=True,status='PASS')
            with patch.object(r,'current',return_value=(source,[case],p,[meta])), \
                 patch.object(r.sb,'materialize',side_effect=materialize), \
                 patch.object(r,'execute_case',return_value=result):
                report=r.run(c,None,'p','j','reviewer','p1','s1','a1','b1',
                             'RUN ACCEPTANCE ASSERTIONS j',image='python@sha256:'+'0'*64)
            self.assertEqual(report['report']['gate'],'PASS')
            self.assertFalse(report['report']['persisted'])
            self.assertEqual([x[0] for x in c.execute("SELECT outcome FROM auth_audit ORDER BY id")],['allowed','allowed'])
    def test_docker_command_is_fixed_and_isolated(self):
        cmd=r.vf._docker_cmd('image',Path('/tmp/work'),['python','-I','-B','-c',r.HARNESS,'{}'],'name')
        for x in ('--network','none','--read-only','--cap-drop','ALL','65534:65534','--memory','256m','--pids-limit','64','--pull','never'):
            self.assertIn(x,cmd)
        self.assertIn('type=bind,src=/tmp/work,dst=/work,readonly',cmd)

@unittest.skipUnless(os.getenv('ORBIT_ASSERTION_REAL_DOCKER')=='1','explicit CI real Docker probe')
class RealDockerProbe(unittest.TestCase):
    def check_case(self,source,x,status):
        p=proposal(source);meta=r.target(p,x)
        with tempfile.TemporaryDirectory() as d:
            root=r.vf._materialize_proposal(p,d)
            result=r.execute_case(root,os.environ['ORBIT_SANDBOX_PYTHON_IMAGE'],dict(id='T',criterion_id='AC',kind='POSITIVE',execution=x),meta)
            self.assertEqual(result['status'],status,result)
            self.assertEqual(result['executed'],status in ('PASS','FAIL'))
    def test_real_mismatch(self):
        self.check_case('def add(a,b):return a+b',contract(assertion=dict(operator='equals',value=6)),'FAIL')
    def test_real_early_exit_no_pass(self):
        self.check_case('def add(a,b):\n    import os\n    os._exit(0)\n',contract(),'ERROR')
    def test_real_import_exception_not_expected_exception(self):
        self.check_case('raise TypeError()\ndef add(a,b):return a+b',contract(assertion=dict(operator='raises',exception='TypeError')),'ERROR')
    def test_real_boolean_not_integer(self):
        self.check_case('def add(a,b):return True',contract(assertion=dict(operator='equals',value=1)),'FAIL')
if __name__=='__main__':unittest.main()
