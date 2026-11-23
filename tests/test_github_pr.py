"""Offline, no-token tests for opt-in GitHub draft PR helper."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MOD_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'github_pr.py'
spec = importlib.util.spec_from_file_location('orbit_git', MOD_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class FakeResponse:
    def __init__(self, result): self.result = result
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def read(self): return json.dumps(self.result).encode()

class GitHubPRTests(unittest.TestCase):
    def artifact(self):
        return {'id':'ab123', 'project_id':'proj', 'stage_id':'po',
                'agent_id':'po-A', 'kind':'draft', 'content':'# Safe document'}

    def test_no_token_is_refused(self):
        with self.assertRaises(mod.GitHubError): mod.GitHubClient('')

    def test_validates_repo(self):
        c=mod.GitHubClient('dummy', opener=lambda req,timeout: None)
        with self.assertRaises(ValueError): c.draft_pr_for_artifact('../abc', self.artifact())

    def test_creates_draft_pr_and_never_merges(self):
        seen=[]
        responses=[{'default_branch':'main'}, {'commit':{'sha':'a'*40}}, {}, {},
                   {'html_url':'https://github.com/example/orbit/pull/1','number':1}]
        def opener(request, timeout):
            seen.append((request.get_method(), request.full_url, request.data))
            return FakeResponse(responses.pop(0))
        client=mod.GitHubClient('fake-secret', opener=opener)
        result=client.draft_pr_for_artifact('example/orbit', self.artifact(), branch='orbit/test')
        self.assertEqual(result['number'],1)
        self.assertEqual([item[0] for item in seen],['GET','GET','POST','PUT','POST'])
        self.assertTrue(json.loads(seen[-1][2])['draft'])
        self.assertFalse(any('/merge' in req[1] for req in seen))
        self.assertIn('docs/agent-deliverables/ab123.md',seen[-2][1])

    def test_dry_run_does_not_touch_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'orbit.sqlite'
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE artifacts (id TEXT, project_id TEXT, stage_id TEXT, agent_id TEXT, kind TEXT, content TEXT)')
                conn.execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?)', tuple(self.artifact().values()))
            with patch.object(mod.GitHubClient,'__init__',side_effect=AssertionError('network invoked')):
                self.assertEqual(mod.main(['--repo','example/orbit','--db',str(path),'--artifact-id','ab123']),0)

if __name__=='__main__': unittest.main()
