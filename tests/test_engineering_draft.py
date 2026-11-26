"""Local Git reconstruction and isolated GitHub request contract regressions."""
import sqlite3
import unittest
from unittest.mock import patch
import test_engineering_sandbox as sandbox_fixture
import engineering_draft as ed
import auth_policy
from engineering_draft_fixture import FakeRemote

class EngineeringDraftTests(unittest.TestCase):
    def setUp(self):
        self.f=sandbox_fixture.EngineeringSandboxTests(methodName='test_replay_and_immutable_receipt')
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()
        self.c,self.db,self.pid,self.jid=self.f.c,self.f.db,self.f.pid,self.f.jid
        self.replay=self.f.run_replay()
        ed.ensure_schema(self.c)
        self.c.commit()
        self.remote=FakeRemote()
        self.repo,self.base,self.base_sha='example/orbit','main','a'*40

    def plan(self):
        return ed.prepare(self.c,self.db,self.pid,self.jid,self.repo,self.base,self.base_sha)

    def apply(self,**changes):
        plan,_=self.plan();digest=ed.pp.digest(plan)
        kwargs=dict(actor='owner',repo=self.repo,base=self.base,base_sha=self.base_sha,
                    expected_digest=digest,confirmation='CREATE ENGINEERING DRAFT '+self.jid+' '+self.repo+' '+digest,
                    client=self.remote)
        kwargs.update(changes)
        return ed.publish(self.c,self.db,self.pid,self.jid,**kwargs)

    def test_dry_run_selected_git_and_redacted_metadata(self):
        plan,files=self.plan()
        self.assertEqual(plan['source']['git'],self.replay['git']['B'])
        self.assertEqual(plan['source']['sandbox_digest'],self.replay['digest'])
        self.assertEqual(ed.view(self.c,self.db,self.pid,self.jid)['state'],'AWAITING_EXPLICIT_DRAFT')
        self.assertEqual(self.remote.calls,[])
        self.assertTrue(all('/candidate-B/' in f['path'] or f['path'].endswith('/VERIFICATION.json') for f in files))
        self.assertNotIn('rationale',files[-1]['content'])
        self.assertNotIn('output',files[-1]['content'])

    def test_publish_one_atomic_tree_and_draft_only(self):
        out=self.apply()
        self.assertTrue(out['remote']['draft'])
        self.assertTrue(all(out[k] is False for k in ed.FLAGS))
        writes=[(r,p) for m,r,p in self.remote.calls if m=='POST']
        self.assertEqual(sum(r.endswith('/git/trees') for r,p in writes),1)
        self.assertEqual(sum(r.endswith('/git/commits') for r,p in writes),1)
        self.assertEqual(sum(r.endswith('/pulls') for r,p in writes),1)
        self.assertTrue(all('/merge' not in r and '/deployments' not in r for r,p in writes))
        self.assertEqual(ed.view(self.c,self.db,self.pid,self.jid)['state'],'CREATED_DRAFT')
        before=len(self.remote.calls)
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(len(self.remote.calls),before)

    def test_confirmation_digest_and_permission(self):
        with self.assertRaises(PermissionError):self.apply(confirmation='yes')
        with patch.object(ed.pp,'check_role',side_effect=PermissionError):
            with self.assertRaises(PermissionError):self.apply()
        with self.assertRaises(PermissionError):self.apply(repo='other/repo')
        self.assertEqual(self.remote.calls,[])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_draft_exports').fetchone()[0],0)
        path='/api/projects/'+self.pid+'/engineering/draft-pr/'+self.jid
        self.assertEqual(auth_policy.scope(self.c,'GET',path),(self.pid,'read'))
        self.assertIsNone(auth_policy.scope(self.c,'POST',path))

    def test_remote_base_mismatch_never_writes_and_blocks_retry(self):
        self.remote.base_sha='f'*40
        with self.assertRaises(ValueError):self.apply()
        self.assertTrue(all(m=='GET' for m,r,p in self.remote.calls))
        self.assertEqual(ed.view(self.c,self.db,self.pid,self.jid)['state'],'RECONCILE_REQUIRED')
        before=len(self.remote.calls)
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(len(self.remote.calls),before)

    def test_remote_tree_mutation_stops_before_ref(self):
        actual=self.remote.request
        def bad(m,r,p=None):
            result=actual(m,r,p)
            if m=='GET' and '/git/trees/'+'c'*40 in r:result['tree'][0]['sha']='0'*40
            return result
        self.remote.request=bad
        with self.assertRaises(ValueError):self.apply()
        self.assertFalse(any(r.endswith('/git/refs') or r.endswith('/pulls') for m,r,p in self.remote.calls))
        self.assertEqual(ed.view(self.c,self.db,self.pid,self.jid)['state'],'RECONCILE_REQUIRED')

    def test_ambiguous_pr_response_no_retry(self):
        actual=self.remote.request
        def bad(m,r,p=None):
            result=actual(m,r,p)
            if r.endswith('/pulls'):result['draft']=False
            return result
        self.remote.request=bad
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(ed.view(self.c,self.db,self.pid,self.jid)['state'],'RECONCILE_REQUIRED')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM engineering_draft_results').fetchone()[0],0)

    def test_immutable_result_and_stale_source(self):
        self.apply()
        for table in ('engineering_draft_exports','engineering_draft_results'):
            for sql in ('UPDATE '+table+' SET digest=\'bad\'','DELETE FROM '+table,
                        'INSERT OR REPLACE INTO '+table+' SELECT * FROM '+table):
                with self.assertRaises(sqlite3.IntegrityError):self.c.execute(sql)
                self.c.rollback()
        self.f.fixture.evidence['report_digest']='changed'
        self.assertEqual(ed.view(self.c,self.db,self.pid,self.jid)['state'],'STALE_OR_INVALID')

    def test_historical_legacy_export_blocks(self):
        self.c.execute('CREATE TABLE code_pr_exports(job_id TEXT PRIMARY KEY)')
        self.c.execute('INSERT INTO code_pr_exports VALUES(?)',(self.jid,))
        self.c.commit()
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(self.remote.calls,[])

if __name__=='__main__':unittest.main()
