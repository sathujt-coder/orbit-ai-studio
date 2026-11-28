"""Validate actual source-bound security observations; not security qualification."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import security_evidence as s

def require(ok,message):
    if not ok:raise ValueError(message)
def check(v,state):
    require(v['schema']=='orbit.security-evidence.v1' and v['state']==state and v['security_gate']=='BLOCK','Security verdict mismatch')
    require(v['evidence_digest']==s.pp.digest({k:x for k,x in v.items() if k!='evidence_digest'}),'Invalid security digest')
    require(v['assessments']==dict.fromkeys(s.ASSESSMENTS,'NOT_ASSESSED') and all(v.get(k) is False for k in s.FLAGS),'Security authorization or false assessment')
    require(set(v['checks'])==set(s.CHECKS),'Missing security checks')
def main():
    raw=Path(sys.argv[1]).read_bytes();trusted=json.loads(raw);http=json.loads(Path(sys.argv[2]).read_bytes())
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(trusted['gate']=='PASS' and all(trusted[k]==http[k]==v for k,v in identity.items()),'Wrong run')
    o=trusted['observations'];pid,jid=o['project_id'],o['job_id']
    points=o['security_points'];require(set(points)=={'first_closed','stale','final'},'Missing isolated security checkpoints')
    for key,v in points.items():
        p=o['points'][key];receipt=p['receipt'];source=receipt['snapshot']['report']['source']
        check(v,'BLOCK' if key=='stale' else 'SECURITY_EVIDENCE_READY')
        require(v==s.evaluate(pid,jid,source,receipt,p['gate']),'Independent security reconstruction mismatch')
    require(points['first_closed']['source']['execution_digest']!=points['final']['source']['execution_digest'],'Fresh execution missing')
    require(all(http[k] is True for k in ('viewer_read','cross_project_denied','post_denied','csrf_denied')),'HTTP security checks missing')
    for key in ('open','recovered','stale'):
        v=http[key];check(v,'BLOCK');require((v['project_id'],v['job_id'])==(pid,jid),'HTTP scope mismatch')
    for key in ('open','recovered'):
        v=http[key];g=http[key+'_retest']
        require(g['evidence_digest']==s.pp.digest({k:x for k,x in g.items() if k!='evidence_digest'}),'HTTP retest digest mismatch')
        require(v['source']['retest_digest']==g['evidence_digest'] and v['source']['execution_digest']==g['execution_digest'],'HTTP current source mismatch')
    require(http['stale']['source'] is None and http['open']['evidence_digest']!=http['recovered']['evidence_digest'],'Stale or unchanged source accepted')
    out=dict(schema='orbit.security-evidence-acceptance.v1',**identity,gate='PASS',security_gate='BLOCK',
        retest_sha256=hashlib.sha256(raw).hexdigest(),isolated=points,http=http,**s.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    with Path(sys.argv[3]).open('xb') as file:file.write(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:file.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
