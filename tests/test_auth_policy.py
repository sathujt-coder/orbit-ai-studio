import sqlite3, unittest, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import auth_policy, auth_store
class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        auth_store.ensure_schema(self.c)
        self.c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)')
        self.c.execute("INSERT INTO projects VALUES('p')")
        self.c.execute('CREATE TABLE coding_jobs(id TEXT,project_id TEXT)')
        self.c.execute("INSERT INTO coding_jobs VALUES('j','p')")
    def tearDown(self):self.c.close()
    def test_resource_lookup(self):
        self.assertEqual(auth_policy.scope(self.c,'GET','/api/coding/j/quality'),('p','read'))
        self.assertIsNone(auth_policy.scope(self.c,'GET','/api/coding/j/unknown'))
        self.assertIsNone(auth_policy.scope(self.c,'POST','/api/projects/p/run/extra'))
    def test_no_session(self):
        self.assertEqual(auth_policy.check(self.c,'GET','/api/bootstrap','',{}, {},8787)[0],401)
