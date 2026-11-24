"""ORBIT v0.5: fail-closed, opt-in, Docker-only verification of AI proposals.

This module NEVER executes generated code on the host. Proposed files are data;
Docker runs get a read-only bind mount, no network and strict resource limits.
A passing result is test evidence, not a guarantee of correctness or security.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import tempfile
import uuid

from coding_factory import validate_proposal

IMAGE_REF = re.compile(r'^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?@sha256:[0-9a-f]{64}$')
PY_TEST = re.compile(r'^test_[A-Za-z0-9_]+\.py$')
JS_TEST = re.compile(r'^[A-Za-z0-9_.-]+\.test\.js$')
PY_RAN = re.compile(r'(?m)^Ran (\d+) tests? in ')
JS_RAN = re.compile(r'(?m)^# tests (\d+)\s*$')
SUPPORTED_CODE = {'.py', '.js'}
SUPPORTED_PASSIVE = {'.md', '.txt', '.json', '.css', '.yaml', '.yml'}
MAX_OUTPUT = 6_000
MAX_EXECUTION_SECONDS = 60


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def pinned_image(value):
    """Require explicit content-addressed images rather than mutable latest tags."""
    if not isinstance(value, str) or not IMAGE_REF.fullmatch(value) or '..' in value:
        raise ValueError('Docker image must be pinned as name@sha256:<64 hex digits>')
    return value


def safe_job(job):
    """Validate reviews, provenance, and persisted hashes before any execution."""
    if not isinstance(job, dict) or job.get('status') != 'ready':
        raise ValueError('Job must pass independent cross-review first')
    manifest = job.get('manifest')
    if not isinstance(manifest, dict) or manifest.get('mode') != 'model':
        raise ValueError('Demo code cannot be marked as independently verified')
    if manifest.get('selected') != 'A' or not isinstance(manifest.get('files'), list):
        raise ValueError('Unexpected candidate selection or missing manifest')
    ra, rb = job.get('review_a'), job.get('review_b')
    for review, reviewer, author in ((ra, 'A', 'B'), (rb, 'B', 'A')):
        if (not isinstance(review, dict) or review.get('reviewer') != reviewer or
                review.get('author') != author or review.get('verdict') != 'APPROVE' or
                type(review.get('score')) is not int or review['score'] < 80):
            raise ValueError('Cross-review evidence is incomplete or below threshold')
    proposals = {}
    for lane in ('A', 'B'):
        proposal = job.get('proposal_' + lane.lower())
        if proposal is None:
            raise ValueError('Both independent agent proposals are required')
        proposals[lane] = validate_proposal(proposal)
    expected = [{'path': f['path'], 'sha256': f['sha256']} for f in proposals['A']['files']]
    if expected != manifest['files']:
        raise ValueError('Proposal A no longer matches the reviewed SHA-256 manifest')
    if 'candidate_files' in manifest:
        for lane,proposal in proposals.items():
            if manifest['candidate_files'].get(lane)!=[{'path':f['path'],'sha256':f['sha256']} for f in proposal['files']]:
                raise ValueError('Proposal '+lane+' no longer matches reviewed manifest')
    return proposals


def static_scan(proposal):
    """Conservative heuristic only, not a dependency or comprehensive security audit."""
    findings = []
    for f in proposal['files']:
        path, source = f['path'], f['content']
        ext = PurePosixPath(path).suffix.lower()
        if ext not in SUPPORTED_CODE | SUPPORTED_PASSIVE:
            findings.append({'path': path, 'code': 'UNSUPPORTED_FORMAT', 'severity': 'block'})
            continue
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}', source):
            findings.append({'path': path, 'code': 'POSSIBLE_SECRET', 'severity': 'block'})
        if ext == '.py':
            try:
                syntax = ast.parse(source, filename=path)
            except SyntaxError:
                findings.append({'path': path, 'code': 'PYTHON_SYNTAX', 'severity': 'block'})
                continue
            for node in ast.walk(syntax):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or '']
                    if any(name.split('.')[0] in {'subprocess', 'ctypes'} for name in names):
                        findings.append({'path': path, 'code': 'DANGEROUS_IMPORT', 'severity': 'block'})
                        break
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', 'compile', '__import__'}:
                        findings.append({'path': path, 'code': 'DYNAMIC_EXECUTION', 'severity': 'block'})
                        break
                    if isinstance(node.func, ast.Attribute) and node.func.attr in {'system', 'popen'}:
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == 'os':
                            findings.append({'path': path, 'code': 'HOST_COMMAND', 'severity': 'block'})
                            break
        elif ext == '.js':
            if re.search(r'\bchild_process\b|\beval\s*\(|\bnew\s+Function\s*\(|\bprocess\.env\b', source):
                findings.append({'path': path, 'code': 'DYNAMIC_OR_PRIVILEGED_JS', 'severity': 'block'})
    return findings


def plan_lane(proposal):
    files = proposal['files']
    py = [f['path'] for f in files if f['path'].endswith('.py')]
    js = [f['path'] for f in files if f['path'].endswith('.js')]
    py_tests = [p for p in py if PY_TEST.fullmatch(PurePosixPath(p).name)]
    js_tests = [p for p in js if JS_TEST.fullmatch(PurePosixPath(p).name)]
    failures = []
    if not (py or js):
        failures.append('NO_EXECUTABLE_FILES')
    if py and not py_tests:
        failures.append('MISSING_PYTHON_TESTS')
    if js and not js_tests:
        failures.append('MISSING_JAVASCRIPT_TESTS')
    findings = static_scan(proposal)
    if any(f['severity'] == 'block' for f in findings):
        failures.append('STATIC_SCAN_BLOCK')
    return {'python': bool(py), 'javascript': bool(js), 'py_tests': py_tests,
            'js_tests': js_tests, 'javascript_files': js, 'findings': findings,
            'blocking_reasons': failures,
            'sha256': hashlib.sha256(json.dumps(
                [{'path': f['path'], 'sha256': f['sha256']} for f in files],
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def preview_job(job):
    proposals = safe_job(job)
    lanes = {lane: plan_lane(proposal) for lane, proposal in proposals.items()}
    return {'job_id': job['id'], 'status': 'blocked' if any(x['blocking_reasons'] for x in lanes.values()) else 'awaiting_human_approval',
            'lanes': lanes, 'notice': 'Dry run. Generated code has NOT been executed; Docker sandbox is mandatory.'}


def _materialize_proposal(proposal, directory):
    """Only write validated text paths to an empty temporary folder, never host repo."""
    root = Path(directory).resolve(strict=True)
    for item in proposal['files']:
        target = root.joinpath(*PurePosixPath(item['path']).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(root):
            raise ValueError('Workspace path escaped root')
        with target.open('x', encoding='utf-8') as handle:
            handle.write(item['content'])
    os.chmod(root, 0o755)
    for directory_path in root.rglob('*'):
        if directory_path.is_dir():
            directory_path.chmod(0o755)
        elif directory_path.is_file():
            directory_path.chmod(0o644)
    return root


def _docker_cmd(image, workspace, command, name):
    # Fixed arguments, no shell, no host token/env or writable source mounts.
    return [
        'docker', 'run', '--rm', '--pull', 'never', '--name', name,
        '--network', 'none', '--read-only', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges', '--pids-limit', '64',
        '--memory', '256m', '--cpus', '1', '--user', '65534:65534',
        '--tmpfs', '/tmp:rw,noexec,nosuid,size=32m',
        '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONNOUSERSITE=1',
        '--env', 'PYTHONPATH=/work', '--env', 'TMPDIR=/tmp',
        '--mount', 'type=bind,src=' + str(workspace) + ',dst=/work,readonly',
        '--workdir', '/work', image, *command,
    ]


def _execute_docker(image, workspace, command, runner, timeout, trace_label):
    name = 'orbit-v05-' + uuid.uuid4().hex[:16]
    argv = _docker_cmd(image, workspace, command, name)
    result = {'step': trace_label, 'image': image, 'executed': False, 'passed': False,
              'exit_code': None, 'test_count': None, 'output': ''}
    try:
        completed = runner(argv, capture_output=True, text=True, timeout=timeout)
        output = (completed.stdout or '') + '\n' + (completed.stderr or '')
        result.update(executed=True, exit_code=completed.returncode, passed=completed.returncode == 0,
                      output=output[-MAX_OUTPUT:])
        if trace_label in ('python_tests', 'javascript_tests', 'typescript_tests'):
            matches = (PY_RAN if trace_label == 'python_tests' else JS_RAN).findall(output)
            count = int(matches[-1]) if matches else 0
            result.update(test_count=count, passed=completed.returncode == 0 and count > 0)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        result['output'] = type(exc).__name__ + ': Docker unavailable or execution timeout'
        # A killed Docker CLI does not guarantee container termination.
        # Clean up the unique named container; never reuse job-provided names.
        if isinstance(exc, subprocess.TimeoutExpired):
            try:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True,
                               timeout=5, check=False)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass
    return result


def _verify_lane(lane, proposal, policy, runner, timeout):
    result = {'lane': lane, 'sha256': policy['sha256'], 'findings': policy['findings'],
              'steps': [], 'status': 'not_verified'}
    if policy['blocking_reasons']:
        result.update(status='blocked', reasons=policy['blocking_reasons'])
        return result
    with tempfile.TemporaryDirectory(prefix='orbit-v05-', dir=None) as work:
        workspace = _materialize_proposal(proposal, work)
        commands = []
        if policy['python']:
            commands.append(('python_tests', 'python', ['python', '-B', '-m', 'unittest', 'discover',
                                               '-s', '/work', '-p', 'test_*.py', '-v']))
        if policy['javascript']:
            for filename in policy['javascript_files']:
                commands.append(('javascript_syntax:' + filename, 'node', ['node', '--check', '/work/' + filename]))
            commands.append(('javascript_tests', 'node', ['node', '--test'] +
                             ['/work/' + filename for filename in policy['js_tests']]))
        for step, kind, argv in commands:
            img = pinned_image(policy['images'][kind])
            item = _execute_docker(img, workspace, argv, runner, timeout, step)
            result['steps'].append(item)
            if not item['passed']:
                result['status'] = 'failed' if item['executed'] else 'not_verified'
                return result
        result['status'] = 'passed'
    return result


def verify_job(job, *, python_image=None, node_image=None, runner=subprocess.run,
               timeout=25, approval=None):
    """Only execute when human submits exact approval token RUN SANDBOX <job id>."""
    started = utc_now()
    if not isinstance(timeout, int) or type(timeout) is not int or not 1 <= timeout <= MAX_EXECUTION_SECONDS:
        raise ValueError('Sandbox timeout must be an integer from 1 to 60 seconds')
    if not isinstance(job.get('id'), str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', job['id']):
        raise ValueError('Unsafe job id')
    if approval != 'RUN SANDBOX ' + job['id']:
        raise PermissionError('Explicit human approval required: RUN SANDBOX <job id>')
    proposal = safe_job(job)
    lane_plans = {lane: plan_lane(p) for lane, p in proposal.items()}
    report = {'version': '0.5.0', 'job_id': job['id'], 'project_id': job.get('project_id'),
              'created_at': started, 'completed_at': None, 'approval': 'local_cli_explicit',
              'sandbox': {'runtime': 'docker', 'network': 'none', 'workspace': 'read-only',
                          'rootfs': 'read-only', 'user': '65534:65534',
                          'capabilities': 'dropped', 'image_pull': 'never'},
              'gate': 'BLOCK', 'verdict': 'blocked', 'lanes': {},
              'notice': 'Sandbox execution evidence only; not proof of functional correctness, safety or production readiness.'}
    if any(v['blocking_reasons'] for v in lane_plans.values()):
        report['lanes'] = {lane: {'status': 'blocked', 'reasons': v['blocking_reasons'],
                                  'findings': v['findings']} for lane, v in lane_plans.items()}
        report['completed_at'] = utc_now()
        return report
    needed = {language for plan in lane_plans.values() for language in ('python', 'javascript') if plan[language]}
    images = {}
    for language in needed:
        images[language] = pinned_image(python_image if language == 'python' else node_image)
    for lane, proposal_data in proposal.items():
        lane_plans[lane]['images'] = {'python': images.get('python'), 'node': images.get('javascript')}
        report['lanes'][lane] = _verify_lane(lane, proposal_data, lane_plans[lane], runner, timeout)
    statuses = {lane['status'] for lane in report['lanes'].values()}
    report['gate'] = 'PASS' if statuses == {'passed'} else 'BLOCK'
    report['verdict'] = ('passed' if report['gate'] == 'PASS' else
                         'failed' if 'failed' in statuses else 'not_verified')
    report['completed_at'] = utc_now()
    return report


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS coding_verifications (
        id TEXT PRIMARY KEY, job_id TEXT NOT NULL, project_id TEXT NOT NULL,
        verdict TEXT NOT NULL, report_json TEXT NOT NULL, created_at TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_coding_verifications_job ON coding_verifications(job_id,created_at)')


def store_report(conn, report):
    ensure_schema(conn)
    if report.get('gate') not in {'BLOCK', 'PASS'} or report.get('verdict') not in {'passed', 'failed', 'not_verified', 'blocked'}:
        raise ValueError('Invalid verification result')
    ref = uuid.uuid4().hex
    conn.execute('INSERT INTO coding_verifications(id,job_id,project_id,verdict,report_json,created_at) '
                 'VALUES(?,?,?,?,?,?)', (ref, report['job_id'], report['project_id'], report['verdict'],
                                        json.dumps(report, ensure_ascii=False), report['created_at']))
    return ref


def list_reports(conn, job_id, limit=5):
    ensure_schema(conn)
    return [dict(id=row['id'], job_id=row['job_id'], verdict=row['verdict'],
                 report=json.loads(row['report_json']), created_at=row['created_at'])
            for row in conn.execute('SELECT id,job_id,verdict,report_json,created_at '
                                    'FROM coding_verifications WHERE job_id=? '
                                    'ORDER BY rowid DESC LIMIT ?', (job_id, min(max(limit,1),10))).fetchall()]
