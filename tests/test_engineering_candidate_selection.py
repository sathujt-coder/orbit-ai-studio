import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_candidate_selection as sel
import project_git_workspace as ws
import coding_factory as cf
import project_planning as pp
import auth_policy
from web_candidate_selection import _digest


class EngineeringSelectionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db=Path(temp.name)/'orbit.sqlite'
        self.c=sqlite3.connect(self.db)
        self.addCleanup(self.c.close)
        self.c.row_factory=sqlite3.Row
        self.c.executescript("""PRAGMA foreign_keys=ON;
            CREATE TABLE projects(id PRIMARY KEY);
            CREATE TABLE studio_coding_bindings(job_id PRIMARY KEY);
            CREATE TABLE coding_verifications(id,project_id,job_id,report_json);
            CREATE TABLE auth_audit(actor,project_id,action,outcome,created_at);
            INSERT INTO projects VALUES('project1'),('project2');
            INSERT INTO studio_coding_bindings VALUES('job123');""")
        sel.ensure_schema(self.c)
        self.pid='project1';self.jid='job123'
        a,b=[cf.validate_proposal({'summary':lane,'files':[
            {'path':'src/'+lane+'.js','content':'export const x = 1;'},
            {'path':lane+'.test.js','content':'const {test}=require("node:test");test("x",()=>{});'}]})
            for lane in ('a','b')]
        self.job=dict(id=self.jid,project_id=self.pid,status='ready',proposal_a=a,proposal_b=b,
            review_a=dict(reviewer='A',author='B',verdict='APPROVE',score=90),
            review_b=dict(reviewer='B',author='A',verdict='APPROVE',score=91),
            manifest=dict(mode='model',selected='A',files=[{k:f[k] for k in ('path','sha256')} for f in a['files']]))
        self.report=dict(project_id=self.pid,job_id=self.jid,gate='PASS',verdict='passed',
            approval='local_cli_explicit',sandbox=dict(runtime='docker',network='none'),lanes={})
        for lane,proposal in (('A',a),('B',b)):
            self.report['lanes'][lane]=dict(status='passed',sha256=_digest(proposal['files']),
                steps=[dict(step='javascript_tests',executed=True,passed=True,exit_code=0,test_count=2)])
        raw=json.dumps(self.report)
        self.c.execute('INSERT INTO coding_verifications VALUES(?,?,?,?)',('report1',self.pid,self.jid,raw))
        self.evidence=dict(project_id=self.pid,job_id=self.jid,adoption_version=1,package_id='P',
            binding_digest='binding',spec_digest='spec',manifest_digest=pp.digest(self.job['manifest']),
            review_digest=pp.digest([self.job['review_a'],self.job['review_b']]),report_id='report1',
            report_digest=hashlib.sha256(raw.encode()).hexdigest(),candidates={
                k:dict(digest=v['sha256'],test_count=2) for k,v in self.report['lanes'].items()})
        self.contract=dict(adoption_version=1,binding_digest='binding',spec_digest='spec',predecessors=[])
        for obj,name,value in ((sel.qa,'source',self.evidence),(sel.ec,'source',self.contract),
            (sel.ec,'require_confirmed',dict(version=1,digest='contract')),(sel.coding_factory,'detail',self.job),
            (pp,'check_role',None)):
            p=patch.object(obj,name,return_value=value);p.start();self.addCleanup(p.stop)
        ws.initialize(self.db,self.pid,{'confirmation':ws.CONFIRMATION})

    def view(self):
        return sel.view(self.c,self.db,self.pid,self.jid)

    def body(self,lane='B'):
        return dict(job_id=self.jid,source_digest=self.view()['source_digest'],expected_version=0,
            selected=lane,rationale='Candidate has a reasoned interface and verified test evidence.',
            confirmation='SELECT ENGINEERING DEV-'+lane+' '+self.jid)

    def record(self,body=None):
        return sel.record(self.c,self.db,self.pid,'reviewer',body if body is not None else self.body(),'stamp')

    def test_b_selected_bound_to_real_git_and_no_authority(self):
        before=ws.view(self.db,self.pid)
        self.assertEqual(self.view()['state'],'AWAITING_SELECTION')
        out=self.record()
        self.assertEqual(out['selected'],'B')
        self.assertEqual(self.view()['state'],'SELECTED')
        self.assertEqual(self.view()['source']['base_commit'],before['base_commit'])
        self.assertTrue(all(out[k] is False for k in sel.FLAGS))
        self.assertEqual(ws.view(self.db,self.pid),before)

    def test_duplicate_and_stale_version(self):
        body=self.body();self.record(body)
        for version in (0,1):
            with self.assertRaises(ValueError):
                self.record(dict(body,expected_version=version))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_candidate_selections').fetchone()[0],1)

    def test_explicit_confirmation_and_permission(self):
        body=self.body()
        for update in (dict(confirmation='yes'),dict(source_digest='bad'),dict(selected='C')):
            with self.assertRaises(ValueError):self.record(dict(body,**update))
        with patch.object(pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.record(body)
        base='/api/projects/project1/engineering/candidate-selections/'
        self.assertEqual(auth_policy.scope(self.c,'GET',base+self.jid),(self.pid,'read'))
        self.assertEqual(auth_policy.scope(self.c,'POST',base+'confirm'),(self.pid,'approve'))
        self.assertIsNone(auth_policy.scope(self.c,'POST',base+'merge'))

    def test_cross_project_and_workspace_tamper(self):
        ws.initialize(self.db,'project2',{'confirmation':ws.CONFIRMATION})
        with self.assertRaises(ValueError):sel.source(self.c,self.db,'project2',self.jid)
        body=self.body()
        (ws.location(self.db,self.pid)/'HEAD').write_text('broken')
        with self.assertRaises(ValueError):self.record(body)
        self.assertEqual(self.view()['state'],'BLOCK')

    def test_report_replacement_stales_receipt(self):
        self.record()
        raw=json.dumps(dict(self.report,note='new report bytes'))
        self.c.execute('UPDATE coding_verifications SET report_json=?',(raw,))
        self.evidence['report_digest']=hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(self.view()['state'],'STALE')
        body=dict(self.body('A'),expected_version=1)
        self.assertEqual(self.record(body)['version'],2)
        self.assertEqual(self.view()['receipt']['selected'],'A')

    def test_failed_other_candidate_blocks(self):
        self.report['lanes']['A']['status']='failed'
        raw=json.dumps(self.report)
        self.c.execute('UPDATE coding_verifications SET report_json=?',(raw,))
        self.evidence['report_digest']=hashlib.sha256(raw.encode()).hexdigest()
        self.assertEqual(self.view()['state'],'BLOCK')

    def test_review_or_contract_changed_blocks(self):
        body=self.body()
        self.job['review_a']['score']=99
        with self.assertRaises(ValueError):self.record(body)
        self.job['review_a']['score']=90
        self.contract['spec_digest']='changed'
        with self.assertRaises(ValueError):self.record(body)

    def test_immutable_and_atomic_audit_failure(self):
        body=self.body()
        self.c.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON auth_audit
            BEGIN SELECT RAISE(ABORT,'injected audit failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):self.record(body)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_candidate_selections').fetchone()[0],0)
        self.c.execute('DROP TRIGGER fail_audit')
        self.record(body)
        for sql in ("UPDATE engineering_candidate_selections SET digest='bad'","DELETE FROM engineering_candidate_selections"):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
        self.assertEqual(self.view()['state'],'SELECTED')

    def test_tampered_receipt_fails_closed(self):
        self.record()
        self.c.execute('DROP TRIGGER engineering_selection_no_update')
        self.c.execute("UPDATE engineering_candidate_selections SET digest='bad'")
        self.assertEqual(self.view()['state'],'INVALID')


if __name__=='__main__':
    unittest.main()
