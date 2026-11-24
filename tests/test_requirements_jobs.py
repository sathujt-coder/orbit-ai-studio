import json
import sqlite3
import unittest
from test_product_requirements import document
import test_agent_queue
import agent_queue as q
import auth_policy
import model_provider as mp
import product_requirements as pr
import requirements_jobs as jobs

class RequirementsQueueTests(unittest.TestCase):
    def setUp(self):
        fixture=test_agent_queue.QueueTests();fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.c=fixture.c
        self.c.execute("ALTER TABLE projects ADD COLUMN idea TEXT NOT NULL DEFAULT 'Save links'")
        pr.ensure_schema(self.c);jobs.ensure_schema(self.c)
        self.lanes=mp.load_config(dict(AI_PROVIDER='ollama',AI_MODEL_A='model-a',AI_MODEL_B='model-b'))
    def add(self):
        return jobs.enqueue(self.c,'p','owner',0,self.lanes,'t')
    def evidence(self,ready=True):
        return dict(document=document(),proposals={},reviews={},final_review=dict(blocking=[] if ready else ['Missing scope']),ready_for_human_review=ready)
    def finish(self,identifier,ready=True):
        row=q.claim(self.c,9999999999,'t')
        self.assertEqual(row['id'],identifier)
        result=jobs.persist(self.c,'p',identifier,self.evidence(ready),self.lanes,'t')
        q.boundary(self.c,row,result,9999999999,'t')
        return jobs.latest(self.c,'p')
    def body(self,row):
        return dict(queue_id=row['queue_id'],digest=row['digest'],expected_version=row['base_version'],confirmation='ADOPT AI REQUIREMENTS')
    def test_adopt_provenance_and_gate(self):
        i=self.add();row=self.finish(i)
        self.assertTrue(row['can_adopt'])
        self.assertIsNone(jobs.latest(self.c,'p2'))
        with self.assertRaises(PermissionError):jobs.adopt(self.c,'p','viewer',self.body(row),'t')
        result=jobs.adopt(self.c,'p','owner',self.body(row),'t')
        self.assertFalse(result['planning_ready'])
        self.assertEqual(jobs.latest(self.c,'p')['adopted_version'],1)
        with self.assertRaises(ValueError):jobs.adopt(self.c,'p','owner',self.body(row),'t')
    def test_blocked_review_and_stale(self):
        i=self.add();row=self.finish(i,False)
        self.assertEqual(row['status'],'dead')
        self.assertFalse(row['can_adopt'])
        i=self.add();row=self.finish(i)
        pr.save(self.c,'p','owner',dict(expected_version=0,document=document()),'t')
        with self.assertRaises(ValueError):jobs.adopt(self.c,'p','owner',self.body(row),'t')
    def test_demo_and_crash(self):
        with self.assertRaises(ValueError):jobs.enqueue(self.c,'p','owner',0,mp.load_config({}),'t')
        i=self.add();q.claim(self.c,9999999999,'t');q.recover(self.c,9999999999,'t')
        self.assertEqual(jobs.latest(self.c,'p')['status'],'interrupted')
        self.assertIsNone(q.claim(self.c,9999999999,'t'))
    def test_authorization(self):
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/requirements/discover'),('p','write'))
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/requirements/adopt'),('p','write'))
    def test_legacy_queue_migration(self):
        # Rebuild a minimal legacy queue from the actual original DDL, then upgrade.
        old=sqlite3.connect(':memory:');self.addCleanup(old.close)
        old.execute('PRAGMA foreign_keys=ON')
        old.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)')
        schema=self.c.execute("SELECT sql FROM sqlite_master WHERE name='agent_queue'").fetchone()[0]
        old.execute(schema.replace("'pipeline','coding','requirements'","'pipeline','coding'"))
        old.execute("INSERT INTO projects VALUES('p')")
        old.execute("""INSERT INTO agent_queue(id,project_id,kind,mode,actor,priority,provider_revision,provider_fingerprint,status,available_at,created_at,updated_at)
            VALUES('old','p','pipeline','next','owner',5,0,'fp','queued',1,1,1)""")
        old.execute("CREATE TABLE agent_queue_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL REFERENCES agent_queue(id),status TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL)")
        old.execute("INSERT INTO agent_queue_events(task_id,status,reason,created_at) VALUES('old','queued','accepted',1)")
        old.commit();q.ensure_schema(old)
        self.assertEqual(old.execute("SELECT id FROM agent_queue").fetchone()[0],'old')
        self.assertEqual(old.execute("SELECT task_id FROM agent_queue_events").fetchone()[0],'old')
        self.assertEqual(old.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertIsNone(old.execute('PRAGMA foreign_key_check').fetchone())
