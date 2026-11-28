"""Verify exact candidate scan using private fixture bytes; never publish source."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import security_sast as s
def require(ok,message):
    if not ok:raise ValueError(message)
def read(path):
    raw=Path(path).read_bytes();return raw,json.loads(raw)
def main():
    tr,threat=read(sys.argv[1]);rr,retest=read(sys.argv[2]);_,http=read(sys.argv[3])
    path=Path(sys.argv[4])
    try:proposal=json.loads(path.read_bytes())
    finally:path.unlink()
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(all(v[k]==x for v in (threat,retest,http) for k,x in identity.items()),'CI identity mismatch')
    require(threat['gate']==retest['gate']=='PASS' and threat['retest_sha256']==hashlib.sha256(rr).hexdigest(),'Upstream evidence mismatch')
    o=retest['observations'];pid,jid=o['project_id'],o['job_id'];points=o['sast_points']
    files,digest=s.manifest(proposal)
    require(set(points)==set(threat['isolated'])=={'first_closed','stale','final'},'Missing isolated checkpoints')
    for k,v in points.items():
        source=o['points'][k]['receipt']['snapshot']['report']['source']
        git,_=s.security.runner.sb.git_objects(proposal,source['git']['parent'],jid,source['selected'])
        require(git==source['git'] and digest==source['candidate_digest'],'Exact Git source mismatch')
        require(v==s.evaluate(pid,jid,threat['isolated'][k],proposal),'Independent SAST reconstruction mismatch')
        require(v['scan_verdict']!='NOT_ASSESSED' and any(x['status']=='SCANNED' for x in v['files']),'Actual Python scan missing')
        require(k!='stale' or v['state']=='BLOCK','Stale accepted')
    require(all(http[k] is True for k in ('viewer_read','cross_project_denied','post_denied','csrf_denied')),'Missing HTTP controls')
    for k in ('open','recovered','stale'):
        require(http[k]==s.evaluate(pid,jid,threat['http'][k],proposal) and http[k]['state']=='BLOCK','HTTP source mismatch')
    require(http['stale']['source'] is None and http['open']['evidence_digest']!=http['recovered']['evidence_digest'],'Stale or unchanged source')
    for v in (*points.values(),*(http[k] for k in ('open','recovered','stale'))):
        require(v['security_gate']=='BLOCK' and all(v.get(k) is False for k in s.FLAGS),'False security approval')
    # Controlled negative bytes, analyzed but never imported or executed.
    bad=s.cf.validate_proposal({'files':[dict(path='fixture.py',content='import pickle as p\np.loads(data)\neval(data)\n')]})
    _,findings=s.scan_file(bad['files'][0])
    require({x['rule_id'] for x in findings}=={'SAST01','SAST03'},'Negative scanner control failed')
    out=dict(schema='orbit.sast-acceptance.v1',**identity,gate='PASS',security_gate='BLOCK',
        threat_sha256=hashlib.sha256(tr).hexdigest(),retest_sha256=hashlib.sha256(rr).hexdigest(),
        policy=s.POLICY,policy_digest=s.pp.digest(s.POLICY),isolated=points,http=http,negative_control=findings,**s.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    with Path(sys.argv[5]).open('xb') as file:file.write(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:file.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
