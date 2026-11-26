"""Narrow React welcome-component acceptance profile for trusted local operators.

The existing image contains a fixed independent assertion. No arbitrary user
acceptance criteria, dependency installation, or publishing is supported.
"""
from __future__ import annotations
import re
import subprocess
import tempfile
from verification_factory import safe_job, _materialize_proposal, _execute_docker, plan_lane, utc_now
from web_typescript_sandbox import immutable_web_image, DANGEROUS

PROFILE = 'react-welcome-v1'

def plan_react(proposal):
    files = proposal['files']
    paths = [f['path'] for f in files]
    blockers = []
    if paths != ['Component.tsx']:
        blockers.append('EXACT_SINGLE_COMPONENT_REQUIRED')
    for f in files:
        if DANGEROUS.search(f['content']):
            blockers.append('PRIVILEGED_CODE_PATTERN')
        if re.search(r'-----BEGIN .*PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}', f['content']):
            blockers.append('POSSIBLE_SECRET')
    return {'blockers':blockers,'sha256':plan_lane(proposal)['sha256']}

def verify_react(job, *, image, approval, runner=subprocess.run, timeout=40, materialize=None):
    if approval != 'RUN REACT SANDBOX ' + str(job.get('id','')):
        raise PermissionError('Explicit React sandbox approval required')
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError('Invalid timeout')
    proposals = safe_job(job)
    plans = {k:plan_react(v) for k,v in proposals.items()}
    report = {'profile':PROFILE,'job_id':job['id'],'project_id':job['project_id'],
              'gate':'BLOCK','verdict':'blocked','created_at':utc_now(),
              'approval':'local_cli_explicit','sandbox':{'runtime':'docker','network':'none'},
              'lanes':{}}
    if any(p['blockers'] for p in plans.values()):
        report['lanes'] = {k:{'status':'blocked','reasons':p['blockers']} for k,p in plans.items()}
        return report
    image = immutable_web_image(image)
    for lane, proposal in proposals.items():
        with tempfile.TemporaryDirectory(prefix='orbit-react-') as tmp:
            root = (_materialize_proposal(proposal,tmp) if materialize is None
                    else materialize(lane,proposal,tmp))
            step = _execute_docker(image,root,[],runner,timeout,'react_welcome_render')
            passed = step['passed'] and 'React component bundle and render: PASS' in step['output'].splitlines()
            step['passed'] = bool(passed)
            step['test_count'] = int(passed)
            report['lanes'][lane] = {'status':'passed' if passed else 'failed',
                'sha256':plans[lane]['sha256'],'steps':[step]}
    report['gate'] = 'PASS' if all(v['status']=='passed' for v in report['lanes'].values()) else 'BLOCK'
    report['verdict'] = 'passed' if report['gate']=='PASS' else 'failed'
    report['completed_at'] = utc_now()
    return report
