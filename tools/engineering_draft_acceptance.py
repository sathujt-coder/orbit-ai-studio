"""Bind mandatory draft integration evidence to its exact CI run and sandbox receipt."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import project_planning as pp

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    sb=json.loads(Path(sys.argv[2]).read_bytes())
    for key,env in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[key]==sb[key]==os.environ[env]
    assert d['schema']=='orbit.engineering-draft-browser.v1'
    assert d['transport']=='synthetic_github_api_real_git_sqlite' and d['remote_writes_real'] is False
    assert d['duplicate_blocked'] is True
    plan=d['plan'];src=plan['source'];r=d['receipt']
    assert d['plan_digest']==pp.digest(plan)==r['plan_digest']
    assert src['project_id']==sb['project_id'] and src['job_id']==sb['job_id']
    assert src['selected']=='B' and src['sandbox_digest']==sb['receipt']['digest']
    assert src['selection_digest']==sb['selection_digest'] and src['git']==sb['receipt']['git']['B']
    assert r['status']=='CREATED_DRAFT' and r['remote']['draft'] is True
    assert all(x[k] is False for x in (d,plan,src,r) for k in ('execution_authorized','merge_authorized','production_release_authorized','remote_writes_authorized'))
    prefix='agent-proposals/'+src['job_id']+'/'
    assert all(f['path'].startswith(prefix+'candidate-B/') or f['path']==prefix+'VERIFICATION.json' for f in plan['files'])
    assert len(plan['files'])>=2 and len({f['path'] for f in plan['files']})==len(plan['files'])
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.3h draft integration evidence PASS; sha256='+digest)
if __name__=='__main__':main()
