"""Unit/integration tests for the agent workflow (no LLM/API bill)."""
import importlib.util, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import sqlite3
import json

SPEC=importlib.util.spec_from_file_location('studio_server',Path(__file__).resolve().parents[1]/'backend'/'server.py')
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        mod.DB_PATH=Path(self.tmp.name)/'test.sqlite'
        mod.PROVIDER='demo'
        mod.init_db()
        self.pid=mod.list_projects()[0]['id']
        with mod.db() as c:
            mod.auth_store.create_user(c,'workflow-owner','fixture-password-123')
            mod.auth_store.grant(c,'workflow-owner',self.pid,'owner')
    def tearDown(self): self.tmp.cleanup()
    def test_roster(self):
        self.assertEqual(len(mod.AGENTS),24)
        self.assertEqual(len(mod.STAGES),12)
        self.assertEqual(len({a['id'] for a in mod.AGENTS}),24)
        self.assertEqual(sum(s['approval'] for s in mod.STAGES),3)
    def test_independent_draft_and_cross_review(self):
        result=mod.run_stage(self.pid,'po')
        self.assertEqual(result,'done')
        state=mod.project_state(self.pid)
        self.assertEqual(state['tasks'][0]['status'],'done')
        self.assertEqual(len(state['artifacts']),3)
        self.assertEqual(len(state['reviews']),2)
        self.assertEqual({(r['reviewer_id'],r['author_id']) for r in state['reviews']},{('po-A','po-B'),('po-B','po-A')})
        self.assertTrue(all(r['verdict']=='APPROVE' for r in state['reviews']))
    def test_human_approval_gate(self):
        with self.assertRaisesRegex(ValueError,'Handoff source quality gate blocked'):
            mod.run_stage(self.pid,'security')
        with patch.object(mod.time,'sleep',return_value=None):
            for sid in mod.STAGE_IDS[:mod.STAGE_IDS.index('security')]:
                self.assertEqual(mod.run_stage(self.pid,sid),'done')
            self.assertEqual(mod.run_stage(self.pid,'security'),'awaiting_approval')
        state=mod.project_state(self.pid)
        security=next(x for x in state['handoff']['roles'] if x['stage_id']=='security')
        self.assertEqual(security['consumption_status'],'DEMO_DRAFTS')
        self.assertEqual(security['receipt']['lanes'],['A','B'])
        self.assertEqual(len(security['receipt']['sources']),9)
        self.assertEqual(security['output']['status'],'blocked')
        with mod.db() as c:
            receipt=c.execute("SELECT * FROM studio_handoff_receipts WHERE project_id=? AND stage_id='security'",(self.pid,)).fetchone()
            self.assertEqual(json.loads(receipt['snapshot'])['context'],mod.get_preceding(self.pid,'security'))
        with self.assertRaisesRegex(ValueError,'Handoff source quality gate blocked'):
            mod.run_stage(self.pid,'devops')
        t={t['stage_id']:t for t in mod.project_state(self.pid)['tasks']}
        self.assertEqual(t['security']['status'],'awaiting_approval')
        mod.approve_stage(self.pid,'security')
        t={t['stage_id']:t for t in mod.project_state(self.pid)['tasks']}
        self.assertEqual(t['security']['status'],'approved')
        with self.assertRaises(ValueError):mod.approve_stage(self.pid,'security')
    def test_atomic_draft_receipt_rollback(self):
        # Force lane B receipt INSERT to fail after the corresponding artifact
        # INSERT. Exercise the actual run_stage transaction, not a copy of it.
        with mod.db() as c:
            c.execute("""CREATE TRIGGER test_reject_b BEFORE INSERT ON studio_handoff_drafts
                WHEN NEW.lane='B' BEGIN SELECT RAISE(ABORT,'fixture receipt failure'); END""")
        with patch.object(mod.time,'sleep',return_value=None):
            with self.assertRaisesRegex(sqlite3.IntegrityError,'fixture receipt failure'):
                mod.run_stage(self.pid,'po')
        with mod.db() as c:
            receipts=c.execute("SELECT run_id FROM studio_handoff_receipts WHERE project_id=? AND stage_id='po'",(self.pid,)).fetchall()
            self.assertEqual(len(receipts),1)
            rid=receipts[0]['run_id']
            lanes=c.execute("SELECT lane FROM studio_handoff_drafts WHERE project_id=? AND stage_id='po' AND run_id=?",(self.pid,rid)).fetchall()
            self.assertEqual([x['lane'] for x in lanes],['A'])
            artifacts=c.execute("SELECT agent_id,kind FROM artifacts WHERE project_id=? AND stage_id='po'",(self.pid,)).fetchall()
            self.assertEqual([(x['agent_id'],x['kind']) for x in artifacts],[('po-A','draft')])
            self.assertEqual(c.execute("SELECT count(*) FROM reviews WHERE project_id=?",(self.pid,)).fetchone()[0],0)
            self.assertFalse(c.execute('PRAGMA foreign_key_check').fetchall())
        role=mod.project_state(self.pid)['handoff']['roles'][0]
        self.assertEqual(role['receipt']['lanes'],['A'])
        self.assertEqual(role['output']['status'],'blocked')
        self.assertFalse(role['execution_authorized'])
    def test_review_parser_fail_closed(self):
        self.assertEqual(mod.parse_review('not json')[0],'REQUEST_CHANGES')
        self.assertEqual(mod.parse_review('{"verdict":"APPROVE","score":200,"feedback":"ok"}'),('APPROVE',100,'ok'))
    def test_chat_and_user_input(self):
        answer=mod.agent_chat(self.pid,'dev-B','Kiểm tra cách thiết kế API')
        self.assertIn('[DEMO]',answer)
        with mod.db() as c:
            count=c.execute('SELECT COUNT(*) FROM chat WHERE project_id=?',(self.pid,)).fetchone()[0]
        self.assertEqual(count,2)
        with self.assertRaises(ValueError):mod.agent_chat(self.pid,'invalid-A','test')
    def test_one_step_pipeline(self):
        identifier=mod.enqueue_pipeline(self.pid,'workflow-owner','next')
        self.assertTrue(mod.project_state(self.pid)['running'])
        self.assertTrue(mod.dispatch_one())
        state=mod.project_state(self.pid)
        self.assertEqual([t['status'] for t in state['tasks']][:2],['done','queued'])
        self.assertFalse(state['running'])
        with mod.db() as c:
            task=mod.agent_queue.get(c,self.pid,identifier)
            self.assertEqual(task['status'],'succeeded')
            self.assertEqual(task['checkpoint_stage'],'po')
            self.assertEqual(task['attempts'],1)
        self.assertFalse(mod.dispatch_one())

if __name__=='__main__':unittest.main()
