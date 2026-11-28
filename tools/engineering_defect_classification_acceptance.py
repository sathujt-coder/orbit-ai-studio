"""Verify classifications captured from the live audited Docker lifecycle."""
import hashlib,json,os,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(root/'tests')]
import defect_classification as c
from test_defect_classification import ClassificationTests

def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ClassificationTests))
    if not result.wasSuccessful() or result.testsRun!=10 or result.skipped:
        raise SystemExit(1)
    raw=Path(sys.argv[1]).read_bytes();integration=json.loads(raw)
    observed=json.loads(Path(sys.argv[2]).read_bytes())
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    if integration['gate']!='PASS' or any(integration[k]!=v or observed[k]!=v for k,v in identity.items()):
        raise ValueError('Run identity mismatch')
    for k,state in [('missing','BLOCK'),('failed','CLASSIFIED'),('recovered','NO_FINDINGS'),('stale','BLOCK')]:
        v=integration['observations'][k];actual=observed[k]
        if actual!=c.classify(v['project_id'],v['job_id'],v) or actual['state']!=state:
            raise ValueError('Classification lifecycle mismatch: '+k)
    report=dict(schema='orbit.defect-classification-acceptance.v1',**identity,gate='PASS',
                policy=c.POLICY,tests=result.testsRun,observations=observed,
                integration_sha256=hashlib.sha256(raw).hexdigest(),**c.FLAGS)
    blob=json.dumps(report,sort_keys=True,separators=(',',':')).encode()
    Path(sys.argv[3]).write_bytes(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
