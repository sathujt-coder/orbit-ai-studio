"""Independent verification of real Docker same-assertion recovery and concurrent writers."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import defect_repair_tracking as t

def require(ok):
    if not ok:raise ValueError('Invalid positive repair evidence')

def main():
    raw=Path(sys.argv[1]).read_bytes();base=json.loads(raw)
    v=json.loads(Path(sys.argv[2]).read_bytes())
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(base['gate']=='PASS' and all(base[k]==v[k]==x for k,x in identity.items()))
    require(v['live_unchanged'] is True and v['same_reviewer_rejected'] is True)
    rd=v['registration_digest'];reg=v['registration'];original=reg['snapshot']
    require(reg['digest']==rd==t.pp.digest(original) and original['state']=='OPEN' and original['finding']['kind']=='EXECUTION_ERROR')
    f=v['failed_run'];p=v['recovered_run'];g=v['final_gate']
    for r in (f,p):
        report=r['report'];receipt=r['receipt'];priority=r['priority_receipt']
        require(r['digest']==t.pp.digest(report) and receipt['digest']==t.pp.digest(receipt['snapshot'])
            and receipt['snapshot']['report']==report and priority['digest']==t.pp.digest(priority['snapshot']))
        require(report['runtime']=='docker' and report['network']=='none' and report['workspace']=='read-only'
            and report['image']==os.environ['ORBIT_SANDBOX_PYTHON_IMAGE'] and all(report[k] is False for k in t.FLAGS))
        require(r['priority']['schedule']['required_count']==report['case_count']==3 and r['priority']['unattempted_order']==[]
            and r['priority']['attempted_order']==r['priority']['schedule']['execution_order'])
    require(f['report']['source']==p['report']['source'] and f['report']['gate']=='BLOCK' and p['report']['gate']=='PASS')
    require(f['receipt']['snapshot']['version']+1==p['receipt']['snapshot']['version']
        and p['receipt']['snapshot']['previous_digest']==f['receipt']['digest']==original['execution_digest'])
    errors=[x for x in f['report']['results'] if x['status']!='PASS']
    require(len(errors)==1 and errors[0]['reason']=='TIMEOUT' and errors[0]['status']=='ERROR'
        and errors[0]['assertion_digest']==original['finding']['assertion_digest'] and errors[0]['case_id']==original['finding']['case_id'])
    require(all(x['status']=='PASS' and x['executed'] is True for x in p['report']['results']))
    require([(x['case_id'],x['assertion_digest']) for x in f['report']['results']]==[(x['case_id'],x['assertion_digest']) for x in p['report']['results']])
    require(g['state']=='REGRESSION_QUALITY_PASS' and all(x=='PASS' for x in g['checks'].values())
        and g['receipts']['execution']==p['receipt']['digest'] and g['evidence_digest']==t.pp.digest({k:x for k,x in g.items() if k!='evidence_digest'}))
    states={'opened':'OPEN','assigned':'ASSIGNED','started':'IN_PROGRESS','recovered_view':'IN_PROGRESS',
            'submitted':'REPAIR_SUBMITTED','verified':'VERIFIED','closed':'CLOSED'}
    def item(key):return next(x for x in v[key]['items'] if x['registration_digest']==rd)
    chain=item('closed')['history']
    require([x['snapshot']['action'] for x in chain]==['ASSIGN','START','SUBMIT','VERIFY','CLOSE'])
    for key,state in states.items():
        x=v[key];i=item(key)
        require(x['state']=='READY' and x['evidence_digest']==t.pp.digest({k:y for k,y in x.items() if k!='evidence_digest'})
            and all(x[k] is False for k in t.FLAGS) and x['automatic_closure'] is False and x['quality_gate_override'] is False)
        require(i['state']==state and i['history']==chain[:len(i['history'])])
    require(v['started']['items']==v['recovered_view']['items'])
    for n,event in enumerate(chain):
        e=event['snapshot'];require(event['digest']==t.pp.digest(e) and e['version']==n+1
            and e['previous_digest']==(chain[n-1]['digest'] if n else None) and e['registration_digest']==rd
            and all(e[k] is False for k in t.FLAGS))
    require(chain[3]['snapshot']['actor']!=chain[4]['snapshot']['actor'] and chain[3]['snapshot']['actor']!=chain[2]['snapshot']['actor']
        and chain[4]['snapshot']['actor']!=chain[2]['snapshot']['actor'])
    evidence=dict(execution_digest=p['receipt']['digest'],candidate_digest=p['report']['source']['candidate_digest'],regression_digest=g['evidence_digest'])
    require(all(x['snapshot']['repair']==evidence for x in chain[2:]))
    require([x['action'] for x in v['races']]==['ASSIGN','SUBMIT','CLOSE'])
    for race,index,key in zip(v['races'],(0,2,4),('opened','recovered_view','verified')):
        require(race['expected_digest']==v[key]['evidence_digest'] and race['audit_after']==race['audit_before']+1
            and sorted(x['status'] for x in race['results'])==['accepted','stale']
            and next(x['receipt'] for x in race['results'] if x['status']=='accepted')==chain[index])
    out=dict(schema='orbit.defect-repair-positive-acceptance.v1',**identity,gate='PASS',
        repair_sha256=hashlib.sha256(raw).hexdigest(),observations=v,**t.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    with Path(sys.argv[3]).open('xb') as file:file.write(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:file.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
