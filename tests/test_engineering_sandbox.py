"""P6.3g unit regressions: real Git, controlled Docker transport.

The mandatory Chromium acceptance exercises the separate real Docker path.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_engineering_candidate_selection as selection_fixture
from test_verification_factory import FakeDocker, JS_IMG
import engineering_sandbox as sb
import auth_policy


class EngineeringSandboxTests(unittest.TestCase):
    def setUp(self):
        self.fixture=selection_fixture.EngineeringSelectionTests(methodName='test_b_selected_bound_to_real_git_and_no_authority')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f=self.fixture
        self.c,self.db,self.pid,self.jid=f.c,f.db,f.pid,f.jid
        sb.ensure_schema(self.c)
        f.record()
        self.c.commit()

    def view(self):
        return sb.view(self.c,self.db,self.pid,self.jid)

    def run_replay(self, fake=None, **changes):
        view=self.view()
        kwargs=dict(actor='reviewer',expected_digest=view['source_digest'],
                    expected_version=view['latest_version'],
                    confirmation='RUN ENGINEERING SANDBOX '+self.jid,node_image=JS_IMG)
        kwargs.update(changes)
        real=sb.vf.verify_job
        fake=fake if fake is not None else FakeDocker()
        with patch.object(sb.vf,'verify_job',side_effect=lambda *a,**k:real(*a,runner=fake,**k)):
            return sb.run(self.c,self.db,self.pid,self.jid,**kwargs)

    def test_real_git_object_extraction_and_parent(self):
        source=self.fixture.view()['source']
        job=self.fixture.job
        before=sb.ws.view(self.db,self.pid)
        results=[]
        for lane in ('A','B'):
            with tempfile.TemporaryDirectory() as work:
                proposal=job['proposal_'+lane.lower()]
                root,meta=sb.materialize(self.db,self.pid,self.jid,lane,proposal,source['base_commit'],work)
                self.assertEqual(meta['parent'],before['base_commit'])
                self.assertEqual(meta['source_sha256'],source['bound_evidence']['candidates'][lane]['digest'])
                for f in proposal['files']:
                    self.assertEqual((root/f['path']).read_bytes(),f['content'].encode())
                results.append(meta['commit'])
        self.assertNotEqual(*results)
        self.assertEqual(sb.ws.view(self.db,self.pid),before)

    def test_replay_and_immutable_receipt(self):
        fake=FakeDocker()
        before=self.fixture.view()['receipt']['digest']
        self.assertEqual(self.view()['state'],'AWAITING_EXPLICIT_SANDBOX')
        result=self.run_replay(fake)
        self.assertEqual(result['gate'],'PASS')
        self.assertEqual(result['selected'],'B')
        self.assertEqual(result['selection_digest'],before)
        self.assertTrue(all(result[k] is False for k in sb.FLAGS))
        self.assertEqual(self.view()['receipt']['digest'],result['digest'])
        self.assertEqual(self.fixture.view()['receipt']['digest'],before)
        self.assertEqual(len(fake.calls),6)
        for argv,_ in fake.calls:
            self.assertEqual(argv[argv.index('--network')+1],'none')
            self.assertIn('--read-only',argv)
        for sql in ("UPDATE engineering_sandbox_runs SET digest='bad'",
                    "DELETE FROM engineering_sandbox_runs",
                    "INSERT OR REPLACE INTO engineering_sandbox_runs SELECT * FROM engineering_sandbox_runs"):
            with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
            self.c.rollback()

    def test_permission_stale_digest_and_confirmation_before_execution(self):
        fake=FakeDocker()
        for change in (dict(confirmation='yes'),dict(expected_digest='bad'),dict(expected_version=True),dict(expected_version=1)):
            with self.assertRaises((ValueError,PermissionError)):self.run_replay(fake,**change)
        self.assertEqual(fake.calls,[])
        path='/api/projects/'+self.pid+'/engineering/sandbox/'+self.jid
        self.assertEqual(auth_policy.scope(self.c,'GET',path),(self.pid,'read'))
        self.assertIsNone(auth_policy.scope(self.c,'POST',path))

    def test_failed_docker_is_block_not_pass(self):
        result=self.run_replay(FakeDocker(node_return=1))
        self.assertEqual(result['gate'],'BLOCK')
        self.assertEqual(self.view()['state'],'BLOCK')
        self.assertFalse(result['execution_authorized'])

    def test_stale_source_after_docker_discards_receipt(self):
        fake=FakeDocker()
        def change(argv,**kwargs):
            result=fake(argv,**kwargs)
            self.fixture.contract['spec_digest']='changed during Docker'
            return result
        with self.assertRaises(ValueError):self.run_replay(change)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_sandbox_runs').fetchone()[0],0)

    def test_audit_failure_rolls_back_receipt(self):
        self.c.execute("""CREATE TRIGGER fail_sandbox_audit BEFORE INSERT ON auth_audit
            WHEN NEW.action='engineering_sandbox_replay'
            BEGIN SELECT RAISE(ABORT,'injected sandbox audit failure'); END""")
        self.c.commit()
        with self.assertRaises(sqlite3.IntegrityError):self.run_replay()
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_sandbox_runs').fetchone()[0],0)

    def test_audited_replay_reserves_writer_before_read_and_releases_for_docker(self):
        statements=[]
        self.c.set_trace_callback(statements.append)
        self.addCleanup(self.c.set_trace_callback,None)
        fake=FakeDocker()
        def check(argv,**kwargs):
            self.assertFalse(self.c.in_transaction)
            return fake(argv,**kwargs)
        self.run_replay(check)
        begins=[x for x in statements if x.startswith('BEGIN')]
        self.assertEqual(begins,['BEGIN IMMEDIATE','BEGIN IMMEDIATE'])

    def test_report_replacement_stales_replay(self):
        self.run_replay()
        self.fixture.evidence['report_digest']='new digest'
        self.assertEqual(self.view()['state'],'STALE')


if __name__=='__main__':unittest.main()
