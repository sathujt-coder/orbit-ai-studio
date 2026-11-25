import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import studio_handoff

class StudioHandoffTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.addCleanup(self.c.close)
        self.c.executescript("""
        CREATE TABLE tasks(project_id,stage_id,status);
        CREATE TABLE artifacts(id PRIMARY KEY,project_id,stage_id,agent_id,kind,content,run_id);
        CREATE TABLE reviews(project_id,stage_id,reviewer_id,author_id,verdict,score,run_id);
        """)
        self.stages=[dict(id='po',approval=False),dict(id='security',approval=True),dict(id='devops',approval=True)]
        for s in self.stages:self.c.execute('INSERT INTO tasks VALUES(?,?,?)',('p',s['id'],'done'))
    def seed(self,sid,run='r',pid='p',score=80):
        for lane in ('A','B'):
            self.c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',(pid+sid+run+lane,pid,sid,sid+'-'+lane,'draft','draft',run))
            self.c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(pid,sid,sid+'-'+lane,sid+'-'+('B' if lane=='A' else 'A'),'APPROVE',score,run))
        self.c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)',(pid+sid+run+'F',pid,sid,sid+'-A','final','final '+run,run))
    def roles(self):
        tasks=self.c.execute("SELECT * FROM tasks WHERE project_id='p'").fetchall()
        return studio_handoff.view(self.c,'p',self.stages,tasks)['roles']
    def test_current_reviewed_output_and_human_gate(self):
        self.seed('po');self.seed('security')
        a,b,d=self.roles()
        self.assertEqual(a['output']['status'],'reviewed_output')
        self.assertEqual(a['output']['version'],1)
        self.assertEqual(len(a['output']['content_digest']),64)
        self.assertEqual(b['input_status'],'reviewed_sources_available')
        self.assertEqual(b['output']['status'],'blocked')
        self.assertEqual(d['input_status'],'blocked')
        self.c.execute("UPDATE tasks SET status='approved' WHERE stage_id='security'")
        self.assertEqual(self.roles()[2]['input_status'],'reviewed_sources_available')
        self.assertEqual(self.roles()[2]['consumption_status'],'NOT_RECORDED')
        self.assertFalse(self.roles()[2]['execution_authorized'])
    def test_reject_missing_cross_project_low_score_and_superseded(self):
        self.seed('po',pid='q')
        self.assertEqual(self.roles()[0]['output']['reason'],'missing_final')
        self.seed('po',score=79)
        self.assertEqual(self.roles()[0]['output']['reason'],'review_or_source_invalid')
        self.seed('po',run='r2')
        self.assertEqual(self.roles()[0]['output']['version'],2)
        self.c.execute("INSERT INTO artifacts VALUES('new','p','po','po-A','draft','new','r3')")
        self.assertEqual(self.roles()[0]['output']['status'],'blocked')
    def test_current_digest_changes_without_claiming_immutable_receipt(self):
        self.seed('po')
        before=self.roles()[0]['output']['content_digest']
        self.c.execute("UPDATE artifacts SET content='changed' WHERE kind='final'")
        self.assertNotEqual(before,self.roles()[0]['output']['content_digest'])
        self.assertEqual(self.roles()[1]['consumption_status'],'NOT_RECORDED')
