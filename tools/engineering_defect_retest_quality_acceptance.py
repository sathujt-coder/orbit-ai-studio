"""Mandatory independent validation of trusted retest observations and receipts."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import defect_retest_quality as q
t=q.repair

def require(ok):
    if not ok:raise ValueError('Invalid trusted retest lifecycle evidence')
def sealed(v):
    return v['evidence_digest']==t.pp.digest({k:x for k,x in v.items() if k!='evidence_digest'})
def main():
    raw=Path(sys.argv[1]).read_bytes();prior=json.loads(raw)
    v=json.loads(Path(sys.argv[2]).read_bytes())
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    require(prior['gate']=='PASS' and all(v[k]==prior[k]==x for k,x in identity.items()))
    require(all(v[k] is True for k in ('same_run_rejected','failed_verify_rejected','stale_digest_rejected','live_unchanged')))
    pid,jid=v['project_id'],v['job_id'];r1,r2=v['registrations'];require(r1!=r2)
    executions=v['executions'];require(len(executions)==5)
    previous=None;source=executions[0]['report']['source'];assertions=None
    for i,r in enumerate(executions):
        report=r['report'];receipt=r['receipt'];s=receipt['snapshot'];priority=r['priority_receipt']
        require(r['digest']==t.pp.digest(report)==s['report_digest'] and receipt['digest']==t.pp.digest(s)
            and s['report']==report and priority['digest']==t.pp.digest(priority['snapshot']))
        require(report['source']==source and (source['project_id'],source['job_id'])==(pid,jid)
            and report['runtime']=='docker' and report['network']=='none' and report['workspace']=='read-only'
            and report['image']==os.environ['ORBIT_SANDBOX_PYTHON_IMAGE'] and all(report[k] is False and s[k] is False for k in t.FLAGS))
        require(report['case_count']==3==r['priority']['schedule']['required_count']
            and r['priority']['unattempted_order']==[] and r['priority']['attempted_order']==r['priority']['schedule']['execution_order'])
        keys=[(x['case_id'],x['assertion_digest']) for x in report['results']]
        if assertions is None:assertions=keys
        require(keys==assertions)
        if previous:require(s['previous_digest']==previous['digest'] and s['version']==previous['snapshot']['version']+1)
        previous=receipt
        if i in (0,2):
            errors=[x for x in report['results'] if x['status']!='PASS']
            require(report['gate']=='BLOCK' and len(errors)==1 and errors[0]['status']=='ERROR' and errors[0]['reason']=='TIMEOUT')
        else:require(report['gate']=='PASS' and all(x['status']=='PASS' and x['executed'] is True for x in report['results']))
    points=v['points'];expected={'open':0,'recovered':1,'first_closed':1,'reopened':1,'same_run_rejected':1,
        'recurrence':2,'fresh':3,'historical_closed':3,'both_closed':3,'stale':4,'final':4}
    require(set(points)==set(expected))
    passing={'first_closed','both_closed','final'}
    final=points['final'];chains={x['registration_digest']:x['history'] for x in final['tracking']['items']}
    require(set(chains)=={r1,r2})
    for key,i in expected.items():
        x=points[key];tracking=x['tracking'];g=x['gate']
        require(all(sealed(z) for z in (tracking,x['detection'],x['regression'],g)) and x['receipt']==executions[i]['receipt'])
        require(g==q.evaluate(pid,jid,tracking,x['detection'],x['regression'],x['registrations'],x['receipt']))
        require(g['state']==('RETEST_QUALITY_PASS' if key in passing else 'BLOCK'))
        require(all(g[k] is False for k in t.FLAGS) and g['automatic_closure'] is False and g['quality_gate_override'] is False)
        require({z['registration_digest'] for z in tracking['items']}==({r1} if i<2 else {r1,r2}))
        for item in tracking['items']:
            rd=item['registration_digest'];require(item['history']==chains[rd][:len(item['history'])])
    regs=[x for chain in final['registrations'].values() for x in chain];require(len(regs)==2)
    require(regs[0]['digest']==r1 and regs[1]['digest']==r2 and regs[1]['snapshot']['previous_digest']==r1)
    require(regs[0]['snapshot']['finding_id']==regs[1]['snapshot']['finding_id'])
    for j,reg in zip((0,2),regs):
        s=reg['snapshot'];require(reg['digest']==t.pp.digest(s) and s['execution_digest']==executions[j]['receipt']['digest'])
        require(all(s[k] is False for k in t.FLAGS))
        error=next(x for x in executions[j]['report']['results'] if x['status']!='PASS')
        require(s['finding']['case_id']==error['case_id'] and s['finding']['assertion_digest']==error['assertion_digest'])
    actions={r1:['ASSIGN','START','SUBMIT','VERIFY','CLOSE','REOPEN','START','SUBMIT','REJECT','SUBMIT','VERIFY','CLOSE','REOPEN','START','SUBMIT','VERIFY','CLOSE'],
             r2:['ASSIGN','START','SUBMIT','VERIFY','CLOSE','REOPEN','START','SUBMIT','VERIFY','CLOSE']}
    for rd,chain in chains.items():
        require([x['snapshot']['action'] for x in chain]==actions[rd])
        for n,event in enumerate(chain):
            e=event['snapshot'];require(event['digest']==t.pp.digest(e) and e['version']==n+1 and e['registration_digest']==rd
                and e['previous_digest']==(chain[n-1]['digest'] if n else None) and all(e[k] is False for k in t.FLAGS))
            if e['action']=='CLOSE':
                require(e['actor']!=e['assignee'] and e['actor']!=chain[n-1]['snapshot']['actor']
                    and chain[n-1]['snapshot']['actor']!=e['assignee'] and e['repair']==chain[n-1]['snapshot']['repair'])
        require(chain[-1]['snapshot']['repair']['execution_digest']==executions[-1]['receipt']['digest'])
    require(points['reopened']['tracking']['items'][0]['history']==points['first_closed']['tracking']['items'][0]['history']+[chains[r1][5]])
    require(points['same_run_rejected']['tracking']['items'][0]['history']==chains[r1][:7])
    require(all(x['status']=='STALE_RETEST' for x in points['stale']['gate']['items']))
    require(all(x['status']=='CURRENT_CLOSURE' for x in final['gate']['items']))
    require(next(x for x in final['tracking']['items'] if x['registration_digest']==r1)['latest'] is False)
    race=v['reopen_race'];require(race['action']=='REOPEN' and race['expected_digest']==points['first_closed']['tracking']['evidence_digest']
        and race['audit_after']==race['audit_before']+1 and sorted(x['status'] for x in race['results'])==['accepted','stale']
        and next(x['receipt'] for x in race['results'] if x['status']=='accepted')==chains[r1][5])
    out=dict(schema='orbit.defect-retest-quality-acceptance.v1',**identity,gate='PASS',
        positive_repair_sha256=hashlib.sha256(raw).hexdigest(),observations=v,**t.FLAGS)
    blob=json.dumps(out,sort_keys=True,separators=(',',':')).encode()
    with Path(sys.argv[3]).open('xb') as file:file.write(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:file.write('evidence_sha256='+hashlib.sha256(blob).hexdigest()+'\n')
if __name__=='__main__':main()
