import copy
import sqlite3
import unittest
from unittest.mock import patch
import security_evidence as s
import auth_policy

class SecurityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.source=dict(project_id='p',job_id='j',plan_version=1,selected='A',git={'source_sha256':'a'*64},**dict.fromkeys(s.DIGESTS,'a'*64))
        self.report=dict(schema='orbit.acceptance-runner-report.v1',source=self.source,runtime='docker',network='none',workspace='read-only',
            image='python@sha256:'+'b'*64,gate='PASS',case_count=1,executed_count=1,results=[dict(status='PASS',executed=True)],**s.retest.FLAGS)
        self.snap=dict(schema='orbit.assertion-run-receipt.v1',project_id='p',job_id='j',version=1,report=self.report,**s.retest.FLAGS)
        self.gate=dict(schema='orbit.defect-retest-quality.v1',project_id='p',job_id='j',state='RETEST_QUALITY_PASS',
            checks=dict.fromkeys(s.retest.CHECKS,'PASS'),regression_digest='c'*64,automatic_closure=False,quality_gate_override=False,**s.retest.FLAGS)
    def seal(self):
        self.snap['report_digest']=s.pp.digest(self.report)
        self.receipt=dict(snapshot=self.snap,digest=s.pp.digest(self.snap))
        self.gate['execution_digest']=self.receipt['digest']
        self.gate.pop('evidence_digest',None)
        self.gate['evidence_digest']=s.pp.digest(self.gate)
    def evaluate(self):
        return s.evaluate('p','j',self.source,self.receipt,self.gate)
    def check_block(self):
        self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_ready_is_not_security_pass(self):
        self.seal();v=self.evaluate()
        self.assertEqual(v['state'],'SECURITY_EVIDENCE_READY');self.assertEqual(v['security_gate'],'BLOCK')
        self.assertTrue(all(x=='NOT_ASSESSED' for x in v['assessments'].values()))
        self.assertTrue(all(v[k] is False for k in s.FLAGS))
        self.assertEqual(v,self.evaluate())
        self.assertNotIn('results',str(v));self.assertNotIn('python@sha256',str(v))
    def test_foreign_scope(self):
        self.source['project_id']='other';self.seal();self.check_block()
    def test_candidate_mismatch(self):
        self.source['git']['source_sha256']='f'*64;self.seal();self.check_block()
    def test_invalid_receipt(self):
        self.seal();self.receipt['digest']='0'*64;self.check_block()
    def test_mutable_image(self):
        self.report['image']='python:latest';self.seal();self.check_block()
    def test_network_enabled(self):
        self.report['network']='bridge';self.seal();self.check_block()
    def test_changed_command_policy(self):
        self.seal()
        with patch.object(s.runner.vf,'_docker_cmd',return_value=['docker','run','--privileged']):self.check_block()
    def test_stale_gate(self):
        self.gate['state']='BLOCK';self.seal();self.check_block()
    def test_forged_gate_digest(self):
        self.seal();self.gate['evidence_digest']='0'*64;self.check_block()
    def test_wrong_execution_binding(self):
        self.seal();self.gate['execution_digest']='d'*64
        self.gate.pop('evidence_digest');self.gate['evidence_digest']=s.pp.digest(self.gate);self.check_block()
    def test_no_authorization(self):
        self.report['execution_authorized']=True;self.seal();self.check_block()
    def test_missing_current_source(self):
        with sqlite3.connect(':memory:') as c:
            c.execute('BEGIN')
            with patch.object(s.runner,'current',side_effect=ValueError('private path or secret')):
                v=s.view(c,'unused','p','j')
            self.assertEqual(v['state'],'BLOCK');self.assertIsNone(v['source']);self.assertNotIn('secret',str(v['source']))
    def test_no_transaction(self):
        with sqlite3.connect(':memory:') as c:
            with self.assertRaisesRegex(ValueError,'transaction'):s.view(c,'unused','p','j')
    def test_read_only_route(self):
        path='/api/projects/p/engineering/security-evidence/j'
        self.assertEqual(auth_policy.scope(None,'GET',path),('p','read'))
        self.assertIsNone(auth_policy.scope(None,'POST',path))
        self.assertIsNone(auth_policy.scope(None,'GET',path+'/extra'))
