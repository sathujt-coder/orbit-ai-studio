"""Bind real per-case runner evidence to the immutable contract and sandbox."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import acceptance_runner as r

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    a,s=[json.loads(Path(p).read_bytes()) for p in sys.argv[2:]]
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[k]==a[k]==s[k]==os.environ[v]
    assert d['schema']=='orbit.assertion-runner-browser.v1' and d['transport']=='real_git_docker_assertions'
    assert d['rbac_rejected'] is True and d['stale_rejected'] is True
    report=d['result']['report'];source=report['source'];plan=a['upgraded']['history'][-1];e=plan['snapshot']
    assert d['result']['digest']==r.pp.digest(report)
    assert report['schema']=='orbit.acceptance-runner-report.v1' and report['gate']=='PASS'
    assert report['persisted'] is False and all(report[k] is False for k in r.FLAGS)
    assert report['runtime']=='docker' and report['network']=='none' and report['workspace']=='read-only'
    r.vf.pinned_image(report['image'])
    assert report['image']==os.environ['ORBIT_SANDBOX_PYTHON_IMAGE']
    assert source['project_id']==s['project_id']==e['project_id'] and source['job_id']==s['job_id']==e['job_id']
    assert source['plan_version']==e['version'] and source['plan_digest']==plan['digest']
    assert source['source_digest']==e['source_digest'] and source['assertion_contract_digest']==e['assertion_contract_digest']
    sr=s['receipt'];assert source['selected']==sr['selected']=='B'
    assert source['sandbox_digest']==sr['digest'] and source['selection_digest']==sr['selection_digest']
    assert source['git']==sr['git']['B'] and source['candidate_digest']==source['git']['source_sha256']==e['source']['candidates']['B']['digest']
    cases=e['cases'];results=report['results']
    assert len(cases)==len(results)==report['case_count']==report['executed_count']>0
    assert len({x['case_id'] for x in results})==len(cases)
    for case,result in zip(cases,results):
        x=case['execution']
        assert (result['case_id'],result['criterion_id'],result['kind'])==(case['id'],case['criterion_id'],case['kind'])
        assert result['assertion_digest']==r.pp.digest(x) and result['path']==x['module']+'.py'
        assert len(result['module_sha256'])==64 and set(result['module_sha256'])<=r.HEX
        assert result['status']=='PASS' and result['executed'] is True and result['reason']=='ASSERTION_MATCH'
        if x['assertion']['operator']=='equals':
            assert result['observation']=='returned' and result['value_digest']==r.pp.digest(x['assertion']['value'])
        else:assert result['observation']=='raised' and result['exception']==x['assertion']['exception']
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4c.2 runner evidence PASS; sha256='+digest)
if __name__=='__main__':main()
