"""Actual SQLite and Git regression tests for isolated fixture copies."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import project_git_workspace as ws
import isolated_workspace_snapshot as snap

class IsolatedWorkspaceSnapshotTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.db=self.root/'source.sqlite'
        self.copy=self.root/'copy.sqlite'
        self.c=sqlite3.connect(self.db)
        self.addCleanup(self.c.close)
        self.c.row_factory=sqlite3.Row
        self.c.executescript("""CREATE TABLE evidence(project_id TEXT, version INTEGER, digest TEXT);
            INSERT INTO evidence VALUES('p',1,'original');""")
        ws.initialize(self.db,'p',{'confirmation':ws.CONFIRMATION})

    def evidence(self,c,pid):
        return [dict(r) for r in c.execute('SELECT * FROM evidence WHERE project_id=? ORDER BY version',(pid,))]

    def clone(self):
        return snap.copy_project_snapshot(self.c,self.copy,'p',self.evidence)

    def test_exact_sqlite_and_git_snapshot_independent(self):
        before=self.clone()
        with closing(sqlite3.connect(self.copy)) as c:
            c.row_factory=sqlite3.Row
            self.assertEqual(snap.capture(c,'p',self.evidence),before)
            self.assertNotEqual(ws.location(self.db,'p').stat().st_ino,ws.location(self.copy,'p').stat().st_ino)
            c.execute("UPDATE evidence SET digest='copy-only'");c.commit()
        self.assertEqual(snap.capture(self.c,'p',self.evidence),before)
        self.assertEqual(ws.view(self.copy,'p'),ws.view(self.db,'p'))

    def test_missing_source_workspace_rejected_without_reinitialization(self):
        import shutil
        shutil.rmtree(ws.location(self.db,'p'))
        with self.assertRaisesRegex(ValueError,'not READY'):self.clone()
        self.assertFalse(self.copy.exists())
        self.assertEqual(ws.view(self.db,'p')['state'],'UNINITIALIZED')

    def test_tampered_source_workspace_rejected(self):
        (ws.location(self.db,'p')/'HEAD').write_text('wrong ref')
        with self.assertRaisesRegex(ValueError,'not READY'):self.clone()
        self.assertFalse(self.copy.exists())
        self.assertEqual(ws.view(self.db,'p')['state'],'BLOCK')

    def test_copy_tampering_detected_and_source_unchanged(self):
        real=snap.shutil.copytree
        before=snap.capture(self.c,'p',self.evidence)
        def corrupt(src,dst,*args,**kwargs):
            result=real(src,dst,*args,**kwargs)
            if Path(dst)==ws.location(self.copy,'p'):
                (Path(dst)/'HEAD').write_text('wrong ref')
            return result
        with patch.object(snap.shutil,'copytree',side_effect=corrupt):
            with self.assertRaisesRegex(ValueError,'not READY'):self.clone()
        self.assertEqual(snap.capture(self.c,'p',self.evidence),before)
        self.assertEqual(ws.view(self.copy,'p')['state'],'BLOCK')

    def test_sqlite_evidence_mismatch_detected(self):
        before=snap.capture(self.c,'p',self.evidence)
        def mismatched(c,pid):
            rows=self.evidence(c,pid)
            if snap.database_path(c)==self.copy:rows[0]['digest']='bad'
            return rows
        with self.assertRaisesRegex(ValueError,'snapshot mismatch'):
            snap.copy_project_snapshot(self.c,self.copy,'p',mismatched)
        self.assertEqual(snap.capture(self.c,'p',self.evidence),before)

    def test_existing_destination_never_overwritten(self):
        self.copy.write_bytes(b'untouched')
        with self.assertRaisesRegex(ValueError,'must be new'):self.clone()
        self.assertEqual(self.copy.read_bytes(),b'untouched')
        with self.assertRaisesRegex(ValueError,'must be new'):
            snap.copy_project_snapshot(self.c,self.db,'p',self.evidence)

if __name__=='__main__':unittest.main()
