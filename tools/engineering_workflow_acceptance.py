"""Verify exact run-bound retry continuity and final development evidence."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import project_planning as pp

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[k]==os.environ[v]
    assert d['schema']=='orbit.engineering-workflow-browser.v1' and d['transport']=='synthetic_inference_real_git_docker_http'
    assert all(d[k] is False for k in ('execution_authorized','merge_authorized','production_release_authorized'))
    rec=d['recovery']
    assert rec['recovered_root_prerequisite'] is True and rec['upstream_stale'] is True
    for kind,status in (('root','cancelled'),('dependent','interrupted')):
        assert rec[kind]==dict(kind=kind,previous_status=status,retry_http=202,rollback=True,model_calls=4,qa_http=201,completion_http=201,immutable_history=True)
    x=d['continuity'];old=x['previous_job_id'];new=x['current_job_id'];r=x['retry_receipt']
    assert old!=new and r['job_id']==new and r['source']['previous_job_id']==old and pp.digest(r)==x['retry_digest']
    assert all(x[k] is True for k in ('completion_block_before_retest','prior_job_write_rejected','duplicate_rejected'))
    assert len(x['previous_events'])==1 and pp.digest(x['previous_events'])==r['source']['defect_history_digest']
    q=x['quality'];src=q['source'];h=q['defects'][0]['history'];s=x['sandbox']
    assert q['lineage']==[old,new] and q['job_id']==new and q['state']=='QUALITY_EVIDENCE_PASS'
    assert q['counts']==dict(OPEN=0,READY_FOR_RETEST=0,CLOSED=1) and len(q['defects'])==1
    assert q['source_digest']==pp.digest(src) and src['qa']['state']=='HUMAN_QA_PASS'
    assert [i['event']['job_id'] for i in h]==[old,new,new]
    assert [i['event']['state'] for i in h]==['OPEN','READY_FOR_RETEST','CLOSED']
    assert json.loads(x['previous_events'][0]['snapshot'])==h[0]['event']
    assert x['previous_events'][0]['digest']==h[0]['digest']
    for i,item in enumerate(h):
        e=item['event']
        assert item['digest']==pp.digest(e) and e['version']==i+1
        assert e['previous_digest']==(h[i-1]['digest'] if i else None) and e['source_digest']==pp.digest(e['source'])
        assert e['source']['binding']==src['binding'] and e['project_id']==q['project_id']==r['source']['project_id']
        assert all(e[k] is False for k in ('execution_authorized','merge_authorized','production_release_authorized','remote_writes_authorized'))
    assert h[2]['event']['source']==src and s['gate']=='PASS' and s['version']==1
    assert src['sandbox']['receipt_digest']==s['digest'] and src['sandbox']['state']=='PASS'
    assert set(s['git'])=={'A','B'} and s['git']['A']['commit']!=s['git']['B']['commit']
    assert all(s[k] is False for k in ('execution_authorized','merge_authorized','production_release_authorized','remote_writes_authorized'))
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.3j workflow continuity evidence PASS; sha256='+digest)
if __name__=='__main__':main()
