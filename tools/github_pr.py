#!/usr/bin/env python3
"""Export one ORBIT artifact to a *draft* GitHub PR. Opt-in --apply; stdlib only.

The ChatGPT GitHub connector is NOT a credential for this local process.
Set a separately authorized GITHUB_TOKEN (prefer a short-lived GitHub App token).
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
VALID_REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
VALID_ARTIFACT = re.compile(r'^[A-Za-z0-9_-]{1,80}$')


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str, opener=None):
        if not token:
            raise GitHubError('GITHUB_TOKEN is required for --apply')
        self._token = token
        self._opener = opener or urllib.request.urlopen

    def request(self, method: str, route: str, payload=None):
        if not route.startswith('/') or route.startswith('//'):
            raise ValueError('GitHub API route must be relative to api.github.com')
        url = 'https://api.github.com' + route
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, method=method, headers={
            'Accept': 'application/vnd.github+json',
            'Authorization': 'Bearer ' + self._token,
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'orbit-ai-github-pr/0.2',
            'Content-Type': 'application/json',
        })
        try:
            with self._opener(req, timeout=25) as resp:
                raw = resp.read()
                return json.loads(raw.decode('utf-8')) if raw else {}
        except urllib.error.HTTPError as exc:
            # Do not print request headers or tokens; GitHub body can be verbose.
            raise GitHubError(f'GitHub API {method} returned HTTP {exc.code} on {route.split("?")[0]}') from None
        except urllib.error.URLError as exc:
            raise GitHubError('Cannot reach GitHub API; check network/proxy') from None

    def draft_pr_for_artifact(self, repo: str, artifact: dict, branch: str | None = None):
        if not VALID_REPO.fullmatch(repo) or '..' in repo:
            raise ValueError('Repository must be owner/repo')
        artifact_id = str(artifact['id'])
        if not VALID_ARTIFACT.fullmatch(artifact_id):
            raise ValueError('Unsafe artifact ID')
        # Only agent deliverables, not executable code or GitHub workflow files.
        path = f'docs/agent-deliverables/{artifact_id}.md'
        branch = branch or f'orbit/artifact-{artifact_id}-{uuid.uuid4().hex[:6]}'
        if not re.fullmatch(r'orbit/[A-Za-z0-9._/-]+', branch) or '..' in branch:
            raise ValueError('Branch must begin with orbit/ and have safe characters')
        api = '/repos/' + repo
        meta = self.request('GET', api)
        default = meta['default_branch']
        base_branch = self.request('GET', api + '/branches/' + urllib.parse.quote(default, safe=''))
        sha = base_branch['commit']['sha']
        self.request('POST', api + '/git/refs', {'ref': 'refs/heads/' + branch, 'sha': sha})
        content = artifact['content']
        if not isinstance(content, str) or len(content.encode('utf-8')) > 200000:
            raise ValueError('Artifact must be text at most 200 KB')
        safe_path = urllib.parse.quote(path, safe='/')
        self.request('PUT', api + '/contents/' + safe_path, {
            'message': f'docs(orbit): agent artifact {artifact_id}',
            'content': base64.b64encode(content.encode('utf-8')).decode('ascii'),
            'branch': branch,
        })
        title = f"ORBIT: {artifact['stage_id']} / {artifact['agent_id']} ({artifact['kind']})"
        body = (
            'ORBIT AI generated artifact for independent review.\\n\\n'
            f"- Project ID: `{artifact['project_id']}`\\n"
            f"- Artifact ID: `{artifact_id}`\\n"
            f"- Stage: `{artifact['stage_id']}`\\n"
            f"- Agent: `{artifact['agent_id']}`\\n\\n"
            'Review A↔B evidence, CI and human approval are required. '
            'This integration never merges or deploys automatically.'
        ).replace('\\n','\n')
        result = self.request('POST', api + '/pulls', {
            'title': title, 'head': branch, 'base': default,
            'body': body, 'draft': True,
        })
        return {'url': result['html_url'], 'number': result['number'], 'branch': branch, 'path': path}


def load_artifact(dbfile: Path, artifact_id: str):
    if not VALID_ARTIFACT.fullmatch(artifact_id):
        raise ValueError('Invalid artifact ID')
    with sqlite3.connect(dbfile) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT id,project_id,stage_id,agent_id,kind,content '
                           'FROM artifacts WHERE id=?', (artifact_id,)).fetchone()
        if row is None:
            raise ValueError('Artifact not found in local database')
        return dict(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Prepare or open a draft GitHub PR for an ORBIT artifact')
    parser.add_argument('--repo', required=True, help='owner/repo')
    parser.add_argument('--artifact-id', required=True, help='ORBIT artifact ID from database')
    parser.add_argument('--db', type=Path, default=ROOT / 'company.sqlite')
    parser.add_argument('--apply', action='store_true', help='Explicitly create branch, file, draft PR on GitHub')
    args = parser.parse_args(argv)
    if not VALID_REPO.fullmatch(args.repo) or '..' in args.repo:
        parser.error('--repo must be owner/repo')
    try:
        artifact = load_artifact(args.db, args.artifact_id)
        path = f"docs/agent-deliverables/{artifact['id']}.md"
        if not args.apply:
            print(json.dumps({'mode':'dry-run', 'repo':args.repo, 'path':path,
                              'stage':artifact['stage_id'], 'agent':artifact['agent_id'],
                              'note':'No GitHub changes made; pass --apply to open draft PR'},ensure_ascii=False,indent=2))
            return 0
        result = GitHubClient(os.environ.get('GITHUB_TOKEN', '')).draft_pr_for_artifact(args.repo, artifact)
        print(json.dumps({'mode':'created', **result}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, sqlite3.Error, GitHubError, KeyError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
