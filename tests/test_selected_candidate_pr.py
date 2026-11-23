"""The Tech Lead decision must control selected candidate PR export."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import verified_pr as vp
import web_candidate_selection as selection
from test_verification_factory import job, PY_IMG, FakeDocker
import verification_factory as vf

class Client(vp.VerifiedCodePRClient):
    def __init__(self): self.calls=[]
    def request(self,method,route,payload=None):
        self.calls.append((method,route,payload))
        if method=='GET' and route.endswith('/branches/main'): return {'commit':{'sha':'a'*40}}
        if method=='GET': return {'default_branch':'main'}
        if route.endswith('/pulls'): return {'html_url':'https://github.com/example/repo/pull/1','number':1}
        return {}

class SelectedCandidatePRTests(unittest.TestCase):
    def setUp(self):
        self.job=job()
        self.job['proposal_b']['files'][0]['content']='def add(a,b):\n    return a + b + 0\n'
        # Keep the proposal B integrity hash in sync with its content.
        from coding_factory import validate_proposal
        b=self.job['proposal_b']
        self.job['proposal_b']=validate_proposal({'summary':b['summary'],'files':[{'path':f['path'],'content':f['content']} for f in b['files']]})
        self.report=vf.verify_job(self.job,python_image=PY_IMG,runner=FakeDocker(),approval='RUN SANDBOX job-abc')
        self.decision=selection.decide(self.job,self.report,selected='B',techlead='Human Lead',
          rationale='Candidate B is chosen after independent verification and review.',
          confirmation='SELECT DEV-B job-abc')

    def test_missing_decision_rejected(self):
        with self.assertRaises(PermissionError): vp.verified_bundle(self.job,self.report)

    def test_b_is_exported_not_a(self):
        bundle=vp.verified_bundle(self.job,self.report,decision=self.decision)
        self.assertEqual(bundle['selected'],'B')
        self.assertTrue(any('/candidate-B/' in f['path'] for f in bundle['files']))
        self.assertFalse(any('/candidate-A/' in f['path'] for f in bundle['files']))
        self.assertIn('DEV-',bundle['files'][-1]['content'] if 'DEV-' in bundle['files'][-1]['content'] else 'DEV-B')

    def test_wrong_digest_rejected(self):
        d=copy.deepcopy(self.decision);d['selected_digest']='0'*64
        with self.assertRaises(ValueError): vp.verified_bundle(self.job,self.report,decision=d)

    def test_wrong_job_rejected(self):
        d=copy.deepcopy(self.decision);d['job_id']='other'
        with self.assertRaises(ValueError): vp.verified_bundle(self.job,self.report,decision=d)

    def test_forged_candidate_comparison_rejected(self):
        d=copy.deepcopy(self.decision);d['candidates']['B']['test_count']=1000
        with self.assertRaises(ValueError): vp.verified_bundle(self.job,self.report,decision=d)

    def test_draft_pr_writes_only_selected_b(self):
        bundle=vp.verified_bundle(self.job,self.report,decision=self.decision)
        client=Client();result=client.draft_pr('example/repo',bundle)
        self.assertEqual(result['number'],1)
        writes=[(m,p) for m,p,_ in client.calls if m=='PUT']
        self.assertTrue(writes)
        self.assertTrue(all('/candidate-B/' in p or p.endswith('/VERIFICATION.json') for _,p in writes))
        self.assertTrue(all('/candidate-A/' not in p for _,p in writes))
        self.assertTrue(any(p.endswith('/pulls') and v['draft'] is True for m,p,v in client.calls))

    def test_untrusted_path_fails_before_any_write(self):
        bundle=vp.verified_bundle(self.job,self.report,decision=self.decision)
        bundle['files'][0]['path']='agent-proposals/job-abc/candidate-A/injected.py'
        client=Client()
        with self.assertRaises(ValueError): client.draft_pr('example/repo',bundle)
        self.assertEqual([m for m,_,_ in client.calls if m in ('POST','PUT')],[])

if __name__=='__main__': unittest.main()
