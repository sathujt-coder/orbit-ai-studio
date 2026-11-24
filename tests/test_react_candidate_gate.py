import sys
from pathlib import Path
import subprocess
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from coding_factory import validate_proposal
from test_verification_factory import job
from react_candidate_gate import verify_react, plan_react
IMAGE='sha256:'+'a'*64

def proposal(source='export default () => <h1>Welcome ORBIT</h1>'):
    return validate_proposal({'summary':'React fixture','files':[{'path':'Component.tsx','content':source}]})

class Runner:
    def __init__(self,output='React component bundle and render: PASS',code=0):
        self.calls=[];self.output=output;self.code=code
    def __call__(self,argv,**kw):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv,self.code,self.output,'')

class ReactGateTests(unittest.TestCase):
    def test_both_lanes(self):
        r=Runner()
        result=verify_react(job(proposal(),proposal()),image=IMAGE,approval='RUN REACT SANDBOX job-abc',runner=r)
        self.assertEqual(result['gate'],'PASS')
        self.assertEqual(len(r.calls),2)
        self.assertTrue(all('--read-only' in a and '--network' in a for a in r.calls))
    def test_no_marker_blocks(self):
        self.assertEqual(verify_react(job(proposal(),proposal()),image=IMAGE,approval='RUN REACT SANDBOX job-abc',runner=Runner(''))['gate'],'BLOCK')
    def test_failed_exit_blocks(self):
        self.assertEqual(verify_react(job(proposal(),proposal()),image=IMAGE,approval='RUN REACT SANDBOX job-abc',runner=Runner(code=1))['gate'],'BLOCK')
    def test_no_approval(self):
        r=Runner()
        with self.assertRaises(PermissionError):
            verify_react(job(proposal(),proposal()),image=IMAGE,approval='yes',runner=r)
        self.assertEqual(r.calls,[])
    def test_privileged_pattern(self):
        self.assertIn('PRIVILEGED_CODE_PATTERN',plan_react(proposal('import x from "child_process"'))['blockers'])
    def test_extra_file_blocks(self):
        p=validate_proposal({'files':[{'path':'Component.tsx','content':'export default ()=>null'},{'path':'package.json','content':'{}'}]})
        self.assertIn('EXACT_SINGLE_COMPONENT_REQUIRED',plan_react(p)['blockers'])
