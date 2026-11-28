"""Validate actual Docker-bound registry receipts against severity evidence."""
import hashlib,json,os,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(root/'tests')]
import detected_defect_registry as r
from test_detected_defect_registry import DetectedRegistryTests

def require(ok):
    if not ok:raise ValueError('Invalid defect registry lifecycle')

def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DetectedRegistryTests))
    require(result.wasSuccessful() and result.testsRun==10 and not result.skipped)
    raw=Path(sys.argv[1]).read_bytes();prior=json.loads(raw)
    v=json.loads(Path(sys.argv[2]).read_bytes())
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(prior['gate']=='PASS' and all(prior[k]==v[k]==x for k,x in identity.items()))
    for k,state in [('pending','REGISTRATION_REQUIRED'),('registered','REGISTERED'),('recovered','NO_CURRENT_FINDINGS'),('stale','BLOCK')]:
        x=v[k]
        require(x['state']==state and x['automatic_closure'] is False and x['quality_gate_override'] is False)
        require(all(x[f] is False for f in r.FLAGS))
        require(x['evidence_digest']==r.pp.digest({a:b for a,b in x.items() if a!='evidence_digest'}))
    require(not v['pending']['history'] and len(v['registered']['history'])==1)
    receipt=v['registered']['history'][0];e=receipt['snapshot'];s=prior['observations']['failed']
    require(receipt['digest']==r.pp.digest(e) and e['severity_digest']==s['evidence_digest'])
    require(e['classification']==s['items'][0] and e['state']=='OPEN' and e['version']==1 and e['previous_digest'] is None)
    require(v['registered']['history']==v['recovered']['history']==v['stale']['history'])
    require(v['duplicate_rejected'] is True and v['failed_gate']=='BLOCK')
    out=dict(schema='orbit.detected-defect-registry-acceptance.v1',**identity,gate='PASS',tests=result.testsRun,
             severity_sha256=hashlib.sha256(raw).hexdigest(),observations=v,**r.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    Path(sys.argv[3]).write_bytes(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
