"""Verify QC evidence against previous sandbox, quality and draft artifacts."""
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_qc as qc

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    sandbox,quality,draft=[json.loads(Path(p).read_bytes()) for p in sys.argv[2:]]
    for key,env in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[key]==sandbox[key]==quality[key]==draft[key]==os.environ[env]
    assert d['schema']=='orbit.engineering-qc-browser.v1' and d['read_only'] is True
    assert d['transport']=='synthetic_inference_real_git_docker_http'
    p=d['passed'];o=d['open'];s=d['stale']
    for v in (p,o,s):
        assert v['evidence_digest']==qc.pp.digest({k:x for k,x in v.items() if k!='evidence_digest'})
        assert v['project_id']==sandbox['project_id'] and v['job_id']==sandbox['job_id']
        assert all(v[k] is False for k in qc.FLAGS) and v['remote_live_verified'] is False
    assert p['state']=='QA_QC_EVIDENCE_PASS' and p['selected']=='B' and p['findings']==[]
    assert set(p['checks'])==set(qc.CHECKS) and all(x=='PASS' for x in p['checks'].values())
    assert p['receipts']['sandbox']==sandbox['receipt']['digest']
    assert p['receipts']['candidate_selection']==sandbox['selection_digest']
    assert p['receipts']['quality_source']==quality['quality']['source_digest']
    assert p['receipts']['defect_history']==qc.pp.digest(quality['quality']['defects'])
    assert p['receipts']['draft_plan']==draft['plan_digest']
    assert p['receipts']['draft_result']==qc.pp.digest(draft['receipt'])
    assert p['defect_counts']==dict(OPEN=0,READY_FOR_RETEST=0,CLOSED=1)
    assert o['state']=='BLOCK' and o['checks']['defects']=='BLOCK' and o['defect_counts']['OPEN']==1
    assert s['state']=='BLOCK' and s['checks']['human_qa']==s['checks']['sandbox']=='BLOCK'
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4a QC evidence PASS; sha256='+digest)
if __name__=='__main__':main()
