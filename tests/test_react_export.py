import copy
import unittest
from test_react_candidate_gate import proposal, Runner, IMAGE
from test_verification_factory import job
from react_candidate_gate import verify_react
from web_candidate_selection import decide, compare
from verified_pr import verified_bundle

class ReactExportTests(unittest.TestCase):
    def setUp(self):
        self.job=job(proposal(),proposal())
        self.report=verify_react(self.job,image=IMAGE,approval='RUN REACT SANDBOX job-abc',runner=Runner())
        self.decision=decide(self.job,self.report,selected='B',techlead='Human Lead',
            rationale='Both candidates passed the fixed render acceptance profile.',
            confirmation='SELECT DEV-B job-abc')
    def test_export_b(self):
        bundle=verified_bundle(self.job,self.report,decision=self.decision)
        self.assertEqual(bundle['selected'],'B')
        self.assertTrue(any('/candidate-B/Component.tsx' in f['path'] for f in bundle['files']))
    def test_wrong_profile(self):
        self.report['profile']='unknown'
        with self.assertRaises(ValueError): compare(self.job,self.report)
    def test_wrong_project(self):
        self.report['project_id']='wrong'
        with self.assertRaises(ValueError): compare(self.job,self.report)
    def test_failed_exit(self):
        self.report['lanes']['B']['steps'][0]['exit_code']=1
        with self.assertRaises(ValueError): verified_bundle(self.job,self.report,decision=self.decision)
    def test_changed_image(self):
        self.report['lanes']['B']['steps'][0]['image']='sha256:'+'b'*64
        with self.assertRaises(ValueError): verified_bundle(self.job,self.report,decision=self.decision)
    def test_missing_step(self):
        self.report['lanes']['B']['steps']=[]
        with self.assertRaises(ValueError): compare(self.job,self.report)
