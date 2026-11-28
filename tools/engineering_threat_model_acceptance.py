"""Verify actual threat model snapshots against security and retest artifacts."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import security_threat_model as t
def require(ok,message):
    if not ok:raise ValueError(message)
def read(path):
    raw=Path(path).read_bytes();return raw,json.loads(raw)
def main():
    raw,security=read(sys.argv[1]);rr,retest=read(sys.argv[2]);_,http=read(sys.argv[3])
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(all(v[k]==x for v in (security,retest,http) for k,x in identity.items()),'CI identity mismatch')
    require(security['gate']==retest['gate']=='PASS' and security['retest_sha256']==hashlib.sha256(rr).hexdigest(),'Upstream evidence mismatch')
    o=retest['observations'];pid,jid=o['project_id'],o['job_id'];points=o['threat_points']
    require(set(points)==set(security['isolated'])=={'first_closed','stale','final'},'Incomplete isolated checkpoints')
    for k,v in points.items():
        require(v==t.evaluate(pid,jid,security['isolated'][k]),'Independent threat reconstruction mismatch')
        require(v['state']==('BLOCK' if k=='stale' else 'THREAT_MODEL_READY'),'Unexpected threat verdict')
    require(points['first_closed']['source']['execution_digest']!=points['final']['source']['execution_digest'],'Fresh execution missing')
    require(all(http[k] is True for k in ('viewer_read','cross_project_denied','post_denied','csrf_denied')),'Missing HTTP controls')
    for k in ('open','recovered','stale'):
        require(http[k]==t.evaluate(pid,jid,security['http'][k]) and http[k]['state']=='BLOCK','HTTP source mismatch')
    require(http['stale']['source'] is None and http['open']['evidence_digest']!=http['recovered']['evidence_digest'],'Stale or unchanged evidence')
    c=t.catalog();require((len(c['assets']),len(c['boundaries']),len(c['threats']),len(c['requirements']))==(7,6,16,16),'Catalog coverage mismatch')
    for v in (*points.values(),*(http[k] for k in ('open','recovered','stale'))):
        require(v['catalog_digest']==t.pp.digest(c) and v['security_gate']=='BLOCK'
                and v['candidate_analysis']=='NOT_ASSESSED' and all(v.get(k) is False for k in t.FLAGS),'False security approval')
        require(all(x['verification_status']=='NOT_VERIFIED' and x['mandatory'] is True for x in v['requirements']),'False verification')
    out=dict(schema='orbit.threat-model-acceptance.v1',**identity,gate='PASS',security_gate='BLOCK',catalog=c,
        catalog_digest=t.pp.digest(c),security_sha256=hashlib.sha256(raw).hexdigest(),retest_sha256=hashlib.sha256(rr).hexdigest(),
        isolated=points,http=http,**t.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    with Path(sys.argv[4]).open('xb') as file:file.write(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:file.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
