"""Verify real Git change evidence against the run-bound selected sandbox."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_git_changes as g

def main():
    raw=Path(sys.argv[1]).read_bytes();d=json.loads(raw)
    sandbox,final=[json.loads(Path(x).read_bytes()) for x in sys.argv[2:]]
    for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        assert d[k]==sandbox[k]==final[k]==os.environ[v]
    assert d['schema']=='orbit.git-change-browser.v1' and d['viewer_read'] is True and d['post_rejected'] is True
    v=d['current'];s=d['stale'];src=v['source'];receipt=sandbox['receipt']
    for x in (v,s):
        assert x['schema']=='orbit.git-change-evidence.v1'
        assert x['project_id']==sandbox['project_id'] and x['job_id']==sandbox['job_id']
        assert x['evidence_digest']==g.pp.digest({k:y for k,y in x.items() if k!='evidence_digest'})
        assert all(x[k] is False for k in g.FLAGS)
        assert x['baseline_kind']=='empty_project_baseline' and x['comparison_kind']=='independent_candidates'
        assert x['rename_detection'] is False
    assert v['state']=='GIT_CHANGE_EVIDENCE_READY' and s['state']=='BLOCK' and s['source'] is None and s['comparisons']=={}
    assert src['project_id']==v['project_id'] and src['job_id']==v['job_id']
    assert src['git']==receipt['git'] and src['selected']==receipt['selected']=='B'
    assert src['selection_digest']==receipt['selection_digest'] and src['sandbox_digest']==receipt['digest']
    assert src['base_commit']==g.ws.baseline(v['project_id'])[2]
    report=final['recovered']['registry']['current_receipt']['snapshot']['report']['source']
    assert src['sandbox_digest']==report['sandbox_digest'] and src['git']['B']==report['git']
    files={'main.py':'def add(a,b):\n    return a+b\n',
           'test_main.py':'import unittest\nfrom main import add\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2,3),5)\n'}
    expected={k:dict(blob=g.ws.object_id('blob',x.encode()),sha256=hashlib.sha256(x.encode()).hexdigest()) for k,x in files.items()}
    assert set(v['comparisons'])==set(g.COMPARISONS) and v['selected_comparison']=='baseline_to_B'
    for lane in ('A','B'):
        c=v['comparisons']['baseline_to_'+lane]
        assert c['from_commit']==src['base_commit'] and c['to_commit']==src['git'][lane]['commit']
        assert c['changes']==g.expected_changes({},expected) and c['counts']==dict(ADDED=2,MODIFIED=0,DELETED=0)
        assert c['unchanged_count']==0
    c=v['comparisons']['A_to_B']
    assert c['from_commit']==src['git']['A']['commit'] and c['to_commit']==src['git']['B']['commit']
    assert c['changes']==[] and c['counts']==dict(ADDED=0,MODIFIED=0,DELETED=0) and c['unchanged_count']==2
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.4d.1 Git change evidence PASS; sha256='+digest)
if __name__=='__main__':main()
