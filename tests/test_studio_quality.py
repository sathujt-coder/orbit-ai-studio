import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import studio_quality
import studio_handoff

class StudioQualityTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("""
        CREATE TABLE projects(id PRIMARY KEY);
        INSERT INTO projects VALUES('p'),('q');
        CREATE TABLE tasks(project_id,stage_id,status,approved_at,position DEFAULT 0);
        CREATE TABLE artifacts(id PRIMARY KEY,project_id,stage_id,agent_id,kind,content,run_id);
        CREATE TABLE reviews(id PRIMARY KEY,project_id,stage_id,reviewer_id,author_id,verdict,score,feedback,created_at,run_id);
        INSERT INTO tasks VALUES('p','po','done',NULL,0);
        """)
        self.stages=[dict(id='po',approval=False)]
        studio_handoff.ensure_schema(self.c)
    def seed(self,pid='p',rid='r',score=80):
        for lane in ('A','B'):
            self.c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',(pid+rid+lane,pid,'po','po-'+lane,'draft','draft',rid))
            self.c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?,?)',(pid+rid+lane,pid,'po','po-'+lane,'po-'+('B' if lane=='A' else 'A'),'APPROVE',score,'feedback','t',rid))
        self.c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',(pid+rid+'F',pid,'po','po-A','final','final',rid))
    def role(self):
        tasks=[dict(x) for x in self.c.execute("SELECT * FROM tasks WHERE project_id='p'")]
        h=studio_handoff.view(self.c,'p',self.stages,tasks)
        return studio_quality.view(self.c,'p',self.stages,tasks,h)['roles'][0]
    def test_review_evidence_and_low_score(self):
        self.seed('q',score=99);self.seed(score=79)
        role=self.role()
        self.assertEqual(role['state'],'BLOCK')
        self.assertEqual({x['score'] for x in role['reviews']},{79})
        self.assertEqual(role['final']['id'],'prF')
        self.assertFalse(role['execution_authorized'])
        self.seed(rid='new')
        self.assertEqual(self.role()['state'],'REVIEWED_OUTPUT')
        self.assertEqual(self.role()['run_id'],'new')
    def test_human_approval_and_stale_receipt(self):
        self.seed()
        self.stages[0]['approval']=True
        self.c.execute("UPDATE tasks SET status='awaiting_approval'")
        self.assertEqual(self.role()['state'],'BLOCK')
        self.c.execute("UPDATE tasks SET status='approved',approved_at='t'")
        self.assertEqual(self.role()['state'],'REVIEWED_OUTPUT')
        studio_handoff.prepare(self.c,'p',self.stages,'po','next','demo','t')
        role=self.role()
        self.assertEqual(role['run_id'],'next')
        self.assertFalse(role['reviews'])
        self.assertNotEqual(role['state'],'REVIEWED_OUTPUT')
        self.c.execute("UPDATE studio_handoff_receipts SET snapshot='{}'")
        self.assertEqual(self.role()['state'],'INVALID')
