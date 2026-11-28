"""Bind HTTP repair lifecycle to real Docker registry and regression artifacts."""
import hashlib,json,os,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(root/'tests')]
import defect_repair_tracking as t
from test_defect_repair_tracking import RepairTrackingTests

def require(ok):
    if not ok:raise ValueError('Invalid repair tracking lifecycle')
def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RepairTrackingTests))
    require(result.wasSuccessful() and result.testsRun==18 and not result.skipped)
    raw=Path(sys.argv[1]).read_bytes();prior=json.loads(raw)
    regression_raw=Path(sys.argv[2]).read_bytes();reg=json.loads(regression_raw)
    v=json.loads(Path(sys.argv[3]).read_bytes())
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(prior['gate']=='PASS' and reg['gate']=='PASS' and all(prior[k]==reg[k]==v[k]==x for k,x in identity.items()))
    original=prior['observations']['registered']['history'][0]
    states={'open':'OPEN','assigned':'ASSIGNED','started':'IN_PROGRESS','recovered':'IN_PROGRESS',
            'submitted':'REPAIR_SUBMITTED','rejected':'IN_PROGRESS','stale':'IN_PROGRESS'}
    for key,state in states.items():
        x=v[key]
        require(x['state']==('BLOCK' if key=='stale' else 'READY') and len(x['items'])==1)
        require(x['evidence_digest']==t.pp.digest({a:b for a,b in x.items() if a!='evidence_digest'}))
        require(x['automatic_closure'] is False and x['quality_gate_override'] is False and all(x[f] is False for f in t.FLAGS))
        item=x['items'][0]
        require(item['state']==state and item['registration_digest']==original['digest'] and item['severity']==original['snapshot']['classification']['severity'])
        for i,event in enumerate(item['history']):
            e=event['snapshot']
            require(e['version']==i+1 and event['digest']==t.pp.digest(e) and e['previous_digest']==(item['history'][i-1]['digest'] if i else None))
    require(v['started']['items']==v['recovered']['items'] and v['rejected']['items']==v['stale']['items'])
    require([e['snapshot']['action'] for e in v['rejected']['items'][0]['history']]==['ASSIGN','START','SUBMIT','REJECT'])
    repair=v['submitted']['items'][0]['history'][-1]['snapshot']['repair']
    require(repair['execution_digest']==v['recovered']['current_execution'])
    require(repair['candidate_digest']==reg['candidate_digest'] and repair['regression_digest']==reg['regression_gate_digest'])
    require(v['recovered']['registry_digest']==prior['observations']['recovered']['evidence_digest'])
    require(all(v[k] is True for k in ('original_assertion_change_rejected','duplicate_rejected','viewer_mutation_rejected','early_submission_rejected')))
    out=dict(schema='orbit.defect-repair-acceptance.v1',**identity,gate='PASS',tests=result.testsRun,
             registry_sha256=hashlib.sha256(raw).hexdigest(),regression_sha256=hashlib.sha256(regression_raw).hexdigest(),observations=v,**t.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    with Path(sys.argv[4]).open('xb') as f:f.write(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
