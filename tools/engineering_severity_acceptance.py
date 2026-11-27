"""Run severity regressions and validate actual operator-reviewed Docker findings."""
import hashlib,json,os,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(root/'tests')]
from test_defect_severity import SeverityTests
import defect_severity as s

def main():
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SeverityTests))
    if not r.wasSuccessful() or r.testsRun!=14 or r.skipped:raise SystemExit(1)
    raw=Path(sys.argv[1]).read_bytes();prior=json.loads(raw)
    v=json.loads(Path(sys.argv[2]).read_bytes())
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    if prior['gate']!='PASS' or any(prior[k]!=x or v[k]!=x for k,x in identity.items()):raise ValueError('Identity mismatch')
    for name,state in [('failed','CLASSIFIED'),('recovered','NO_FINDINGS'),('stale','BLOCK')]:
        x=v[name]
        if x['state']!=state or x['quality_gate_override'] is not False or any(x[k] is not False for k in s.FLAGS):raise ValueError('Severity lifecycle mismatch')
        if x['evidence_digest']!=s.pp.digest({k:y for k,y in x.items() if k!='evidence_digest'}):raise ValueError('Digest mismatch')
        if name!='stale' and x['detection_digest']!=prior['observations'][name]['detection_digest']:raise ValueError('Detection binding mismatch')
    item=v['failed']['items'][0]
    if item['severity']!='LOW' or not item['impact_confirmed'] or not item['attestation_digest'] or v['failed_gate']!='BLOCK':raise ValueError('Gate separation missing')
    out=dict(schema='orbit.severity-hardening-acceptance.v1',**identity,gate='PASS',tests=r.testsRun,policy=s.POLICY,
             classification_sha256=hashlib.sha256(raw).hexdigest(),observations=v,**s.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    Path(sys.argv[3]).write_bytes(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
