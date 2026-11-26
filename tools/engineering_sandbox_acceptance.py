"""Validate mandatory real Git/Docker browser evidence and bind to exact CI run."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

def main():
    raw=Path(sys.argv[1]).read_bytes()
    d=json.loads(raw)
    for key,env in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT')):
        if d.get(key)!=os.environ[env]:raise ValueError('Evidence run binding mismatch: '+key)
    def require(ok):
        if not ok:raise ValueError('Incomplete engineering sandbox evidence')
    def hexstr(v,n):return isinstance(v,str) and bool(re.fullmatch('[0-9a-f]{'+str(n)+'}',v))
    require(d['schema']=='orbit.engineering-sandbox-browser.v1' and d['transport']=='synthetic_inference_real_git_real_docker')
    require(all(d[k] is False for k in ('execution_authorized','merge_authorized','production_release_authorized')))
    require(hexstr(d['base_commit'],40) and hexstr(d['selection_digest'],64))
    r=d['receipt']
    require(r['gate']=='PASS' and r['selected']=='B' and r['version']==2 and r['selection_digest']==d['selection_digest'] and hexstr(r['digest'],64))
    require(set(r['git'])==set(r['lanes'])=={'A','B'} and r['git']['A']['commit']!=r['git']['B']['commit'])
    for lane in ('A','B'):
        g=r['git'][lane];v=r['lanes'][lane]
        require(hexstr(g['commit'],40) and hexstr(g['tree'],40) and g['parent']==d['base_commit'])
        require(hexstr(g['source_sha256'],64) and g['source_sha256']==v['sha256'] and v['status']=='passed')
        require(type(v['test_count']) is int and v['test_count']>0)
    digest=hashlib.sha256(raw).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+digest+'\n')
    print('P6.3g real Git sandbox evidence PASS; sha256='+digest)

if __name__=='__main__':main()
