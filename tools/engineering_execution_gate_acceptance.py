"""Validate the combined gate against independent run-bound QC/plan/registry evidence."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import execution_quality_gate as g

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    q,p,r=[json.loads(Path(x).read_bytes()) for x in sys.argv[2:]]
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[k]==q[k]==p[k]==r[k]==os.environ[v]
    assert d['schema']=='orbit.execution-quality-browser.v1'
    assert d['post_rejected'] is True and d['viewer_read'] is True
    for key,qv,pv,rv in (('before',q['passed'],p['upgraded'],r['initial']),
                         ('passed',q['passed'],p['upgraded'],r['second']),
                         ('stale',q['stale'],p['stale'],r['stale'])):
        v=d[key]
        assert v==g.evaluate(v['project_id'],v['job_id'],qv,pv,rv)
        assert all(v[k] is False for k in g.FLAGS)
    assert d['before']['state']=='BLOCK' and d['before']['checks']['legacy_qc']=='PASS'
    assert d['before']['checks']['test_plan']=='PASS' and d['before']['checks']['execution_receipt']=='BLOCK'
    assert d['passed']['state']=='EXECUTION_QUALITY_PASS' and all(x=='PASS' for x in d['passed']['checks'].values())
    assert d['stale']['state']=='BLOCK' and d['stale']['checks']['execution_receipt']=='BLOCK'
    assert d['passed']['receipts']['execution']==r['second']['current_receipt']['digest']
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4c.4 execution quality gate evidence PASS; sha256='+digest)
if __name__=='__main__':main()
