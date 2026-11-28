"""Bind advisory test mapping to the exact impact, contract and executed results."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_impacted_tests as m

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    impact,contract,runner,final=[json.loads(Path(x).read_bytes()) for x in sys.argv[2:]]
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert all(x[k]==os.environ[v] for x in (d,impact,contract,runner,final))
    assert d['schema']=='orbit.impacted-test-browser.v1' and d['viewer_read'] is True and d['post_rejected'] is True
    for name,plan,report in (('initial',contract['upgraded'],runner['result']['report']),
                             ('recovered',final['corrected_plan'],final['recovered']['result']['report'])):
        v=d[name];targets=[{k:x[k] for k in ('path','module_sha256')} for x in report['results']]
        src,selected,mappings=m.derive(impact['current'],plan,report['source'],targets)
        assert v['state']=='IMPACTED_TEST_MAPPING_READY' and v['source']==src
        assert v['selected_comparison']==selected=='baseline_to_B' and v['mappings']==mappings
        assert mappings[selected]['case_count']==mappings[selected]['impacted_count']==mappings[selected]['required_count']==3
        assert mappings['A_to_B']['impacted_count']==0 and mappings['A_to_B']['required_count']==3
        assert all(x['required'] is True for p in mappings.values() for x in p['cases'])
    s=d['stale']
    assert s['state']=='BLOCK' and s['source'] is None and s['mappings']=={} and s['selected_comparison'] is None
    for v in (d['initial'],d['recovered'],s):
        assert v['schema']=='orbit.impacted-test-mapping.v1' and m.digest_ok(v)
        assert v['project_id']==impact['current']['project_id'] and v['job_id']==impact['current']['job_id']
        assert v['full_regression_required'] is True and v['selective_execution_authorized'] is False
        assert all(v[k] is False for k in m.FLAGS)
    assert d['initial']['evidence_digest']!=d['recovered']['evidence_digest']
    assert d['initial']['mappings']==d['recovered']['mappings']
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4d.3 impacted test mapping evidence PASS; sha256='+digest)
if __name__=='__main__':main()
