import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import studio_activity

class StudioActivityTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("""
        CREATE TABLE projects(id PRIMARY KEY);
        INSERT INTO projects VALUES('p'),('q');
        CREATE TABLE agent_queue(id,project_id,kind,status,control,reason,attempts,deferrals,checkpoint_stage,updated_at,retry_of);
        CREATE TABLE ai_usage(id,project_id,agent_id,lane,provider,model,purpose,run_id,started_at,elapsed_ms,status,input_tokens,output_tokens,total_tokens,coverage,source);
        CREATE TABLE inference_denials(seq INTEGER PRIMARY KEY,project_id,agent_id,run_id,reason,created_at);
        INSERT INTO agent_queue VALUES('job','p','pipeline','running','','',1,0,NULL,1,NULL);
        """)
        studio_activity.ensure_schema(self.c)
        self.stages=[dict(id='po')]
        self.handoff=dict(roles=[dict(stage_id='po',receipt=dict(run_id='r',mode='ollama',lanes=[]))])
    def role(self):
        return studio_activity.view(self.c,'p',self.stages,self.handoff)['roles'][0]
    def test_attempt_evidence_and_queue_binding(self):
        studio_activity.bind(self.c,'p','po','r','job','t')
        self.c.execute("INSERT INTO ai_usage VALUES('a','p','po-A','A','ollama','local','stage_draft','r',1,NULL,'pending',NULL,NULL,NULL,'unknown','none')")
        self.c.execute("INSERT INTO ai_usage VALUES('b','q','po-B','B','ollama','secret-other','stage_draft','r',1,1,'ok',1,1,2,'complete','provider')")
        a,b=self.role()['agents']
        self.assertEqual(a['state'],'ATTEMPT_PENDING_UNCONFIRMED')
        self.assertIsNone(a['stage_attempt']['total_tokens'])
        self.assertEqual(b['state'],'NO_EVIDENCE')
        self.assertIsNone(b['latest_attempt'])
        self.assertEqual(self.role()['queue']['id'],'job')
        self.c.execute("UPDATE agent_queue SET status='interrupted'")
        self.assertEqual(self.role()['agents'][0]['state'],'ATTEMPT_UNRESOLVED')
        self.c.execute("UPDATE ai_usage SET status='ok',elapsed_ms=5,total_tokens=0,coverage='complete' WHERE id='a'")
        a=self.role()['agents'][0]
        self.assertEqual(a['state'],'ATTEMPT_RETURNED')
        self.assertEqual(a['stage_attempt']['total_tokens'],0)
    def test_demo_and_unrelated_calls_are_not_current_stage(self):
        self.handoff['roles'][0]['receipt'].update(mode='demo',lanes=['A'])
        self.c.execute("INSERT INTO ai_usage VALUES('chat','p','po-B','B','ollama','local','agent_chat','other',1,5,'ok',2,3,5,'complete','provider')")
        a,b=self.role()['agents']
        self.assertEqual(a['state'],'DEMO_DRAFT_RECORDED')
        self.assertIsNone(a['stage_attempt'])
        self.assertEqual(b['state'],'NO_EVIDENCE')
        self.assertEqual(b['latest_attempt']['purpose'],'agent_chat')
        self.assertIsNone(b['stage_attempt'])
        with self.assertRaises(ValueError):studio_activity.bind(self.c,'q','po','r','job','t')
