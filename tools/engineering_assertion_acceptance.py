"""Run-bound assertion contract acceptance; no test execution claims."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_test_plan as tp

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw);p=json.loads(Path(sys.argv[2]).read_bytes())
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[k]==p[k]==os.environ[v]
    assert d['schema']=='orbit.assertion-contract-browser.v1'
    assert all(d[k] is True for k in ('shell_rejected','downgrade_rejected','rbac_rejected'))
    a,b,s=(d[k] for k in ('legacy','upgraded','stale'))
    assert a==p['passed'] and s==p['stale']
    assert a['assertion_status']=='NOT_READY' and a['latest_version']==1
    assert b['state']=='TEST_PLAN_COVERAGE_PASS' and b['assertion_status']=='ASSERTION_CONTRACT_READY' and b['latest_version']==2
    assert s['state']=='STALE' and s['assertion_status']=='NOT_READY' and s['assertion_contract_digest'] is None
    assert b['history'][:1]==a['history'] and len(b['history'])==2 and s['history']==b['history']
    for v in (a,b,s):
        assert v['project_id']==a['project_id'] and v['job_id']==a['job_id']
        assert v['execution_status']=='NOT_EXECUTED' and all(v[k] is False for k in tp.FLAGS)
    r=b['history'][1];e=r['snapshot']
    assert e['schema']==tp.V2 and e['version']==2 and e['previous_digest']==a['history'][0]['digest']
    assert tp.pp.digest(e)==r['digest'] and e['source_digest']==tp.pp.digest(e['source'])==a['source_digest']==b['source_digest']
    assert e['source']==a['history'][0]['snapshot']['source'] and all(e[k] is False for k in tp.FLAGS)
    cases,cov=tp.coverage(e['source'],e['cases'],tp.V2)
    assert cases==e['cases'] and cov==e['coverage'] and cov['complete']
    assert [{k:v for k,v in x.items() if k!='execution'} for x in cases]==a['history'][0]['snapshot']['cases']
    assert e['assertion_contract_digest']==tp.contract_digest(e)==b['assertion_contract_digest']
    for case in cases:
        x=case['execution'];assert x['module']=='main' and x['function']=='add'
        if case['kind']=='POSITIVE':assert x['arguments']==[2,3] and x['assertion']==dict(operator='equals',value=5)
        elif case['kind']=='NEGATIVE':assert x['arguments']==[2,'bad'] and x['assertion']==dict(operator='raises',exception='TypeError')
        else:assert x['arguments']==[0,0] and x['assertion']==dict(operator='equals',value=0)
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4c.1 assertion contract acceptance PASS; sha256='+digest)
if __name__=='__main__':main()
