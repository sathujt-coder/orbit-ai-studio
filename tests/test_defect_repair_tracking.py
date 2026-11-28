import sqlite3,unittest
from unittest.mock import patch
import defect_repair_tracking as t
import test_detected_defect_registry as fixtures

class RepairTrackingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DetectedRegistryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.c;t.ensure_schema(self.c)
        for user,role in [('dev','developer'),('other','developer'),('qa','reviewer'),('closer','reviewer'),('viewer','viewer')]:
            self.c.execute('INSERT INTO auth_users(id,password_hash) VALUES(?,?)',(user,'fixture'))
            self.c.execute('INSERT INTO auth_memberships VALUES(?,?,?)',(user,'p',role))
        self.f.register()
        self.item=self.view()['items'][0]
    def view(self):return t.view(self.c,None,'p','j')
    def act(self,action,actor,assignee=None,digest=None,**overrides):
        body=dict(action=action,finding_id=self.item['finding_id'],registration_digest=self.item['registration_digest'],
                  expected_digest=digest or self.view()['evidence_digest'],assignee=assignee,note='Bounded repair note',
                  confirmation=action+' DEFECT j '+self.item['finding_id'])
        body.update(overrides)
        return t.record(self.c,None,'p','j',actor,body,'fixture-time')
    def start(self):
        self.act('ASSIGN','reviewer','dev');self.act('START','dev')
    def evidence(self):
        return dict(execution_digest='a'*64,candidate_digest='b'*64,regression_digest='c'*64)
    def test_assignment(self):
        e=self.act('ASSIGN','reviewer','dev')
        self.assertEqual(e['snapshot']['state'],'ASSIGNED')
        self.assertEqual(self.view()['items'][0]['assignee'],'dev')
        self.assertEqual(self.f.view()['history'][0]['snapshot']['state'],'OPEN')
    def test_stale_duplicate(self):
        d=self.view()['evidence_digest'];self.act('ASSIGN','reviewer','dev',d)
        with self.assertRaises(ValueError):self.act('ASSIGN','reviewer','dev',d)
        self.assertEqual(len(self.view()['items'][0]['history']),1)
    def test_wrong_actor(self):
        with self.assertRaises(PermissionError):self.act('ASSIGN','viewer','dev')
        self.start()
        with self.assertRaises(PermissionError):self.act('SUBMIT','other')
    def test_invalid_assignee(self):
        with self.assertRaises(PermissionError):self.act('ASSIGN','reviewer','viewer')
    def test_revoked_membership(self):
        self.act('ASSIGN','reviewer','dev')
        self.c.execute("DELETE FROM auth_memberships WHERE user_id='dev'")
        with self.assertRaises(PermissionError):self.act('START','dev')
    def test_confirmation(self):
        with self.assertRaises(PermissionError):self.act('ASSIGN','reviewer','dev',confirmation='yes')
    def test_reassign(self):
        self.start();self.act('REASSIGN','reviewer','other')
        with self.assertRaises(PermissionError):self.act('START','dev')
        self.act('START','other')
    def test_atomic_audit(self):
        self.c.execute("""CREATE TRIGGER reject_repair_audit BEFORE INSERT ON auth_audit
          WHEN NEW.action='engineering_defect_repair_assign'
          BEGIN SELECT RAISE(ABORT,'injected'); END""")
        before=self.c.execute('SELECT count(*) FROM auth_audit').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):self.act('ASSIGN','reviewer','dev')
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_audit').fetchone()[0],before)
        self.assertEqual(self.view()['items'][0]['history'],[])
    def test_immutable(self):
        self.start()
        for sql in ('UPDATE engineering_defect_repair_events SET digest="bad"','DELETE FROM engineering_defect_repair_events',
                    'INSERT OR REPLACE INTO engineering_defect_repair_events SELECT * FROM engineering_defect_repair_events'):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
    def test_reject_and_resubmit(self):
        self.start()
        with patch.object(t,'repair_evidence',return_value=self.evidence()):
            self.act('SUBMIT','dev');self.act('REJECT','qa');self.act('SUBMIT','dev')
        self.assertEqual(self.view()['items'][0]['state'],'REPAIR_SUBMITTED')
        self.assertEqual(len(self.view()['items'][0]['history']),5)
    def test_verify_and_close(self):
        self.start()
        with patch.object(t,'repair_evidence',return_value=self.evidence()):
            self.act('SUBMIT','dev');self.act('VERIFY','qa')
            with self.assertRaises(PermissionError):self.act('CLOSE','qa')
            self.act('CLOSE','closer')
        self.assertEqual(self.view()['items'][0]['state'],'CLOSED')
        self.assertEqual(self.f.view()['history'][0]['snapshot']['state'],'OPEN')
        self.assertFalse(self.view()['quality_gate_override'])
    def test_stale_repair_rejected(self):
        self.start()
        with patch.object(t,'repair_evidence',return_value=self.evidence()):self.act('SUBMIT','dev')
        with patch.object(t,'repair_evidence',return_value=dict(self.evidence(),candidate_digest='d'*64)):
            with self.assertRaises(ValueError):self.act('VERIFY','qa')
    def test_recovery_preserves_tracking(self):
        self.start();old=self.view()['items']
        d=self.f.f.f.f;d.f.setup_result(True);self.f.f.v=d.detect()
        v=self.view()
        self.assertEqual(v['registry_state'],'NO_CURRENT_FINDINGS')
        self.assertEqual(v['items'],old)
        self.assertFalse(v['automatic_closure'])
    def test_stale_registry_blocks(self):
        self.start();self.f.f.v['state']='BLOCK'
        v=self.view();self.assertEqual(v['state'],'BLOCK')
        self.assertEqual(v['items'][0]['state'],'IN_PROGRESS')
        with self.assertRaises(ValueError):self.act('SUBMIT','dev')
    def test_invalid_transition(self):
        with self.assertRaises(ValueError):self.act('START','dev')
    def test_scope(self):
        with self.assertRaises(ValueError):self.act('ASSIGN','reviewer','dev',registration_digest='f'*64)
if __name__=='__main__':unittest.main()
