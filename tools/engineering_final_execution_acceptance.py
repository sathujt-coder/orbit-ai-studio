"""Reconstruct full real-Docker failure/recovery lifecycle from run-bound evidence."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import execution_quality_gate as g

def validate(d,q,p,r,old):
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        if not os.environ.get(v) or not all(x[k]==os.environ[v] for x in (d,q,p,r,old)):
            raise ValueError('Run identity mismatch')
    assert d['schema']=='orbit.final-automated-test-execution.v1'
    assert all(d[k] is True for k in ('stale_authorization_rejected','old_gate_digest_rejected','stale_guard_rejected'))
    base=p['upgraded'];failed=d['failed_plan'];fixed=d['corrected_plan'];initial=r['second']
    assert failed['history'][:2]==base['history'] and fixed['history'][:3]==failed['history']
    assert len(failed['history'])==failed['latest_version']==3
    assert len(fixed['history'])==fixed['latest_version']==4
    e0=base['history'][-1]['snapshot'];e1=failed['history'][-1]['snapshot'];e2=fixed['history'][-1]['snapshot']
    for v,e in ((failed,e1),(fixed,e2)):
        assert v['state']=='TEST_PLAN_COVERAGE_PASS' and v['assertion_status']=='ASSERTION_CONTRACT_READY'
        assert v['history'][-1]['digest']==g.pp.digest(e)
        assert e['previous_digest']==v['history'][-2]['digest']
        assert e['schema']==g.tp.V2 and e['version']==v['latest_version']
        assert e['source']==e0['source'] and e['source_digest']==g.pp.digest(e['source'])==e0['source_digest']
        assert e['assertion_contract_digest']==g.tp.contract_digest(e)==v['assertion_contract_digest']
        cases,cov=g.tp.coverage(e['source'],e['cases'],g.tp.V2)
        assert cases==e['cases'] and cov==e['coverage'] and cov['complete']
    assert e2['cases']==e0['cases'] and e2['assertion_contract_digest']==e0['assertion_contract_digest']
    assert e1['assertion_contract_digest']!=e0['assertion_contract_digest']
    changes=[(x,y) for x,y in zip(e0['cases'],e1['cases']) if x!=y]
    assert len(e0['cases'])==len(e1['cases'])==3 and len(changes)==1
    x,y=changes[0];assert x['kind']==y['kind']=='POSITIVE'
    assert x['execution']['assertion']==dict(operator='equals',value=5)
    assert y['execution']['assertion']==dict(operator='equals',value=6)
    assert {**x,'execution':{**x['execution'],'assertion':y['execution']['assertion']}}==y
    f=d['failed'];z=d['recovered'];a=d['after_revision'];b=d['before_recovery'];s=d['stale']
    assert a['registry']['state']==b['registry']['state']=='STALE'
    assert a['registry']['current_receipt'] is None and b['registry']['current_receipt'] is None
    assert a['registry']['history']==initial['history']
    assert f['registry']['history'][:2]==initial['history'] and f['registry']['latest_version']==3
    assert b['registry']['history']==f['registry']['history']
    assert z['registry']['history'][:3]==f['registry']['history'] and z['registry']['latest_version']==4
    assert f['registry']['state']=='EXECUTION_RECORDED_BLOCK' and z['registry']['state']=='EXECUTION_RECORDED_PASS'
    origin=initial['current_receipt']['snapshot']['report']
    targets=[{k:x[k] for k in ('path','module_sha256')} for x in origin['results']]
    for step,plan,e,version,expected in ((f,failed,e1,3,'BLOCK'),(z,fixed,e2,4,'PASS')):
        v=step['registry'];receipt=v['current_receipt'];snap=receipt['snapshot'];report=snap['report']
        assert len(v['history'])==version and receipt==v['history'][-1]==step['result']['receipt']
        assert snap['version']==version and snap['previous_digest']==v['history'][-2]['digest']
        assert receipt['digest']==g.pp.digest(snap)
        assert report==step['result']['report'] and snap['report_digest']==step['result']['digest']==g.pp.digest(report)
        expected_source=dict(origin['source'],plan_version=e['version'],plan_digest=plan['history'][-1]['digest'],
                             assertion_contract_digest=e['assertion_contract_digest'])
        assert snap['summary']==g.registry.validate_report(report,expected_source,e['cases'],targets)
        assert report['gate']==expected and report['case_count']==report['executed_count']==3
        assert report['image']==origin['image'] and report['actor']==origin['actor']
        assert all(snap[k] is False for k in g.FLAGS)
        if expected=='BLOCK':
            assert snap['summary']['pass_count']==2
            fail=[x for x in report['results'] if x['status']=='FAIL']
            assert len(fail)==1 and fail[0]['kind']=='POSITIVE' and fail[0]['value_digest']==g.pp.digest(5)
        else:assert snap['summary']['pass_count']==3
    assert s['plan']==p['stale'] and s['registry']==r['stale'] and s['gate']==old['stale']
    assert s['plan']['history']==fixed['history'] and s['registry']['history']==z['registry']['history']
    assert s['registry']['state']=='STALE' and s['registry']['current_receipt'] is None
    pid=e0['project_id'];jid=e0['job_id']
    for step,plan,qv,state in ((a,failed,q['passed'],'BLOCK'),(f,failed,q['passed'],'BLOCK'),
                                (b,fixed,q['passed'],'BLOCK'),(z,fixed,q['passed'],'EXECUTION_QUALITY_PASS'),
                                (s,s['plan'],q['stale'],'BLOCK')):
        v=step['gate']
        assert v==g.evaluate(pid,jid,qv,plan,step['registry']) and v['state']==state
        assert all(v[k] is False for k in g.FLAGS)
    assert f['gate']['checks']['legacy_qc']==f['gate']['checks']['test_plan']=='PASS'
    assert z['gate']['receipts']['execution']==z['registry']['current_receipt']['digest']
    assert z['gate']['evidence_digest']!=old['passed']['evidence_digest']

def main():
    raw=Path(sys.argv[1]).read_bytes()
    validate(json.loads(raw),*[json.loads(Path(x).read_bytes()) for x in sys.argv[2:]])
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4c.5 final automated test execution evidence PASS; sha256='+digest)
if __name__=='__main__':main()
