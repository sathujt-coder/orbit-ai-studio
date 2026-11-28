import copy
import sqlite3
import unittest
import security_sast as s
import auth_policy
class SastTests(unittest.TestCase):
    def proposal(self,content,path='main.py'):
        return s.cf.validate_proposal({'files':[dict(path=path,content=content)]})
    def model(self,p):
        _,digest=s.manifest(p);c=s.threat.catalog()
        src=dict(**dict.fromkeys((*s.security.DIGESTS,'execution_digest','retest_digest','security_evidence_digest','policy_digest'),'a'*64))
        src['candidate_digest']=digest
        v=dict(schema='orbit.security-threat-model.v1',project_id='p',job_id='j',state='THREAT_MODEL_READY',security_gate='BLOCK',
            source=src,catalog_digest=s.pp.digest(c),candidate_analysis='NOT_ASSESSED',
            **{k:c[k] for k in ('assets','boundaries','threats','requirements')},**s.threat.FLAGS)
        v['evidence_digest']=s.pp.digest(v);return v
    def scan(self,content,path='main.py'):
        p=self.proposal(content,path);return s.evaluate('p','j',self.model(p),p)
    def rules(self,code):return {x['rule_id'] for x in self.scan(code)['findings']}
    def test_clean_baseline_never_security_pass(self):
        v=self.scan('def add(a,b):\n return a+b\n')
        self.assertEqual(v['state'],'SAST_BASELINE_READY');self.assertEqual(v['security_gate'],'BLOCK');self.assertEqual(v['scan_verdict'],'NO_RULE_MATCHES')
        self.assertTrue(all(v[k] is False for k in s.FLAGS))
    def test_dynamic_code(self):self.assertIn('SAST01',self.rules('eval(value)'))
    def test_alias_command(self):self.assertIn('SAST02',self.rules('from os import system as run\nrun(value)'))
    def test_deserialize_alias(self):self.assertIn('SAST03',self.rules('import pickle as p\np.loads(value)'))
    def test_sql_dynamic(self):self.assertIn('SAST04',self.rules('db.execute(f"select {x}")'))
    def test_sql_parameterized(self):self.assertNotIn('SAST04',self.rules('db.execute("select ?",(x,))'))
    def test_tls_disabled(self):self.assertIn('SAST05',self.rules('import requests as r\nr.get(url,verify=False)'))
    def test_dynamic_import(self):self.assertIn('SAST06',self.rules('from importlib import import_module as i\ni(name)'))
    def test_native_loading(self):self.assertIn('SAST07',self.rules('import ctypes as c\nc.CDLL(path)'))
    def test_template(self):self.assertIn('SAST08',self.rules('from flask import render_template_string as r\nr(x)'))
    def test_environment(self):self.assertIn('SAST09',self.rules('import os as o\nx=o.environ[key]'))
    def test_network(self):self.assertIn('SAST10',self.rules('import socket as s\ns.socket()'))
    def test_parse_error(self):self.assertIn('SAST90',self.rules('def :'))
    def test_unsupported(self):
        v=self.scan('const x=1;','main.ts');self.assertEqual(v['state'],'BLOCK');self.assertEqual(v['findings'][0]['rule_id'],'SAST91')
    def test_passive_only_blocks(self):self.assertEqual(self.scan('docs','README.md')['scan_verdict'],'BLOCK')
    def test_tampered_file(self):
        p=self.proposal('x=1');m=self.model(p);p['files'][0]['content']='x=2'
        self.assertIsNone(s.evaluate('p','j',m,p)['source'])
    def test_foreign_scope(self):
        p=self.proposal('x=1');self.assertEqual(s.evaluate('other','j',self.model(p),p)['state'],'BLOCK')
    def test_stale_model(self):
        p=self.proposal('x=1');m=self.model(p);m['state']='BLOCK';m.pop('evidence_digest');m['evidence_digest']=s.pp.digest(m)
        self.assertEqual(s.evaluate('p','j',m,p)['state'],'BLOCK')
    def test_digest_tamper(self):
        p=self.proposal('x=1');m=self.model(p);m['evidence_digest']='0'*64
        self.assertEqual(s.evaluate('p','j',m,p)['scan_verdict'],'NOT_ASSESSED')
    def test_no_source_leak_or_execution(self):
        code='raise RuntimeError("private-sentinel")\neval("private-sentinel")'
        v=self.scan(code);self.assertNotIn('private-sentinel',str(v));self.assertEqual(v['scan_verdict'],'BLOCK')
        self.assertEqual(v,self.scan(code))
    def test_no_transaction(self):
        with sqlite3.connect(':memory:') as c:
            with self.assertRaises(ValueError):s.view(c,'unused','p','j')
    def test_read_only_route(self):
        path='/api/projects/p/engineering/sast/j'
        self.assertEqual(auth_policy.scope(None,'GET',path),('p','read'));self.assertIsNone(auth_policy.scope(None,'POST',path))
