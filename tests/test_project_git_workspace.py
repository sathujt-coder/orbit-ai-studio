import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import project_git_workspace as ws
import auth_policy


class ProjectGitWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=Path(self.temp.name)/'project.sqlite'
        self.body={'confirmation':ws.CONFIRMATION}

    def init(self,pid='project-a'):
        return ws.initialize(self.db,pid,self.body)

    def test_real_git_project_isolation_and_idempotency(self):
        self.assertEqual(ws.view(self.db,'project-a')['state'],'UNINITIALIZED')
        self.assertFalse(ws.location(self.db,'project-a').parent.exists())
        a=self.init()
        b=self.init('project-b')
        self.assertEqual(a['state'],'READY')
        self.assertEqual(b['state'],'READY')
        self.assertNotEqual(a['workspace_id'],b['workspace_id'])
        self.assertNotEqual(a['base_commit'],b['base_commit'])
        self.assertEqual(self.init(),a)
        self.assertEqual(ws.git(ws.location(self.db,'project-a'),'rev-parse','--is-bare-repository').strip(),b'true')
        self.assertEqual(ws.git(ws.location(self.db,'project-a'),'remote'),b'')
        self.assertTrue(all(a[k] is False for k in ws.FLAGS))
        self.assertEqual(ws.view(Path(self.temp.name)/'other.sqlite','project-a')['state'],'UNINITIALIZED')

    def test_explicit_confirmation_and_path_rejection(self):
        for body in ({},{'confirmation':ws.CONFIRMATION,'path':'/tmp'},
                     {'confirmation':ws.CONFIRMATION,'remote':'https://example.test'}):
            with self.assertRaises(ValueError):
                ws.initialize(self.db,'project-a',body)
        for pid in ('../a','/tmp/a','a/b','a\nb',''):
            with self.assertRaises(ValueError):
                ws.initialize(self.db,pid,self.body)
        self.assertFalse(ws.location(self.db,'project-a').parent.exists())

    def test_cross_project_copy_is_blocked(self):
        self.init()
        a=ws.location(self.db,'project-a')
        b=ws.location(self.db,'project-b')
        shutil.copytree(a,b)
        self.assertEqual(ws.view(self.db,'project-b')['state'],'BLOCK')
        with self.assertRaises(ValueError):self.init('project-b')
        self.assertEqual(ws.view(self.db,'project-a')['state'],'READY')

    def test_symlink_and_remote_config_blocked(self):
        self.init()
        a=ws.location(self.db,'project-a')
        b=ws.location(self.db,'project-b')
        b.symlink_to(a,target_is_directory=True)
        self.assertEqual(ws.view(self.db,'project-b')['state'],'BLOCK')
        with self.assertRaises(ValueError):self.init('project-b')
        with (a/'config').open('a') as f:f.write('\n[remote "origin"]\nurl = https://example.test\n')
        self.assertEqual(ws.view(self.db,'project-a')['state'],'BLOCK')
        with self.assertRaises(ValueError):self.init()

    def test_failed_initialization_never_publishes_partial_repo(self):
        real=ws.git
        def failing(repo,*args,**kw):
            if args[0]=='update-ref':raise ValueError('injected failure')
            return real(repo,*args,**kw)
        with patch.object(ws,'git',side_effect=failing):
            with self.assertRaisesRegex(ValueError,'injected'):self.init()
        path=ws.location(self.db,'project-a')
        self.assertFalse(path.exists())
        self.assertEqual(list(path.parent.iterdir()),[])
        self.assertEqual(self.init()['state'],'READY')

    def test_git_environment_and_route_permissions(self):
        with patch.dict(os.environ,{'GIT_DIR':'/tmp/invalid','GIT_OBJECT_DIRECTORY':'/tmp/invalid',
                                   'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.bare',
                                   'GIT_CONFIG_VALUE_0':'false','GITHUB_TOKEN':'fixture-secret'}):
            self.assertEqual(self.init()['state'],'READY')
        path='/api/projects/project-a/engineering/workspace'
        self.assertEqual(auth_policy.scope(None,'GET',path),('project-a','read'))
        self.assertEqual(auth_policy.scope(None,'POST',path),('project-a','manage'))
        self.assertIsNone(auth_policy.scope(None,'POST',path+'/push'))
        repo=ws.location(self.db,'project-a')
        repo.chmod(0o755)
        self.assertEqual(ws.view(self.db,'project-a')['state'],'BLOCK')
