"""Final defect acceptance rejects malformed or substituted CI evidence."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import engineering_final_defect_acceptance as f

class FinalDefectAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.identity=dict(source_commit='a'*40,run_id='1',run_attempt='1')
        self.needs={job:dict(result='success',outputs={}) for _,job,_,_ in f.SPECS.values()}
        self.docs={}
        for key,(_,_,_,schema) in f.SPECS.items():
            self.docs[key]=dict(schema='orbit.'+schema+'.v1',**self.identity,gate='PASS',**dict.fromkeys(f.FLAGS,False))
            if key in f.COUNTS:self.docs[key]['tests']=f.COUNTS[key]
        self.docs['detection'].update(errors=0,failures=0)
        self.docs['final_regression'].update(full_regression_required=True,selective_execution_authorized=False)
        for key in f.REGRESSION:self.write(key)
        regression={k:self.hash(k) for k in f.REGRESSION}
        chain=f.sha(f.canonical(regression))
        self.docs['final_regression'].update(evidence_sha256=regression,evidence_chain_sha256=chain)
        self.needs['requirements-browser']['outputs']['final_regression_chain_sha256']=chain
        self.write('final_regression');self.write('detection')
        for key in f.DEFECT[1:-1]:
            for child,field,parent in f.LINKS:
                if child==key:self.docs[key][field]=self.hash(parent)
            self.write(key)
        rds=['1'*64,'2'*64];execution='e'*64
        items=[]
        for rd,n in zip(rds,(17,10)):
            chain=[];previous=None
            for i in range(n):
                s=dict(version=i+1,registration_digest=rd,previous_digest=previous,repair=dict(execution_digest=execution),**dict.fromkeys(f.FLAGS,False))
                previous=f.sha(f.canonical(s));chain.append(dict(snapshot=s,digest=previous))
            items.append(dict(state='CLOSED',latest=n==10,registration_digest=rd,history=chain))
        points={}
        for k in ('open','recovered','first_closed','reopened','same_run_rejected','recurrence','fresh','historical_closed','both_closed','stale','final'):
            g=dict(state='RETEST_QUALITY_PASS' if k in ('first_closed','both_closed','final') else 'BLOCK',
                   items=[dict(status='STALE_RETEST' if k=='stale' else 'CURRENT_CLOSURE') for _ in rds],
                   execution_digest=execution,checks={'closure':'PASS'})
            g['evidence_digest']=f.sha(f.canonical(g))
            points[k]=dict(gate=g)
        points['final']['tracking']=dict(items=items)
        self.docs['retest']['observations']=dict(**self.identity,executions=[dict(receipt=dict(digest=execution)) for _ in range(5)],
            points=points,registrations=rds,same_run_rejected=True,failed_verify_rejected=True,stale_digest_rejected=True,live_unchanged=True,
            reopen_race=dict(action='REOPEN',results=[dict(status='accepted'),dict(status='stale')],audit_before=0,audit_after=1))
        self.write('retest')
    def hash(self,key):
        _,job,output,_=f.SPECS[key];return self.needs[job]['outputs'][output]
    def write(self,key):
        _,job,output,_=f.SPECS[key];raw=f.canonical(self.docs[key])
        (self.path/f.filename(key)).write_bytes(raw);self.needs[job]['outputs'][output]=f.sha(raw)
    def validate(self):return f.validate(self.path,self.needs,self.identity)
    def test_valid_complete_chain(self):
        report=self.validate();self.assertEqual(report['gate'],'PASS');self.assertEqual(len(report['evidence_sha256']),9)
        self.assertEqual(len(report['regression_evidence_sha256']),6);self.assertEqual(report['coverage']['repair_receipts'],27)
        self.assertTrue(all(report[k] is False for k in f.FLAGS))
    def test_missing_artifact(self):
        (self.path/f.filename('retest')).unlink()
        with self.assertRaises(FileNotFoundError):self.validate()
    def test_raw_byte_mismatch(self):
        p=self.path/f.filename('retest');p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'Raw digest mismatch'):self.validate()
    def test_foreign_run_even_with_matching_hash(self):
        self.docs['retest']['run_id']='2';self.write('retest')
        with self.assertRaisesRegex(ValueError,'Run identity mismatch'):self.validate()
    def test_cross_link_mismatch(self):
        self.docs['retest']['positive_repair_sha256']='0'*64;self.write('retest')
        with self.assertRaisesRegex(ValueError,'Cross-artifact binding'):self.validate()
    def test_regression_chain_mismatch(self):
        self.needs['requirements-browser']['outputs']['final_regression_chain_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Six-artifact'):self.validate()
    def test_authorization_never_granted(self):
        self.docs['retest']['execution_authorized']=True;self.write('retest')
        with self.assertRaisesRegex(ValueError,'Unexpected authorization'):self.validate()
    def test_false_gate(self):
        self.docs['retest']['gate']='BLOCK';self.write('retest')
        with self.assertRaisesRegex(ValueError,'Gate BLOCK'):self.validate()
    def test_missing_checkpoint(self):
        self.docs['retest']['observations']['points'].pop('stale');self.write('retest')
        with self.assertRaisesRegex(ValueError,'Incomplete retest'):self.validate()
    def test_tampered_receipt_with_matching_artifact_digest(self):
        self.docs['retest']['observations']['points']['final']['tracking']['items'][0]['history'][0]['snapshot']['version']=7
        self.write('retest')
        with self.assertRaisesRegex(ValueError,'Immutable repair chain'):self.validate()
    def test_producer_failure(self):
        self.needs['validate']['result']='failure'
        with self.assertRaisesRegex(ValueError,'Producer not successful'):self.validate()
    def test_duplicate_reopen_audit(self):
        self.docs['retest']['observations']['reopen_race']['audit_after']=2;self.write('retest')
        with self.assertRaisesRegex(ValueError,'Concurrent REOPEN'):self.validate()
