"""Reconstruct dependency graph from exact known fixture, bind to Git evidence."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_dependency_impact as d

def main():
    raw=Path(sys.argv[1]).read_bytes();a=json.loads(raw);git=json.loads(Path(sys.argv[2]).read_bytes())
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert a[k]==git[k]==os.environ[v]
    assert a['schema']=='orbit.dependency-impact-browser.v1' and a['viewer_read'] is True and a['post_rejected'] is True
    v=a['current'];s=a['stale'];g=git['current']
    for x in (v,s):
        assert x['schema']=='orbit.dependency-impact-evidence.v1'
        assert x['project_id']==g['project_id'] and x['job_id']==g['job_id']
        assert x['evidence_digest']==d.pp.digest({k:y for k,y in x.items() if k!='evidence_digest'})
        assert x['full_regression_required'] is True and x['selective_execution_authorized'] is False
        assert all(x[k] is False for k in d.FLAGS)
    assert v['state']=='DEPENDENCY_IMPACT_READY' and s['state']=='BLOCK' and s['graphs']==s['comparisons']=={} and s['source'] is None
    assert v['source']==dict(git_change_evidence_digest=g['evidence_digest'],git_source=g['source'])
    files={'main.py':'def add(a,b):\n    return a+b\n',
           'test_main.py':'import unittest\nfrom main import add\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2,3),5)\n'}
    proposals={k:dict(summary='Synthetic coding fixture '+k,files=[dict(path=p,content=x,sha256=hashlib.sha256(x.encode()).hexdigest()) for p,x in files.items()]) for k in ('A','B')}
    # Lane digest depends on file content/order, not summary.
    graphs,comparisons=d.derive(g,proposals)
    assert v['graphs']==graphs and v['comparisons']==comparisons
    assert v['selected_comparison']==g['selected_comparison']=='baseline_to_B'
    assert graphs['A']==graphs['B'] and graphs['B']['edges']==[dict(importer='test_main.py',dependency='main.py')]
    assert graphs['B']['uncertainties']==[]
    assert comparisons['baseline_to_B']['current_impacted_paths']==['main.py','test_main.py']
    assert comparisons['A_to_B']['impacted_paths']==[] and all(x['full_regression_required'] is True for x in comparisons.values())
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4d.2 dependency impact evidence PASS; sha256='+digest)
if __name__=='__main__':main()
