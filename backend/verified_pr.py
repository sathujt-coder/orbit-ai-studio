"""ORBIT v0.5: manually authorized draft PR for independently verified code.

Generated files are kept under agent-proposals/<job>/, NEVER written over the
application source. This module never merges, executes code or deploys.
"""
from __future__ import annotations
import base64
import json
from pathlib import Path
import re
import sys
import uuid
from urllib.parse import quote

from coding_factory import safe_path
from verification_factory import safe_job, plan_lane
from web_candidate_selection import compare as compare_candidates

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
from github_pr import GitHubClient, GitHubError, VALID_REPO

JOB_ID = re.compile(r'^[A-Za-z0-9_-]{1,80}$')


def verified_bundle(job, evidence, *, decision=None):
    """Recheck all proofs against current persisted code, not stale assertions."""
    proposals = safe_job(job)
    if not JOB_ID.fullmatch(str(job['id'])):
        raise ValueError('Invalid job id')
    if (not isinstance(evidence, dict) or evidence.get('job_id') != job['id'] or
            evidence.get('project_id') != job['project_id'] or
            evidence.get('gate') != 'PASS' or evidence.get('verdict') != 'passed' or
            evidence.get('approval') != 'local_cli_explicit'):
        raise ValueError('A passing, approved sandbox verification is required')
    lanes = evidence.get('lanes')
    if not isinstance(lanes, dict) or set(lanes) != {'A', 'B'}:
        raise ValueError('Both verification lanes are required')
    summary = {}
    for lane, proposal in proposals.items():
        evidence_lane = lanes[lane]
        if not isinstance(evidence_lane, dict) or evidence_lane.get('status') != 'passed':
            raise ValueError('Both agent lanes must pass in isolated workspaces')
        expected = plan_lane(proposal)
        if expected['blocking_reasons'] or evidence_lane.get('sha256') != expected['sha256']:
            raise ValueError('Verified source hash mismatch or static scan blocker')
        steps = evidence_lane.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('Empty execution evidence is not accepted')
        if any(not isinstance(s, dict) or s.get('passed') is not True or
               s.get('executed') is not True or s.get('exit_code') != 0 for s in steps):
            raise ValueError('Execution evidence contains a failed or simulated step')
        test_steps = [s for s in steps if s.get('step') in ('python_tests', 'javascript_tests')]
        expected_count = int(expected['python']) + int(expected['javascript'])
        if len(test_steps) != expected_count or any(type(s.get('test_count')) is not int or s['test_count'] < 1 for s in test_steps):
            raise ValueError('Missing non-zero test count for a language')
        summary[lane] = {'source_sha256': expected['sha256'],
                         'executed_tests': sum(s['test_count'] for s in test_steps),
                         'steps': [{'name': s['step'], 'passed': True, 'test_count': s.get('test_count'),
                                    'image': s.get('image')} for s in steps]}
    # Publishing requires an explicit Tech Lead decision, not the old implicit A.
    if not isinstance(decision, dict):
        raise PermissionError('Tech Lead decision required before code PR export')
    comparison = compare_candidates(job, evidence)
    lane = decision.get('selected')
    if lane not in ('A', 'B') or decision.get('status') != 'selected_for_human_review':
        raise ValueError('Invalid candidate selection')
    if decision.get('job_id') != job['id'] or decision.get('project_id') != job['project_id']:
        raise ValueError('Decision belongs to another job')
    if decision.get('selected_digest') != comparison['candidates'][lane]['digest']:
        raise ValueError('Decision digest does not match verified source')
    if decision.get('candidates') != comparison['candidates']:
        raise ValueError('Decision candidate comparison is stale or modified')
    if (not isinstance(decision.get('techlead'), str) or len(decision['techlead'].strip()) < 3
            or not isinstance(decision.get('rationale'), str) or len(decision['rationale'].strip()) < 20
            or not isinstance(decision.get('decided_at'), str)):
        raise ValueError('Incomplete Tech Lead decision')
    prefix = 'agent-proposals/' + job['id']
    files = [{'path': prefix + '/candidate-' + lane + '/' + safe_path(f['path']),
              'content': f['content']} for f in proposals[lane]['files']]
    redacted = {
        'version': '0.5.0', 'job_id': job['id'], 'project_id': job['project_id'],
        'verification': {'gate': 'PASS', 'verdict': 'passed', 'created_at': evidence.get('created_at'),
                         'completed_at': evidence.get('completed_at'), 'lanes': summary},
        'reviews': [job['review_a'], job['review_b']],
        'selection': {'selected': lane, 'techlead': decision['techlead'],
                      'rationale': decision['rationale'], 'decided_at': decision['decided_at'],
                      'selected_digest': decision['selected_digest']},
        'note': 'AI candidate ' + lane + ', reviewed and sandbox-tested. NOT merged, deployed, or production certified.'
    }
    files.append({'path': prefix + '/VERIFICATION.json',
                  'content': json.dumps(redacted, ensure_ascii=False, indent=2) + '\n'})
    return {'job_id': job['id'], 'selected': lane, 'prefix': prefix, 'files': files,
            'review_summary': summary, 'notice': 'Draft PR only. Human review and CI required before merge.'}


