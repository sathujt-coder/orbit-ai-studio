"""Real SQLite WAL contention tests for audited guard/runner transactions."""
import sqlite3,sys,tempfile,threading,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import acceptance_runner as runner
import auth_store
import project_planning as pp

class AuditedTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.sqlite'
        self.writer=sqlite3.connect(self.path,timeout=2)
        self.addCleanup(self.writer.close)
        self.writer.execute('PRAGMA journal_mode=WAL')
        auth_store.ensure_schema(self.writer)
        self.writer.execute("INSERT INTO auth_users(id,password_hash) VALUES('reviewer','fixture')")
        self.writer.execute("INSERT INTO auth_memberships VALUES('reviewer','p','reviewer')")
        self.writer.commit()
    def connect(self):
        c=sqlite3.connect(self.path,timeout=2)
        c.row_factory=sqlite3.Row
        runner.restrict_cli_database(c)
        return c
    def count(self):
        return self.writer.execute('SELECT count(*) FROM auth_audit').fetchone()[0]
    def test_deferred_snapshot_upgrade_reproduces_locked(self):
        c=self.connect();self.addCleanup(c.close)
        c.execute('BEGIN')
        c.execute('SELECT role FROM auth_memberships').fetchone()
        self.writer.execute("UPDATE auth_memberships SET role='viewer'")
        self.writer.commit()
        with self.assertRaisesRegex(sqlite3.OperationalError,'database is locked'):
            pp.check_role(c,'p','reviewer','read')
        c.rollback();self.assertEqual(self.count(),0)
    def contend(self,revoke):
        entered=threading.Event()
        self.writer.execute('BEGIN IMMEDIATE')
        if revoke:self.writer.execute("DELETE FROM auth_memberships WHERE user_id='reviewer'")
        else:self.writer.execute("UPDATE auth_memberships SET role='viewer'")
        def worker():
            c=self.connect()
            try:
                c.set_trace_callback(lambda sql:entered.set() if sql=='BEGIN IMMEDIATE' else None)
                with c:
                    runner.begin_audited_transaction(c)
                    pp.check_role(c,'p','reviewer','read')
                    return c.execute("SELECT role FROM auth_memberships WHERE user_id='reviewer'").fetchone()[0]
            finally:c.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(worker)
            try:
                self.assertTrue(entered.wait(1),'Writer reservation was not attempted')
                self.assertFalse(result.done(),'Guard did not wait for writer')
            finally:self.writer.commit()
            if revoke:
                with self.assertRaises(PermissionError):result.result(timeout=3)
                self.assertEqual(self.count(),0)
            else:
                self.assertEqual(result.result(timeout=3),'viewer')
                self.assertEqual(self.count(),1)
    def test_immediate_waits_then_reads_fresh_role(self):self.contend(False)
    def test_immediate_waits_then_rejects_revoked_role(self):self.contend(True)
    def test_guard_failure_rolls_back_audit_and_no_domain_write(self):
        c=self.connect();self.addCleanup(c.close)
        with self.assertRaisesRegex(ValueError,'stale'):
            with c:
                runner.begin_audited_transaction(c)
                pp.check_role(c,'p','reviewer','read')
                raise ValueError('stale')
        self.assertEqual(self.count(),0)
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("UPDATE auth_memberships SET role='owner'")
        c.rollback()
        self.assertEqual(self.writer.execute('SELECT role FROM auth_memberships').fetchone()[0],'reviewer')
    def test_idle_required(self):
        c=self.connect();self.addCleanup(c.close)
        c.execute('BEGIN')
        with self.assertRaisesRegex(ValueError,'Idle database'):
            runner.begin_audited_transaction(c)
        c.rollback()
if __name__=='__main__':unittest.main()
