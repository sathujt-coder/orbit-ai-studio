import copy
import sqlite3
import unittest
from unittest.mock import patch
import security_threat_model as t
import auth_policy

class ThreatModelTests(unittest.TestCase):
    def setUp(self):
        s=t.security
        src=dict(**dict.fromkeys((*s.DIGESTS,'execution_digest','report_digest','regression_digest','retest_digest'),'a'*64),
                 selected='A',plan_version=1,execution_version=1)
        self.e=dict(schema='orbit.security-evidence.v1',project_id='p',job_id='j',state='SECURITY_EVIDENCE_READY',
            security_gate='BLOCK',source=src,policy_digest='b'*64,checks=dict.fromkeys(s.CHECKS,'PASS'),
            assessments=dict.fromkeys(s.ASSESSMENTS,'NOT_ASSESSED'),**s.FLAGS)
        self.seal()
    def seal(self):
        self.e.pop('evidence_digest',None);self.e['evidence_digest']=t.pp.digest(self.e)
    def evaluate(self):return t.evaluate('p','j',self.e)
    def block(self):self.assertEqual(self.evaluate()['state'],'BLOCK')
    def test_catalog_complete(self):
        c=t.catalog();self.assertEqual((len(c['assets']),len(c['boundaries']),len(c['threats']),len(c['requirements'])),(7,6,16,16))
        self.assertEqual({x['stride'] for x in c['threats']},set(t.STRIDE))
    def test_ready_is_not_approval(self):
        v=self.evaluate();self.assertEqual(v['state'],'THREAT_MODEL_READY');self.assertEqual(v['security_gate'],'BLOCK')
        self.assertEqual(v['candidate_analysis'],'NOT_ASSESSED');self.assertTrue(all(v[k] is False for k in t.FLAGS))
        self.assertTrue(all(x['verification_status']=='NOT_VERIFIED' and x['mandatory'] is True for x in v['requirements']))
        self.assertEqual(v,self.evaluate())
    def test_binding_changes_digest(self):
        old=self.evaluate();self.e['source']['execution_digest']='c'*64;self.seal()
        v=self.evaluate();self.assertNotEqual(v['evidence_digest'],old['evidence_digest']);self.assertEqual(v['catalog_digest'],old['catalog_digest'])
    def test_foreign_scope(self):
        self.e['project_id']='other';self.seal();self.block()
    def test_tampered_security_digest(self):
        self.e['evidence_digest']='0'*64;self.block()
    def test_stale_security(self):
        self.e['state']='BLOCK';self.seal();self.block()
    def test_forged_ready_check(self):
        self.e['checks']['current_retest']='BLOCK';self.seal();self.block()
    def test_missing_source(self):
        self.e['source']=None;self.seal();self.block();self.assertIsNone(self.evaluate()['source'])
    def test_invalid_binding(self):
        self.e['source']['candidate_digest']='invalid';self.seal();self.block()
    def test_false_assessment(self):
        self.e['assessments']['threat_model']='PASS';self.seal();self.block()
    def test_authorization_rejected(self):
        self.e['execution_authorized']=True;self.seal();self.block()
    def test_duplicate_threat(self):
        c=t.catalog();c['threats'].append(copy.deepcopy(c['threats'][0]))
        with self.assertRaises(ValueError):t.validate_catalog(c)
    def test_missing_requirement(self):
        c=t.catalog();c['requirements'].pop()
        with self.assertRaises(ValueError):t.validate_catalog(c)
    def test_invalid_boundary(self):
        c=t.catalog();c['threats'][0]['asset']='A06'
        with self.assertRaises(ValueError):t.validate_catalog(c)
    def test_no_transaction(self):
        with sqlite3.connect(':memory:') as c:
            with self.assertRaises(ValueError):t.view(c,'unused','p','j')
    def test_read_only_route(self):
        path='/api/projects/p/engineering/threat-model/j'
        self.assertEqual(auth_policy.scope(None,'GET',path),('p','read'))
        self.assertIsNone(auth_policy.scope(None,'POST',path))
        self.assertIsNone(auth_policy.scope(None,'GET',path+'/extra'))
