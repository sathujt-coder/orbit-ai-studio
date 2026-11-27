import copy,sqlite3,unittest
import detected_defect_registry as r
import test_defect_severity as fixtures

class DetectedRegistryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SeverityTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.c;r.ensure_schema(self.c)
    def view(self):return r.view(self.c,None,'p','j')
    def register(self,actor='reviewer',digest=None,confirmation='REGISTER DETECTED DEFECTS j'):
        return r.register(self.c,None,'p','j',actor,digest if digest is not None else self.f.view()['evidence_digest'],confirmation)
    def count(self):return self.c.execute('SELECT count(*) FROM engineering_detected_defects').fetchone()[0]
    def test_registration(self):
        self.assertEqual(self.view()['state'],'REGISTRATION_REQUIRED')
        result=self.register();v=self.view()
        self.assertEqual(v['state'],'REGISTERED')
        self.assertEqual(result,[v['history'][0]['digest']])
        self.assertEqual(v['history'][0]['snapshot']['state'],'OPEN')
        self.assertFalse(v['quality_gate_override'])
    def test_low_preserved(self):
        self.f.attest('COSMETIC_IMPACT');self.register()
        self.assertEqual(self.view()['history'][0]['snapshot']['classification']['severity'],'LOW')
    def test_duplicate(self):
        self.register()
        with self.assertRaises(ValueError):self.register()
        self.assertEqual(self.count(),1)
    def test_stale_digest(self):
        with self.assertRaises(ValueError):self.register(digest='a'*64)
        self.assertEqual(self.count(),0)
    def test_unauthorized(self):
        with self.assertRaises(PermissionError):self.register(actor='unknown')
        self.assertEqual(self.count(),0)
    def test_confirmation(self):
        with self.assertRaises(PermissionError):self.register(confirmation='yes')
        self.assertEqual(self.count(),0)
    def test_atomic_audit(self):
        self.c.execute("""CREATE TRIGGER reject_registry_audit BEFORE INSERT ON auth_audit
          WHEN NEW.action='engineering_detected_defects_register'
          BEGIN SELECT RAISE(ABORT,'injected'); END""")
        before=self.c.execute('SELECT count(*) FROM auth_audit').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):self.register()
        self.assertEqual(self.count(),0)
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_audit').fetchone()[0],before)
    def test_immutable(self):
        self.register()
        for sql in ('UPDATE engineering_detected_defects SET digest="bad"',
                    'DELETE FROM engineering_detected_defects',
                    'INSERT OR REPLACE INTO engineering_detected_defects SELECT * FROM engineering_detected_defects'):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
    def test_recovery_does_not_close(self):
        self.register();old=self.view()['history']
        self.f.f.f.setup_result(True);self.f.v=self.f.f.detect()
        v=self.view()
        self.assertEqual(v['state'],'NO_CURRENT_FINDINGS')
        self.assertEqual(v['history'],old)
        self.assertFalse(v['automatic_closure'])
    def test_stale_preserves_history(self):
        self.register();old=self.view()['history']
        self.f.v=copy.deepcopy(self.f.v);self.f.v['state']='BLOCK'
        self.assertEqual(self.view()['state'],'BLOCK')
        self.assertEqual(self.view()['history'],old)
if __name__=='__main__':unittest.main()
