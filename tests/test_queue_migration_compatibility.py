"""P6.2h.1: historical queue migration, including persisted child evidence."""
import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import agent_queue as q
import auth_store
import model_provider as mp

# Historical constraint literals, deliberately not derived from the current kind list.
OLD_CHECK="CHECK(kind IN ('pipeline','coding','requirements','planning','decomposition'))"
CURRENT_CHECK="CHECK(kind IN ('pipeline','coding','requirements','planning','decomposition','planning_review'))"

class QueueMigrationCompatibility(unittest.TestCase):
    def fixture(self,check=OLD_CHECK):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close);c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)')
        c.execute("INSERT INTO projects VALUES('p')")
        auth_store.ensure_schema(c)
        auth_store.create_user(c,'owner','fixture-password-123');auth_store.grant(c,'owner','p','owner')
        q.ensure_schema(c)
        sql=c.execute("SELECT sql FROM sqlite_master WHERE name='agent_queue'").fetchone()[0]
        self.assertIn(CURRENT_CHECK,sql)
        c.commit();c.execute('PRAGMA foreign_keys=OFF')
        c.execute('DROP TABLE agent_queue')
        c.execute(sql.replace(CURRENT_CHECK,check))
        c.execute("CREATE UNIQUE INDEX aq_active_kind ON agent_queue(project_id,kind) WHERE status IN ('queued','running','paused','waiting_approval')")
        c.execute("CREATE UNIQUE INDEX aq_one_running_project ON agent_queue(project_id) WHERE status='running'")
        c.execute("CREATE INDEX aq_dispatch ON agent_queue(status,available_at,priority,created_at)")
        c.execute('CREATE INDEX local_queue_actor ON agent_queue(actor)')
        c.commit();c.execute('PRAGMA foreign_keys=ON')
        return c

    def test_p62g_upgrade_preserves_rows_links_events_indexes_and_is_idempotent(self):
        c=self.fixture()
        lanes=mp.load_config(dict(AI_PROVIDER='ollama',AI_MODEL_A='a',AI_MODEL_B='b'))
        parent=q.enqueue(c,'p','planning','owner',0,lanes,now=100)
        child=q.enqueue(c,'p','decomposition','owner',0,lanes,dependency_id=parent,now=101)
        c.execute('UPDATE agent_queue SET attempts=2,deferrals=1 WHERE id=?',(parent,))
        c.execute('CREATE TABLE old_evidence(queue_id TEXT REFERENCES agent_queue(id), payload TEXT)')
        c.execute('INSERT INTO old_evidence VALUES(?,?)',(child,'preserve this evidence'))
        c.commit()
        def rows():return [tuple(x) for x in c.execute('SELECT rowid,* FROM agent_queue ORDER BY rowid')]
        def events():return [tuple(x) for x in c.execute('SELECT * FROM agent_queue_events ORDER BY seq')]
        def indexes():return [tuple(x) for x in c.execute("SELECT name,sql FROM sqlite_master WHERE tbl_name='agent_queue' AND type='index' AND sql IS NOT NULL ORDER BY name")]
        before=(rows(),events(),indexes())
        q.ensure_schema(c)
        self.assertEqual((rows(),events(),indexes()),before)
        self.assertEqual(tuple(c.execute('SELECT * FROM old_evidence').fetchone()),(child,'preserve this evidence'))
        self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])
        review=q.enqueue(c,'p','planning_review','owner',0,lanes,dependency_id=child,now=102)
        self.assertEqual(q.get(c,'p',review)['dependency_id'],child)
        with self.assertRaises(ValueError):q.enqueue(c,'p','planning_review','owner',0,lanes,now=103)
        c.commit()
        after=(rows(),events(),indexes())
        q.ensure_schema(c);q.ensure_schema(c)
        self.assertEqual((rows(),events(),indexes()),after)
        self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])

    def test_partial_schema_with_review_is_not_mistaken_for_current(self):
        c=self.fixture("CHECK(kind IN ('pipeline','coding','requirements','planning_review'))")
        lanes=mp.load_config(dict(AI_PROVIDER='ollama',AI_MODEL_A='a',AI_MODEL_B='b'))
        old=q.enqueue(c,'p','planning_review','owner',0,lanes,now=100)
        c.commit();q.ensure_schema(c)
        self.assertEqual(q.get(c,'p',old)['kind'],'planning_review')
        q.enqueue(c,'p','planning','owner',0,lanes,now=101)
        q.enqueue(c,'p','decomposition','owner',0,lanes,now=102)
        self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])

    def test_unknown_kind_constraint_fails_closed(self):
        c=self.fixture("CHECK(kind IN ('pipeline','coding','unknown_kind'))")
        before=c.execute("SELECT sql FROM sqlite_master WHERE name='agent_queue'").fetchone()[0]
        with self.assertRaises(RuntimeError):q.ensure_schema(c)
        self.assertEqual(c.execute("SELECT sql FROM sqlite_master WHERE name='agent_queue'").fetchone()[0],before)
        self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
