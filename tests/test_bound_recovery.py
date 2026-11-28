import sqlite3
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import studio_coding as sc
import auth_policy

class BoundRecoveryMigrationTests(unittest.TestCase):
    def test_legacy_unique_binding_migration_preserves_foreign_keys(self):
        c=sqlite3.connect(':memory:')
        self.addCleanup(c.close)
        c.execute('PRAGMA foreign_keys=ON')
        c.executescript("""
        CREATE TABLE projects(id TEXT PRIMARY KEY);
        CREATE TABLE coding_jobs(id TEXT PRIMARY KEY);
        CREATE TABLE agent_queue(id TEXT PRIMARY KEY);
        CREATE TABLE studio_work_packages(project_id TEXT,adoption_version INTEGER,package_id TEXT,PRIMARY KEY(project_id,adoption_version,package_id));
        CREATE TABLE studio_coding_bindings(
          job_id TEXT PRIMARY KEY REFERENCES coding_jobs(id),
          project_id TEXT NOT NULL REFERENCES projects(id),
          queue_id TEXT NOT NULL UNIQUE REFERENCES agent_queue(id),
          adoption_version INTEGER NOT NULL,package_id TEXT NOT NULL,binding_digest TEXT NOT NULL,spec_digest TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL,
          UNIQUE(project_id,adoption_version,package_id),
          FOREIGN KEY(project_id,adoption_version,package_id) REFERENCES studio_work_packages(project_id,adoption_version,package_id));
        CREATE TABLE receipt(job_id TEXT REFERENCES studio_coding_bindings(job_id));
        INSERT INTO projects VALUES('p');INSERT INTO coding_jobs VALUES('j');INSERT INTO agent_queue VALUES('q');
        INSERT INTO studio_work_packages VALUES('p',1,'pkg');
        INSERT INTO studio_coding_bindings VALUES('j','p','q',1,'pkg','b','s','owner','t');
        INSERT INTO receipt VALUES('j');
        """)
        before=c.execute('SELECT rowid,* FROM studio_coding_bindings').fetchall()
        sc.migrate_retry_bindings(c)
        sc.migrate_retry_bindings(c)
        self.assertEqual(c.execute('SELECT rowid,* FROM studio_coding_bindings').fetchall(),before)
        self.assertEqual(c.execute('SELECT * FROM receipt').fetchall(),[('j',)])
        self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_retry_http_route_requires_project_write(self):
        self.assertEqual(auth_policy.scope(None,'POST','/api/projects/p/studio/work-packages/retry'),('p','write'))