class VerifiedCodePRClient(GitHubClient):
    def draft_pr(self, repo, bundle):
        if not VALID_REPO.fullmatch(repo) or '..' in repo:
            raise ValueError('Invalid GitHub repository')
        jid = bundle['job_id']
        if not JOB_ID.fullmatch(jid):
            raise ValueError('Invalid job id')
        selected = bundle.get('selected')
        if selected not in ('A', 'B'):
            raise ValueError('Explicit selected candidate is required')
        # Preflight all paths before creating a branch or making any GitHub writes.
        for f in bundle['files']:
            path = f['path']
            if not path.startswith('agent-proposals/' + jid + '/'):
                raise ValueError('Refusing to write outside agent-proposals job prefix')
            relative = path[len('agent-proposals/' + jid + '/'):]
            if relative != 'VERIFICATION.json':
                if not relative.startswith('candidate-' + selected + '/'):
                    raise ValueError('Invalid selected candidate path')
                safe_path(relative[len('candidate-' + selected + '/'):])
        branch = 'orbit/verified-' + jid + '-' + uuid.uuid4().hex[:8]
        api = '/repos/' + repo
        meta = self.request('GET', api)
        base = meta['default_branch']
        details = self.request('GET', api + '/branches/' + quote(base, safe=''))
        self.request('POST', api + '/git/refs', {'ref': 'refs/heads/' + branch,
                                                'sha': details['commit']['sha']})
        for f in bundle['files']:
            path = f['path']
            if not path.startswith('agent-proposals/' + jid + '/'):
                raise ValueError('Refusing to write outside agent-proposals job prefix')
            # All payload paths are revalidated, so callers cannot write to CI
            # workflow, backend, or any other application source location.
            relative = path[len('agent-proposals/' + jid + '/'):]
            if relative != 'VERIFICATION.json':
                if not relative.startswith('candidate-' + selected + '/'):
                    raise ValueError('Invalid candidate path')
                safe_path(relative[len('candidate-' + selected + '/'):])
            encoded = quote(path, safe='/')
            self.request('PUT', api + '/contents/' + encoded, {
                'message': 'feat(orbit): reviewed candidate ' + jid,
                'content': base64.b64encode(f['content'].encode('utf-8')).decode('ascii'),
                'branch': branch,
            })
        result = self.request('POST', api + '/pulls', {
            'title': 'ORBIT verified candidate: ' + jid,
            'head': branch, 'base': base, 'draft': True,
            'body': ('Sandbox verification gate PASSED for DEV-A and DEV-B, '
                     'and both cross-reviews were approved. Selected DEV-' + selected + ' is under '
                     '`agent-proposals/`, not integrated into production source. '
                     'Human review and CI are mandatory; DO NOT auto-merge or deploy.'),
        })
        return {'url': result['html_url'], 'number': result['number'],
                'branch': branch, 'base': base}
