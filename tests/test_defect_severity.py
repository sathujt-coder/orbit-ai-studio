import copy,sqlite3,unittest
from unittest.mock import patch
import defect_severity as s
import test_defect_classification as fixtures
import auth_store

class SeverityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ClassificationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.v=self.f.failed()
        self.c=sqlite3.connect(':memory:');self.addCleanup(self.c.close)
        auth_store.ensure_schema(self.c)
        self.c.execute("INSERT INTO auth_users(id,password_hash) VALUES('reviewer','fixture')")
        self.c.execute("INSERT INTO auth_memberships VALUES('reviewer','p','reviewer')")
        s.ensure_schema(self.c);self.c.commit();self.c.execute('BEGIN IMMEDIATE')
        p=patch.object(s.detection,'view',side_effect=lambda *a:copy.deepcopy(self.v))
        p.start();self.addCleanup(p.stop)
    def view(self,submitted=None):return s.view(self.c,None,'p','j',submitted)
    def attest(self,impact,actor='reviewer'):
        f=self.v['findings'][0]['finding_id']
        return s.attest(self.c,None,'p','j',actor,f,self.v['evidence_digest'],impact,
                        'Reviewed bounded impact evidence','ATTEST SEVERITY j '+f)
    def level(self,impact,expected):
        self.attest(impact);v=self.view()
        self.assertEqual(v['items'][0]['severity'],expected)
        self.assertTrue(v['items'][0]['impact_confirmed'])
        self.assertFalse(v['quality_gate_override'])
    def test_critical(self):self.level('DATA_LOSS','CRITICAL')
    def test_high(self):self.level('MANDATORY_FAILURE','HIGH')
    def test_medium(self):self.level('LIMITED_FUNCTIONAL_IMPACT','MEDIUM')
    def test_low(self):self.level('COSMETIC_IMPACT','LOW')
    def test_default(self):
        self.assertEqual(self.view()['items'][0]['severity'],'HIGH')
        self.assertFalse(self.view()['items'][0]['impact_confirmed'])
    def test_forged_rehashed(self):
        v=copy.deepcopy(self.v);v['findings']=[];v['state']='NO_FINDINGS'
        self.f.resign(v)
        self.assertEqual(self.view(v)['state'],'BLOCK')
    def test_wrong_actor(self):
        with self.assertRaises(PermissionError):self.attest('DATA_LOSS','unknown')
    def test_immutable(self):
        self.attest('COSMETIC_IMPACT')
        with self.assertRaises(sqlite3.IntegrityError):self.c.execute('UPDATE engineering_severity_attestations SET digest="bad"')
        with self.assertRaises(sqlite3.IntegrityError):self.attest('DATA_LOSS')
    def test_stale(self):
        self.attest('COSMETIC_IMPACT')
        self.v=copy.deepcopy(self.v)
        self.v['state']='BLOCK'
        self.assertEqual(self.view()['state'],'BLOCK')
    def test_runtime_not_downgraded(self):
        self.v=self.f.f.nonexecuted('ERROR','DOCKER_UNAVAILABLE')
        with self.assertRaises(ValueError):self.attest('COSMETIC_IMPACT')
        self.assertEqual(self.view()['items'][0]['severity'],'HIGH')
    def test_atomic_audit_failure(self):
        self.c.execute("""CREATE TRIGGER fail_severity_audit BEFORE INSERT ON auth_audit
            WHEN NEW.action='engineering_severity_attest'
            BEGIN SELECT RAISE(ABORT,'injected audit failure'); END""")
        before=self.c.execute('SELECT count(*) FROM auth_audit').fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):self.attest('COSMETIC_IMPACT')
        self.assertEqual(self.c.execute('SELECT count(*) FROM engineering_severity_attestations').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT count(*) FROM auth_audit').fetchone()[0],before)
        self.assertTrue(self.c.in_transaction)
        self.c.commit()
        self.assertEqual(self.c.execute('SELECT count(*) FROM engineering_severity_attestations').fetchone()[0],0)
    def test_idempotent_migration_preserves_receipt(self):
        digest=self.attest('COSMETIC_IMPACT')
        s.ensure_schema(self.c);s.ensure_schema(self.c)
        self.assertEqual(self.view()['items'][0]['attestation_digest'],digest)
    def test_nul_rationale_rejected(self):
        f=self.v['findings'][0]['finding_id']
        with self.assertRaises(ValueError):
            s.attest(self.c,None,'p','j','reviewer',f,self.v['evidence_digest'],'COSMETIC_IMPACT',
                     'Reviewed evidence with '+chr(0)+' invalid text','ATTEST SEVERITY j '+f)
        self.assertEqual(self.c.execute('SELECT count(*) FROM engineering_severity_attestations').fetchone()[0],0)
    def test_revoked_reviewer(self):
        self.c.execute("DELETE FROM auth_memberships WHERE user_id='reviewer'")
        with self.assertRaises(PermissionError):self.attest('DATA_LOSS')
        self.assertEqual(self.c.execute('SELECT count(*) FROM engineering_severity_attestations').fetchone()[0],0)
if __name__=='__main__':unittest.main()
