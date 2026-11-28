"""Recompute priority order and require every actual Docker result, even zero impact."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import regression_priority as p

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    mapping,final=[json.loads(Path(x).read_bytes()) for x in sys.argv[2:]]
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert all(x[k]==os.environ[v] for x in (d,mapping,final))
    assert d['schema']=='orbit.regression-priority-browser.v1'
    assert all(d[k] is True for k in ('old_mapping_rejected','stale_rejected','registry_unchanged'))
    m=mapping['recovered'];report=final['recovered']['result']['report']
    cases=final['corrected_plan']['history'][-1]['snapshot']['cases']
    targets=[{k:x[k] for k in ('path','module_sha256')} for x in report['results']]
    assert set(d['runs'])=={'baseline_to_B','A_to_B'}
    kinds={x['kind']:x['id'] for x in cases}
    for comparison,v in d['runs'].items():
        assert set(v)=={'report','digest','priority','priority_digest'}
        assert v['report']==report and v['digest']==p.pp.digest(report)
        schedule=p.schedule(m,report['source'],cases,targets,comparison,m['evidence_digest'])
        expected=[kinds[k] for k in ('NEGATIVE','BOUNDARY','POSITIVE')] if comparison=='baseline_to_B' else [x['id'] for x in cases]
        assert schedule['execution_order']==expected and schedule['required_count']==3
        assert schedule['impacted_count']==(3 if comparison=='baseline_to_B' else 0)
        e=p.evidence(schedule,expected,report)
        assert v['priority']==e and v['priority_digest']==p.pp.digest(e)
        assert e['unattempted_order']==[] and e['gate']=='PASS'
        assert report['case_count']==report['executed_count']==3 and all(x['executed'] is True and x['status']=='PASS' for x in report['results'])
        assert all(e[k] is False for k in p.FLAGS)
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4d.4 prioritized full regression evidence PASS; sha256='+digest)
if __name__=='__main__':main()
