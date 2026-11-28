import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_test_plan as tp

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw);qc=json.loads(Path(sys.argv[2]).read_bytes())
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[k]==qc[k]==os.environ[v]
    assert d['schema']=='orbit.acceptance-test-plan-browser.v1' and d['transport']=='synthetic_test_plan_real_http'
    for k in ('rbac_rejected','csrf_rejected','incomplete_rejected','duplicate_version_rejected','stale_write_rejected'):assert d[k] is True
    a,p,s=(d[k] for k in ('initial','passed','stale'))
    for v in (a,p,s):
        assert v['project_id']==qc['passed']['project_id'] and v['job_id']==qc['passed']['job_id']
        assert v['execution_status']=='NOT_EXECUTED' and all(v[k] is False for k in tp.FLAGS)
    assert a['state']=='AWAITING_TEST_PLAN' and a['history']==[]
    assert p['state']=='TEST_PLAN_COVERAGE_PASS' and p['latest_version']==1
    assert s['state']=='STALE' and s['history'][:len(p['history'])]==p['history']
    assert len(p['history'])==1
    r=p['history'][0];e=r['snapshot'];src=e['source']
    assert tp.pp.digest(e)==r['digest'] and e['previous_digest'] is None and e['version']==1
    assert e['source_digest']==tp.pp.digest(src)==p['source_digest']==a['source_digest']
    assert src['acceptance']==p['criteria']==a['criteria']
    assert all(src[k]==qc['passed']['binding'][k] for k in qc['passed']['binding'])
    cases,cov=tp.coverage(src,e['cases'])
    assert cases==e['cases'] and cov==e['coverage'] and cov['complete']
    assert cov['criteria_covered']==cov['criteria_total'] and cov['cases_total']>=3*cov['criteria_total']
    assert all(e[k] is False for k in tp.FLAGS)
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4b test planning evidence PASS; sha256='+digest)
if __name__=='__main__':main()
