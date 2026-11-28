"""Verify real HTTP defect lifecycle and bind current sandbox/draft receipts."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import project_planning as pp

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    sandbox=json.loads(Path(sys.argv[2]).read_bytes())
    draft=json.loads(Path(sys.argv[3]).read_bytes())
    for key,env in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[key]==sandbox[key]==draft[key]==os.environ[env]
    assert d['schema']=='orbit.engineering-quality-browser.v1'
    assert d['transport']=='synthetic_inference_real_git_docker_http' and d['prior_close_blocked'] is True
    q=d['quality'];src=q['source'];initial=d['initial_sandbox'];final=sandbox['receipt']
    assert q['project_id']==d['project_id']==sandbox['project_id'] and q['job_id']==d['job_id']==sandbox['job_id']
    assert q['state']=='QUALITY_EVIDENCE_PASS' and q['source_digest']==pp.digest(src)
    assert q['counts']==dict(OPEN=0,READY_FOR_RETEST=0,CLOSED=1)
    assert len(q['defects'])==1
    h=q['defects'][0]['history']
    assert [x['event']['state'] for x in h]==['OPEN','READY_FOR_RETEST','CLOSED']
    for i,x in enumerate(h):
        e=x['event']
        assert pp.digest(e)==x['digest'] and e['version']==i+1
        assert e['previous_digest']==(h[i-1]['digest'] if i else None)
        assert e['source_digest']==pp.digest(e['source'])
        assert e['project_id']==q['project_id'] and e['job_id']==q['job_id']
        assert all(e[k] is False for k in ('execution_authorized','merge_authorized','production_release_authorized','remote_writes_authorized'))
    assert initial['version']==1 and final['version']==2 and initial['gate']=='PASS'
    assert initial['git']==final['git'] and initial['selection_digest']==final['selection_digest']
    assert set(initial['lanes'])=={'A','B'} and all(x['status']=='passed' and x['test_count']>0 for x in initial['lanes'].values())
    assert h[0]['event']['source']['sandbox']['receipt_digest']==h[1]['event']['source']['sandbox']['receipt_digest']==initial['digest']
    assert h[2]['event']['source']==src and src['qa']['state']=='HUMAN_QA_PASS'
    assert src['sandbox']['state']=='PASS' and src['sandbox']['version']==2
    assert src['sandbox']['receipt_digest']==d['retest_sandbox_digest']==final['digest']==draft['plan']['source']['sandbox_digest']
    assert initial['digest']!=final['digest']
    assert all(q[k] is False for k in ('execution_authorized','merge_authorized','production_release_authorized','remote_writes_authorized'))
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.3i engineering quality evidence PASS; sha256='+digest)
if __name__=='__main__':main()
