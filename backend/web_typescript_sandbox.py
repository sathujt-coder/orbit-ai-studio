"""Opt-in, offline TypeScript/TSX sandbox adapter for two independently reviewed candidates.

No dependency installation, network, host execution, publish or merge. Requires a
preloaded digest-pinned image with tsc and tsx on PATH. This is an independent
adapter; integration with the legacy Python/JS verifier is a future change.
"""
from __future__ import annotations
from pathlib import PurePosixPath
import re
import subprocess
import tempfile
from coding_factory import safe_path
from verification_factory import safe_job, pinned_image, _materialize_proposal, _execute_docker, plan_lane, utc_now

TEST = re.compile(r'^[A-Za-z0-9_.-]+\.test\.tsx?$')
CODE = {'.ts', '.tsx', '.js', '.jsx', '.json', '.css', '.html', '.md', '.txt'}
DANGEROUS = re.compile(r'\bchild_process\b|\bprocess\.env\b|\beval\s*\(|\bnew\s+Function\s*\(')

def plan_web(proposal):
    paths = [safe_path(f['path']) for f in proposal['files']]
    ts = [p for p in paths if PurePosixPath(p).suffix in ('.ts', '.tsx')]
    tests = [p for p in ts if TEST.fullmatch(PurePosixPath(p).name)]
    errors = []
    if not ts: errors.append('NO_TYPESCRIPT')
    if not tests: errors.append('MISSING_TYPESCRIPT_TESTS')
    if 'tsconfig.json' not in paths: errors.append('MISSING_TSCONFIG')
    if 'package.json' in paths or any(p.endswith(('package-lock.json','yarn.lock','pnpm-lock.yaml')) for p in paths):
        errors.append('DEPENDENCY_INSTALL_NOT_SUPPORTED')
    if any(PurePosixPath(p).suffix.lower() not in CODE for p in paths):
        errors.append('UNSUPPORTED_FILE')
    if any(DANGEROUS.search(f['content']) for f in proposal['files']):
        errors.append('PRIVILEGED_CODE_PATTERN')
    # No dependency resolution: React/JSX imports require a preloaded toolchain
    # and are intentionally rejected until offline dependency pinning is audited.
    if any(re.search(r'from\s+[\'\"]react(?:/[^\'\"]*)?[\'\"]|require\([\'\"]react', f['content'])
           for f in proposal['files']):
        errors.append('REACT_DEPENDENCIES_NOT_AUDITED')
    return {'files':paths, 'ts_files':ts, 'tests':tests, 'blockers':errors,
            'sha256':plan_lane({'files':proposal['files']})['sha256']}

def verify_web(job, *, image, approval, runner=subprocess.run, timeout=25):
    if approval != 'RUN WEB SANDBOX ' + str(job.get('id','')):
        raise PermissionError('Explicit RUN WEB SANDBOX <job-id> confirmation required')
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError('Invalid timeout')
    proposals = safe_job(job)
    plans = {lane:plan_web(p) for lane,p in proposals.items()}
    result = {'job_id':job['id'], 'project_id':job.get('project_id'), 'gate':'BLOCK',
              'verdict':'blocked','approval':'local_cli_explicit',
              'sandbox':{'runtime':'docker','network':'none','image_pull':'never'},
              'lanes':{},'created_at':utc_now()}
    if any(p['blockers'] for p in plans.values()):
        result['lanes']={lane:{'status':'blocked','reasons':p['blockers']} for lane,p in plans.items()}
        return result
    image=pinned_image(image)
    for lane,proposal in proposals.items():
        plan=plans[lane]
        with tempfile.TemporaryDirectory(prefix='orbit-web-') as tmp:
            root=_materialize_proposal(proposal,tmp)
            commands=[
                ('typescript_check',['tsc','--noEmit','--project','/work/tsconfig.json']),
                ('typescript_tests',['tsx','--test']+['/work/'+p for p in plan['tests']]),
            ]
            steps=[]
            for label,argv in commands:
                step=_execute_docker(image,root,argv,runner,timeout,label)
                steps.append(step)
                if not step['passed']: break
            passed=len(steps)==2 and all(s['passed'] for s in steps) and steps[-1].get('test_count',0)>0
            result['lanes'][lane]={'status':'passed' if passed else 'failed',
                'sha256':plan['sha256'],'steps':steps}
    result['gate']='PASS' if all(l['status']=='passed' for l in result['lanes'].values()) else 'BLOCK'
    result['verdict']='passed' if result['gate']=='PASS' else 'failed'
    return result
