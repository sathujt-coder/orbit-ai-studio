"""The code-delivery PR must never bypass verified evidence or modify app sources."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import verified_pr as vp
import verification_factory as vf
import web_candidate_selection as selection
from test_verification_factory import job, PY_IMG, FakeDocker


class FakeClient(vp.VerifiedCodePRClient):
    def __init__(self):
        self.requests = []
    def request(self, method, route, payload=None):
        self.requests.append((method, route, payload))
        if method == 'GET' and route.endswith('/branches/main'):
            return {'commit': {'sha': 'a' * 40}}
        if method == 'GET':
            return {'default_branch': 'main'}
        if route.endswith('/pulls'):
            return {'html_url': 'https://github.com/example/orbit/pull/2', 'number': 2}
        return {}


class VerifiedPRTests(unittest.TestCase):
    def setUp(self):
        self.job = job()
        self.report = vf.verify_job(self.job, python_image=PY_IMG, runner=FakeDocker(),
                                    approval='RUN SANDBOX job-abc')
        self.decision = selection.decide(self.job, self.report, selected='A', techlead='Human Lead',
            rationale='Candidate A passes all verification and is simpler to maintain.',
            confirmation='SELECT DEV-A job-abc')

    def test_verified_bundle_only_writes_candidate_prefix(self):
        bundle = vp.verified_bundle(self.job, self.report, decision=self.decision)
        self.assertEqual(len(bundle['files']), 3)
        self.assertTrue(all(x['path'].startswith('agent-proposals/job-abc/') for x in bundle['files']))
        self.assertTrue(all(not x['path'].startswith('.github/') for x in bundle['files']))
        self.assertNotIn('output',bundle['files'][-1]['content'])

    def test_draft_pr_does_not_merge_or_deploy(self):
        client = FakeClient()
        res = client.draft_pr('example/orbit', vp.verified_bundle(self.job, self.report, decision=self.decision))
        self.assertEqual(res['number'], 2)
        writes = [(method,route) for method,route,_ in client.requests if method in {'POST','PUT'}]
        self.assertEqual(sum(route.endswith('/pulls') for _,route in writes), 1)
        self.assertTrue(all('/merge' not in route and '/deployments' not in route for _,route in writes))
        self.assertTrue(all('/agent-proposals%2F' not in route for _,route in writes))
        for method, route, body in client.requests:
            if method == 'PUT':
                self.assertIn('/agent-proposals/job-abc/', route)
            if route.endswith('/pulls'):
                self.assertTrue(body['draft'])
                self.assertEqual(body['base'],'main')

    def test_forged_report_rejected(self):
        for mutate in (lambda r:r.update(gate='BLOCK'),
                       lambda r:r.update(approval='ui'),
                       lambda r:r['lanes']['B'].update(status='failed'),
                       lambda r:r['lanes']['A'].update(sha256='0'*64),
                       lambda r:r['lanes']['A']['steps'][0].update(executed=False),
                       lambda r:r['lanes']['A']['steps'][0].update(test_count=0)):
            fresh=json.loads(json.dumps(self.report))
            mutate(fresh)
            with self.subTest(mutate=str(mutate)),self.assertRaises(ValueError):
                vp.verified_bundle(self.job, fresh)

    def test_code_change_after_verification_rejected(self):
        self.job['proposal_b']['files'][0]['content']='def add(*args): return 0'
        with self.assertRaises(ValueError):
            vp.verified_bundle(self.job,self.report,decision=self.decision)

    def test_refuses_untrusted_target_path(self):
        bundle=vp.verified_bundle(self.job,self.report,decision=self.decision)
        bundle['files'][0]['path']='.github/workflows/ci.yml'
        client=FakeClient()
        with self.assertRaises(ValueError):
            client.draft_pr('example/orbit',bundle)
        self.assertEqual(sum(x[0]=='PUT' for x in client.requests),0)


if __name__ == '__main__': unittest.main()
