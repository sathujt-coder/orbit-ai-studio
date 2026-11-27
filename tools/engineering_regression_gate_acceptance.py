"""Reconstruct the durable regression gate from run-bound artifacts."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import regression_quality_gate as g

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    mapping,final,impact,registry,old=[json.loads(Path(x).read_bytes()) for x in sys.argv[2:]]
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert all(x[k]==os.environ[v] for x in (d,mapping,final,impact,registry,old))
    assert d['schema']=='orbit.regression-quality-browser.v1'
    assert d['viewer_read'] is True and d['post_rejected'] is True
    pid=mapping['initial']['project_id'];jid=mapping['initial']['job_id']
    def inputs(plan,report):
        return plan['history'][-1]['snapshot']['cases'],[{k:x[k] for k in ('path','module_sha256')} for x in report['results']]
    initial=registry['second'];ireport=initial['current_receipt']['snapshot']['report']
    # The initial mapping is already validated by the mandatory earlier validator.
    initial_cases=final['corrected_plan']['history'][1]['snapshot']['cases']
    itargets=[{k:x[k] for k in ('path','module_sha256')} for x in ireport['results']]
    assert d['missing']==g.evaluate(pid,jid,old['passed'],initial,mapping['initial'],ireport['source'],initial_cases,itargets,None)
    assert d['missing']['state']=='BLOCK' and d['missing']['checks']['execution_quality']=='PASS'
    assert d['missing']['checks']['durable_priority_receipt']=='BLOCK'
    f=final['failed'];z=final['recovered']
    cases,targets=inputs(final['failed_plan'],f['result']['report'])
    fs=f['result']['report']['source'];fm=d['failed_mapping']
    src,selected,maps=g.mapping.derive(impact['current'],final['failed_plan'],fs,targets)
    assert g.mapping.digest_ok(fm) and fm['source']==src and fm['selected_comparison']==selected and fm['mappings']==maps
    for name,step,plan,m in (('failed',f,final['failed_plan'],fm),('recovered',z,final['corrected_plan'],mapping['recovered'])):
        result=step['result'];report=result['report'];cases,targets=inputs(plan,report)
        receipt=result['priority_receipt'];v=d[name]
        assert v==g.evaluate(pid,jid,step['gate'],step['registry'],m,report['source'],cases,targets,receipt)
        assert v['priority_receipt']==receipt and v['checks']['durable_priority_receipt']=='PASS'
        assert result['priority']==receipt['snapshot']['priority'] and result['priority_digest']==receipt['snapshot']['priority_digest']
        assert receipt['snapshot']['execution_receipt_digest']==step['registry']['current_receipt']['digest']
        assert receipt['snapshot']['execution_version']==step['registry']['latest_version']
        assert report['case_count']==report['executed_count']==3
        assert v['state']==('BLOCK' if name=='failed' else 'REGRESSION_QUALITY_PASS')
        assert v['checks']['mandatory_regression']==('BLOCK' if name=='failed' else 'PASS')
    report=z['result']['report'];cases,targets=inputs(final['corrected_plan'],report)
    assert d['before_recovery']==g.evaluate(pid,jid,final['before_recovery']['gate'],final['before_recovery']['registry'],
         mapping['recovered'],report['source'],cases,targets,None)
    assert d['before_recovery']['state']=='BLOCK' and d['before_recovery']['priority_receipt'] is None
    assert d['stale']==g.evaluate(pid,jid,final['stale']['gate'],{}, {},None,[],[],None)
    assert d['stale']['state']=='BLOCK' and d['stale']['priority_receipt'] is None
    for name in ('missing','failed','before_recovery','recovered','stale'):
        v=d[name];assert g.mapping.digest_ok(v)
        assert all(v[k] is False for k in g.FLAGS)
        assert v['full_regression_required'] is True and v['selective_execution_authorized'] is False
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4d.5 regression quality gate evidence PASS; sha256='+digest)
if __name__=='__main__':main()
