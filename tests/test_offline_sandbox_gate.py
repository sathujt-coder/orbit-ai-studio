import json,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'backend')]
import offline_sandbox_gate as g
from test_verification_factory import job,proposal_py,PY_IMG
class OfflineSandboxTests(unittest.TestCase):
    def fixture(self):
        j=job()
        j['manifest']['candidate_files']={k:[{'path':f['path'],'sha256':f['sha256']} for f in j['proposal_'+k.lower()]['files']] for k in 'AB'}
        return j
    def test_reject_unsafe(self):
        for text in ('import os\n def add(a,b): return a+b','def add(a,b): return eval("1")','def add(a,b):\n while True: pass','def add(a,b): return a**b'):
            with self.assertRaises((ValueError,SyntaxError)):g.narrow_check(text,False)
    def test_gate_and_independent_contract(self):
        calls=[]
        def runner(argv,**kwargs):
            calls.append(argv)
            self.assertIn('--network',argv)
            self.assertEqual(argv[argv.index('--network')+1],'none')
            if 'unittest' in argv:return subprocess.CompletedProcess(argv,0,'','Ran 1 test in 0.001s\nOK')
            return subprocess.CompletedProcess(argv,0,json.dumps([a+b for a,b in g.CASES]),'')
        result=g.verify(self.fixture(),PY_IMG,'RUN OFFLINE SANDBOX job-abc',runner)
        self.assertEqual(result['gate'],'PASS')
        self.assertEqual(len(calls),4)
        self.assertTrue(all(x['steps'][1]['test_count']==10 for x in result['lanes'].values()))
    def test_independent_failure_blocks(self):
        def runner(argv,**kwargs):
            return subprocess.CompletedProcess(argv,0,'[]' if 'unittest' not in argv else 'Ran 1 test in 0.001s\nOK','')
        self.assertEqual(g.verify(self.fixture(),PY_IMG,'RUN OFFLINE SANDBOX job-abc',runner)['gate'],'BLOCK')
    def test_confirmation_required(self):
        with self.assertRaises(PermissionError):g.verify(self.fixture(),PY_IMG,'wrong')

    def test_safe_diagnostics(self):
        step={'step':'python_tests','image':PY_IMG,'executed':True,'passed':False,'exit_code':1,'test_count':1,'output':'NameError: secret model text\nFAILED (errors=1)'}
        d=g.sanitized(step)
        self.assertEqual(d['diagnostic'],'NameError')
        self.assertEqual(d['failure_counts'],{'errors':1})
        self.assertNotIn('secret',json.dumps(d))
    def test_repair_keeps_passing_lane_and_binds_hash(self):
        j=self.fixture()
        def runner(argv,**kwargs):
            return subprocess.CompletedProcess(argv,0,json.dumps([a+b for a,b in g.CASES]) if 'unittest' not in argv else 'Ran 1 test in 0.001s\nOK','')
        report=g.verify(j,PY_IMG,'RUN OFFLINE SANDBOX job-abc',runner)
        report['gate']='BLOCK'
        report['lanes']['B'].update(status='blocked',steps=[],reason='only unittest import allowed')
        plan=g.repair_plan(j,report)
        self.assertTrue(plan['A']['reuse'])
        self.assertFalse(plan['B']['reuse'])
        self.assertIn('only unittest import',plan['B']['feedback'])
        report['lanes']['B']['sha256']='wrong'
        with self.assertRaises(ValueError):g.repair_plan(j,report)
    def test_infrastructure_failure_not_repaired(self):
        j=self.fixture()
        def runner(argv,**kwargs):
            return subprocess.CompletedProcess(argv,125,'','docker error')
        report=g.verify(j,PY_IMG,'RUN OFFLINE SANDBOX job-abc',runner)
        with self.assertRaisesRegex(ValueError,'infrastructure'):g.repair_plan(j,report)

    def test_static_diagnostics_show_file_rule_and_line(self):
        p=proposal_py()
        p=g.cf.validate_proposal({'files':[{'path':'main.py','content':'def add(a,b):\n    return a +\n'},
            {'path':'test_main.py','content':p['files'][1]['content']}]})
        f=g.preflight(p)
        self.assertTrue(any(x['path']=='main.py' and x['code']=='PYTHON_SYNTAX' and x['line']==2 for x in f))
        self.assertNotIn('return a +',json.dumps(f))
    def test_narrow_diagnostics_show_import_line(self):
        p=proposal_py()
        p=g.cf.validate_proposal({'files':[p['files'][0],{'path':'test_main.py','content':'import os\nimport unittest\n'}]})
        self.assertTrue(any(x['path']=='test_main.py' and x['code']=='NARROW_POLICY' and x['line']==1 for x in g.preflight(p)))
