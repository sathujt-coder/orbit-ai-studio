"""Real SQLite and production contracts; synthetic adoption candidate and sandbox transport.
Not real-model or real-Docker acceptance. Browser suite exercises actual planning adoption.
"""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import server
import auth_store
import coding_factory as cf
import agent_queue as aq
import project_planning as pp
import work_package_binding as wb
import studio_coding as sc
import studio_verification as qa
import verification_factory as vf
from test_verification_factory import FakeDocker,PY_IMG

class StudioEndToEnd(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=patch.object(server,'DB_PATH',Path(temp.name)/'studio.sqlite');p.start();self.addCleanup(p.stop)
        server.init_db()
        with server.db() as c:
            self.pid=server.create_project('Studio fixture','Trusted source contract integration','Web app',c)
            self.other=server.create_project('Other fixture','Private project','Web app',c)
            for user,role in [('fixture-owner','owner'),('fixture-dev','developer'),('fixture-reviewer','reviewer'),('fixture-viewer','viewer')]:
                auth_store.create_user(c,user,'fixture-password-long')
                auth_store.grant(c,user,self.pid,role)
        self.actor='fixture-owner'
    def test_atomic_begin_callback_rollback(self):
        # Exercise production coding begin + real queue and inject fault AFTER
        # both rows exist, before commit. No inference is dispatched.
        revision,lanes=server.provider_snapshot()
        def insert(c,jid):
            qid=aq.enqueue(c,self.pid,'coding',self.actor,revision,lanes,coding_job_id=jid,routing=server.ROUTING['fingerprint'])
            self.assertEqual(aq.get(c,self.pid,qid)['coding_job_id'],jid)
            self.assertEqual(c.execute('SELECT status FROM coding_jobs WHERE id=?',(jid,)).fetchone()[0],'queued')
            raise sqlite3.IntegrityError('injected binding persistence fault')
        with self.assertRaisesRegex(sqlite3.IntegrityError,'injected'):
            cf.begin(server.db,server.LOCK,self.pid,'Trusted integration fixture specification',server.uid,server.now,server.log,None,enqueue=insert)
        with server.db() as c:
            for table in ('coding_jobs','agent_queue','studio_coding_bindings'):
                self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table+' WHERE project_id=?',(self.pid,)).fetchone()[0],0)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_real_rbac_and_cross_project_denial(self):
        with server.db() as c:
            self.assertEqual(server.workflow_permissions(c,self.pid,'fixture-dev'),dict(project_id=self.pid,can_write=True,can_approve=False))
            self.assertEqual(server.workflow_permissions(c,self.pid,'fixture-reviewer'),dict(project_id=self.pid,can_write=False,can_approve=True))
            self.assertFalse(server.workflow_permissions(c,self.other,'fixture-owner')['can_write'])
            for user in ('fixture-viewer','fixture-reviewer'):
                with self.assertRaises(PermissionError):
                    sc.request(c,self.pid,user,{})
            with self.assertRaises(PermissionError):qa.attest(c,self.pid,'fixture-dev',{},server.now())
