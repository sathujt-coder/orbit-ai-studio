"""Mandatory registry evidence validator, bound to the accepted real runner."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_assertion_registry as reg

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    runner,contract=[json.loads(Path(p).read_bytes()) for p in sys.argv[2:]]
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[k]==runner[k]==contract[k]==os.environ[v]
    assert d['schema']=='orbit.assertion-registry-browser.v1'
    assert all(d[k] is True for k in ('duplicate_rejected','post_rejected','stale_rejected'))
    a,b,c,s=(d[k] for k in ('initial','first','second','stale'))
    assert a['state']=='AWAITING_EXECUTION' and a['history']==[] and a['latest_version']==0
    assert b['state']==c['state']=='EXECUTION_RECORDED_PASS'
    assert b['latest_version']==1 and c['latest_version']==s['latest_version']==2
    assert len(b['history'])==1 and len(c['history'])==2 and c['history'][:1]==b['history']
    assert s['state']=='STALE' and s['current_receipt'] is None and s['history']==c['history']
    assert b['current_receipt']==b['history'][0] and c['current_receipt']==c['history'][1]
    plan=contract['upgraded']['history'][-1]['snapshot']
    source=runner['result']['report']['source'];cases=plan['cases']
    targets=[{k:x[k] for k in ('path','module_sha256')} for x in runner['result']['report']['results']]
    for v in (a,b,c,s):
        assert v['project_id']==source['project_id'] and v['job_id']==source['job_id'] and all(v[k] is False for k in reg.FLAGS)
    previous=None
    for version,r in enumerate(c['history'],1):
        e=r['snapshot'];report=e['report']
        assert reg.pp.digest(e)==r['digest'] and e['previous_digest']==previous and e['version']==version
        assert e['schema']=='orbit.assertion-run-receipt.v1' and e['project_id']==source['project_id'] and e['job_id']==source['job_id']
        assert e['report_digest']==reg.pp.digest(report) and report==runner['result']['report']
        assert e['summary']==reg.validate_report(report,source,cases,targets) and e['summary']['gate']=='PASS'
        assert all(e[k] is False for k in reg.FLAGS)
        previous=r['digest']
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4c.3 immutable result registry evidence PASS; sha256='+digest)
if __name__=='__main__':main()
