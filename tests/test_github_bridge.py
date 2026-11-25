"""No-network tests of GitHub human-gated local integration and retry behavior."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('orbit_server_for_bridge', HERE/'backend/server.py')
server=importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
bridge=server.github_bridge


class GithubBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        server.DB_PATH=Path(self.temp.name)/'orbits.sqlite'
        server.PROVIDER='demo'
        server.init_db()
        self.pid=server.list_projects()[0]['id']

    def tearDown(self):
        self.temp.cleanup()

    def artifact(self, stage='po'):
        with server.db() as conn:
            row=conn.execute('SELECT id FROM artifacts WHERE project_id=? AND stage_id=? AND kind=? ORDER BY rowid DESC LIMIT 1', (self.pid, stage, 'final')).fetchone()
        return row['id']

    def test_fails_before_stage_done(self):
        with server.db() as conn, self.assertRaisesRegex(ValueError,'Không tìm thấy'):
            bridge.preview(conn,self.pid,'doesnotexist')

    def test_read_only_preview_and_duplicate_protection(self):
        server.run_stage(self.pid,'po')
        aid=self.artifact()
        with server.db() as conn:
            plan=bridge.preview(conn,self.pid,aid)
        self.assertEqual(plan['stage'],'po')
        self.assertEqual(plan['review'][:3],'2/2')
        self.assertIsNone(plan['existing'])
        with patch.dict(os.environ,{'ORBIT_GITHUB_REPO':'sathujt-coder/orbit-ai-studio','GITHUB_TOKEN':'dummy', 'ORBIT_GITHUB_WRITES':'1'}):
            class MockClient:
                calls=0
                def __init__(self,token): self.assert_token=token
                def draft_pr_for_artifact(self,repo,artifact):
                    self.__class__.calls+=1
                    return {'url':'https://github.com/sathujt-coder/orbit-ai-studio/pull/14','number':14,'branch':'orbit/artifact-foo'}
            with self.assertRaisesRegex(ValueError, 'xác nhận'):
                bridge.create_export(server.db,server.LOCK,self.pid,aid,'',MockClient)
            result=bridge.create_export(server.db,server.LOCK,self.pid,aid,'CREATE DRAFT PR',MockClient)
            self.assertEqual(result['number'],14)
            self.assertEqual(MockClient.calls,1)
            with self.assertRaisesRegex(ValueError,'đã gửi'):
                bridge.create_export(server.db,server.LOCK,self.pid,aid,'CREATE DRAFT PR',MockClient)
            with server.db() as conn:
                self.assertEqual(bridge.preview(conn,self.pid,aid)['existing']['status'],'created')
                self.assertEqual(len(bridge.exports(conn,self.pid)),1)

    def test_cannot_reuse_earlier_reviews_for_forged_final(self):
        server.run_stage(self.pid,'po')
        with server.db() as conn:
            conn.execute("INSERT INTO artifacts(id,project_id,stage_id,agent_id,kind,content,created_at,run_id) VALUES(?,?,?,?,?,?,?,?)",
                ('forged',self.pid,'po','po-A','final','# unverifiable','2026-11-23','different-run'))
            with self.assertRaisesRegex(ValueError,'phương án độc lập'):
                bridge.preview(conn,self.pid,'forged')

    def test_disabled_token_never_appears_in_config(self):
        with patch.dict(os.environ,{'GITHUB_TOKEN':'very-secret-value','ORBIT_GITHUB_WRITES':'0'}):
            status=bridge.config()
            self.assertTrue(status['token_configured'])
            self.assertNotIn('very-secret-value',str(status))
            self.assertFalse(status['writes_enabled'])

    def test_manual_gate_required(self):
        with self.assertRaisesRegex(ValueError,'Handoff source quality gate blocked'):
            server.run_stage(self.pid,'security')
        with patch.object(server.time,'sleep',return_value=None):
            for sid in server.STAGE_IDS[:server.STAGE_IDS.index('security')]:
                self.assertEqual(server.run_stage(self.pid,sid),'done')
            self.assertEqual(server.run_stage(self.pid,'security'),'awaiting_approval')
        aid=self.artifact('security')
        with server.db() as conn, self.assertRaisesRegex(ValueError,'human approval'):
            bridge.preview(conn,self.pid,aid)
        server.approve_stage(self.pid,'security')
        with server.db() as conn:
            self.assertEqual(bridge.preview(conn,self.pid,aid)['stage'],'security')

    def test_only_latest_final(self):
        server.run_stage(self.pid,'po')
        old=self.artifact()
        server.run_stage(self.pid,'po')
        with server.db() as conn, self.assertRaisesRegex(ValueError,'final cũ'):
            bridge.preview(conn,self.pid,old)

    def test_reject_unsafe_and_blocked_writes(self):
        self.assertFalse(bridge.safe_repo('.. /repo'))
        self.assertFalse(bridge.safe_repo('-bad/repo'))
        server.run_stage(self.pid,'po')
        aid=self.artifact()
        with patch.dict(os.environ,{'ORBIT_GITHUB_REPO':'sathujt-coder/orbit-ai-studio','ORBIT_GITHUB_WRITES':'0', 'GITHUB_TOKEN':'dummy'}):
            with self.assertRaisesRegex(ValueError,'Chưa bật'):
                bridge.create_export(server.db,server.LOCK,self.pid,aid,'CREATE DRAFT PR')


if __name__=='__main__': unittest.main()
