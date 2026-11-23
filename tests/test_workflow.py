"""Unit/integration tests for the agent workflow (no LLM/API bill)."""
import importlib.util, tempfile, unittest
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('studio_server',Path(__file__).resolve().parents[1]/'backend'/'server.py')
mod=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        mod.DB_PATH=Path(self.tmp.name)/'test.sqlite'
        mod.PROVIDER='demo'
        mod.RUNNING.clear()
        mod.init_db()
        self.pid=mod.list_projects()[0]['id']
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
        self.assertEqual(mod.run_stage(self.pid,'security'),'awaiting_approval')
        t={t['stage_id']:t for t in mod.project_state(self.pid)['tasks']}
        self.assertEqual(t['security']['status'],'awaiting_approval')
        mod.approve_stage(self.pid,'security')
        t={t['stage_id']:t for t in mod.project_state(self.pid)['tasks']}
        self.assertEqual(t['security']['status'],'approved')
        with self.assertRaises(ValueError):mod.approve_stage(self.pid,'security')
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
        mod.pipeline_worker(self.pid,'next')
        statuses=[t['status'] for t in mod.project_state(self.pid)['tasks']]
        self.assertEqual(statuses[:2],['done','queued'])

if __name__=='__main__':unittest.main()
