import json
import sqlite3
import unittest
from unittest.mock import patch
import test_engineering_draft as fixture
import engineering_quality as eq
import auth_policy

class EngineeringQualityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.EngineeringDraftTests(methodName='test_publish_one_atomic_tree_and_draft_only')
        self.addCleanup(self.f.doCleanups);self.f.setUp()
        self.c,self.db,self.pid,self.jid=self.f.c,self.f.db,self.f.pid,self.f.jid
        self.src=dict(project_id=self.pid,job_id=self.jid,binding=dict(package_id='P',adoption_version=1),
            qa=dict(state='HUMAN_QA_PASS',source_digest='qa-source',receipt_digest='qa-receipt'),
            sandbox=dict(state='PASS',source_digest='sandbox-source',version=1,receipt_digest='initial'),**eq.FLAGS)
        p=patch.object(eq,'source',side_effect=lambda *a:self.src);p.start();self.addCleanup(p.stop)

    def body(self,action='OPEN',version=0,**changes):
        b=dict(action=action,defect_id='D1',expected_version=version,source_digest=eq.pp.digest(self.src),
            rationale='Explicit review and reproduction evidence for this defect.',
            confirmation='DEFECT '+action+' '+self.jid+' D1')
        if action=='OPEN':b.update(title='Missing regression case',severity='HIGH',category='TEST')
        b.update(changes);return b

    def event(self,action='OPEN',version=0,**changes):
        return eq.record(self.c,self.db,self.pid,self.jid,'reviewer',self.body(action,version,**changes),'stamp')

    def view(self):
        return eq.view(self.c,self.db,self.pid,self.jid)

    def fresh(self):
        self.src['sandbox'].update(version=2,receipt_digest='fresh')

    def test_lifecycle_requires_new_sandbox_and_current_qa(self):
        self.assertEqual(self.view()['state'],'QUALITY_EVIDENCE_PASS')
        a=self.event();self.assertEqual(self.view()['state'],'BLOCK')
        b=self.event('READY_FOR_RETEST',1)
        with self.assertRaises(ValueError):self.event('CLOSED',2)
        self.fresh();self.src['qa']['state']='HUMAN_QA_BLOCK'
        with self.assertRaises(ValueError):self.event('CLOSED',2)
        self.src['qa']['state']='HUMAN_QA_PASS'
        c=self.event('CLOSED',2)
        self.assertEqual(self.view()['state'],'QUALITY_EVIDENCE_PASS')
        self.assertEqual([x['digest'] for x in self.view()['defects'][0]['history']],[a['digest'],b['digest'],c['digest']])
        self.event('REOPEN',3)
        self.assertEqual(self.view()['counts']['OPEN'],1)

    def test_stale_and_duplicate_rejected(self):
        self.event()
        with self.assertRaises(ValueError):self.event()
        with self.assertRaises(ValueError):self.event('READY_FOR_RETEST',1,source_digest='bad')
        self.assertEqual(self.view()['defects'][0]['version'],1)

    def test_immutable_and_tamper(self):
        self.event();self.c.commit()
        for sql in ("UPDATE engineering_defect_events SET digest='bad'","DELETE FROM engineering_defect_events",
                    "INSERT OR REPLACE INTO engineering_defect_events SELECT * FROM engineering_defect_events"):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
            self.c.rollback()
        self.c.execute('DROP TRIGGER engineering_defect_no_update')
        self.c.execute("UPDATE engineering_defect_events SET digest='bad'")
        self.assertEqual(self.view()['state'],'BLOCK')
        with self.assertRaises(ValueError):eq.guard_no_open_defects(self.c,self.pid,self.jid)

    def test_atomic_audit_failure(self):
        self.c.execute("""CREATE TRIGGER fail_defect_audit BEFORE INSERT ON auth_audit
            WHEN NEW.action='engineering_defect_open' BEGIN SELECT RAISE(ABORT,'fault'); END""")
        with self.assertRaises(sqlite3.IntegrityError):self.event()
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_defect_events').fetchone()[0],0)

    def test_permission_and_scope(self):
        with patch.object(eq.pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.event()
        path='/api/projects/'+self.pid+'/engineering/quality/'+self.jid
        self.assertEqual(auth_policy.scope(self.c,'GET',path),(self.pid,'read'))
        self.assertEqual(auth_policy.scope(self.c,'POST',path+'/defects',body=self.body()),(self.pid,'approve'))
        self.assertEqual(auth_policy.scope(self.c,'POST',path+'/defects',body=self.body('READY_FOR_RETEST',1)),(self.pid,'write'))

    def test_open_defect_blocks_actual_draft_entry(self):
        self.event();self.c.commit()
        with self.assertRaisesRegex(ValueError,'Unresolved engineering defects'):self.f.apply()
        self.assertEqual(self.f.remote.calls,[])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_draft_exports').fetchone()[0],0)

    def test_closed_evidence_blocks_draft_when_stale(self):
        self.event();self.event('READY_FOR_RETEST',1);self.fresh();self.event('CLOSED',2)
        self.src['qa']['receipt_digest']='changed';self.c.commit()
        with self.assertRaisesRegex(ValueError,'Stale defect closure evidence'):self.f.apply()
        self.assertEqual(self.f.remote.calls,[])

    def test_closed_evidence_stales(self):
        self.event();self.event('READY_FOR_RETEST',1);self.fresh();self.event('CLOSED',2)
        self.src['qa']['receipt_digest']='changed'
        self.assertEqual(self.view()['state'],'BLOCK')

if __name__=='__main__':unittest.main()
