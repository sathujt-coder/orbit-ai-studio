"""Bind real Docker lifecycle detection observations to final regression evidence."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import regression_quality_gate as g

def require(ok):
    if not ok:raise ValueError('Invalid trusted detection lifecycle')

def main():
    raw=Path(sys.argv[1]).read_bytes()
    d=json.loads(raw)
    final_raw=Path(sys.argv[2]).read_bytes()
    final=json.loads(final_raw)
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(all(d[k]==final[k]==v for k,v in identity.items()) and final['gate']=='PASS')
    for k,state in [('missing','BLOCK'),('failed','DETECTED'),('recovered','NO_FINDINGS'),('stale','BLOCK')]:
        v=d[k]
        require(v['state']==state and g.mapping.digest_ok(v) and all(v[x] is False for x in g.FLAGS))
        if k in ('failed','recovered'):
            receipt=final['lifecycle']['history'][k]['execution_history'][-1]
            require(v['receipt_digest']==receipt['digest'])
            failed=[x for x in receipt['snapshot']['report']['results'] if x['status']=='FAIL']
            require(len(v['findings'])==len(failed))
            for finding,row in zip(v['findings'],failed):
                require(finding['kind']=='ASSERTION_MISMATCH' and finding['case_id']==row['case_id'] and finding['receipt_digest']==receipt['digest'])
        else:
            require(not v['findings'] and v['receipt_digest'] is None)
    out=dict(schema='orbit.defect-detection-integration.v1',**identity,gate='PASS',observations=d,
             final_regression_sha256=hashlib.sha256(final_raw).hexdigest(),**g.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    Path(sys.argv[3]).write_bytes(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
