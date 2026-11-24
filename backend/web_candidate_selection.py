"""Human Tech Lead selection between independently generated DEV-A and DEV-B.

This module never executes or publishes generated code. Verification evidence is
mandatory and checked against candidate file hashes; no silent fallback to A.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re
from coding_factory import validate_proposal
from verification_factory import safe_job, plan_lane

def _digest(files):
    data = [{'path': f['path'], 'sha256': f['sha256']} for f in files]
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def react_evidence(proposal, lane):
    from react_candidate_gate import plan_react
    from web_typescript_sandbox import immutable_web_image
    plan = plan_react(proposal)
    if plan['blockers'] or lane.get('sha256') != plan['sha256']:
        raise ValueError('React profile or source mismatch')
    steps = lane.get('steps')
    if not isinstance(steps, list) or len(steps) != 1:
        raise ValueError('Exactly one React render check required')
    step = steps[0]
    if (step.get('step') != 'react_welcome_render' or step.get('executed') is not True
        or step.get('passed') is not True or step.get('exit_code') != 0
        or type(step.get('test_count')) is not int or step['test_count'] != 1):
        raise ValueError('React render evidence incomplete')
    immutable_web_image(step.get('image'))
    return steps

def compare(job, report):
    """Fail closed unless BOTH independently reviewed candidates passed sandbox."""
    proposals = safe_job(job)
    if not isinstance(report, dict) or report.get('job_id') != job.get('id'):
        raise ValueError('Verification report does not match job')
    if report.get('gate') != 'PASS' or report.get('verdict') != 'passed':
        raise ValueError('Both candidates must pass sandbox verification')
    if report.get('sandbox', {}).get('runtime') != 'docker' or report.get('approval') != 'local_cli_explicit':
        raise ValueError('Untrusted verification provenance')
    profile = report.get('profile')
    if profile not in (None, 'react-welcome-v1'):
        raise ValueError('Unknown verification profile')
    if profile and (report.get('project_id') != job.get('project_id') or report['sandbox'].get('network') != 'none'):
        raise ValueError('React evidence project or network mismatch')
    lanes = report.get('lanes')
    if not isinstance(lanes, dict) or set(lanes) != {'A', 'B'}:
        raise ValueError('Both candidate results required')
    results = {}
    for lane in ('A', 'B'):
        expected = _digest(proposals[lane]['files'])
        actual = lanes[lane]
        if not isinstance(actual, dict) or actual.get('status') != 'passed' or actual.get('sha256') != expected:
            raise ValueError('Missing, failed or mismatched evidence for DEV-' + lane)
        steps = actual.get('steps')
        if not isinstance(steps, list) or not steps:
            raise ValueError('Empty sandbox test evidence for DEV-' + lane)
        if any(not isinstance(s, dict) or s.get('executed') is not True or s.get('passed') is not True for s in steps):
            raise ValueError('Sandbox steps are incomplete')
        test_steps = react_evidence(proposals[lane], actual) if profile else [s for s in steps if s.get('step') in ('python_tests', 'javascript_tests')]
        if not test_steps or any(type(s.get('test_count')) is not int or s['test_count'] < 1 for s in test_steps):
            raise ValueError('Positive test count required for DEV-' + lane)
        results[lane] = {
            'summary': proposals[lane]['summary'],
            'files': [{'path': f['path'], 'sha256': f['sha256']} for f in proposals[lane]['files']],
            'test_count': sum(s['test_count'] for s in test_steps),
            'sandbox_steps': len(steps),
            'digest': expected,
            **({'profile': profile, 'image': test_steps[0]['image']} if profile else {}),
        }
    return {'job_id': job['id'], 'project_id': job.get('project_id'),
            'status': 'awaiting_techlead_decision', 'candidates': results,
            'notice': 'Sandbox tests are evidence, not proof of correctness. Human code review required.'}

def decide(job, report, *, selected, techlead, rationale, confirmation):
    """Human confirmation does not create a PR, deploy or merge."""
    comparison = compare(job, report)
    if selected not in ('A', 'B'):
        raise ValueError('Select A or B explicitly')
    if not isinstance(techlead, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9 ._@-]{2,99}', techlead):
        raise ValueError('Named Tech Lead required')
    if not isinstance(rationale, str) or not 20 <= len(rationale.strip()) <= 3000:
        raise ValueError('Tech Lead rationale must be 20-3000 characters')
    expected = 'SELECT DEV-' + selected + ' ' + job['id']
    if confirmation != expected:
        raise PermissionError('Explicit Tech Lead confirmation required: ' + expected)
    return {**comparison, 'status': 'selected_for_human_review', 'selected': selected,
            'techlead': techlead, 'rationale': rationale.strip(),
            'decided_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'selected_digest': comparison['candidates'][selected]['digest'],
            'publish_allowed': False, 'production_approved': False}
