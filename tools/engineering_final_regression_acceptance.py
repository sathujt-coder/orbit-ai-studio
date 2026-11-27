"""Final P6.4d acceptance: verify lifecycle and bind the entire evidence chain."""
import hashlib,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import regression_quality_gate as g

NAMES=('git_change','dependency_impact','impacted_test','regression_priority','regression_gate','final_execution')
REJECTIONS=('missing_rejected','failed_rejected','before_recovery_rejected','old_digest_rejected',
            'stale_pass_digest_rejected','stale_current_digest_rejected')

def require(ok,message):
    if not ok:raise ValueError(message)

def validate_lifecycle(d,gate,final):
    require(d['schema']=='orbit.final-regression-lifecycle.v1','Invalid lifecycle schema')
    h=d['history'];guard=d['guard']
    require(set(h)=={'missing','failed','recovered','stale'},'Incomplete history observations')
    require(set(guard)==set(REJECTIONS)|{'recovered'} and all(guard[k] is True for k in REJECTIONS),
            'Missing guard rejection')
    require(guard['recovered']==gate['recovered'] and guard['recovered']['state']=='REGRESSION_QUALITY_PASS',
            'Recovered guard mismatch')
    require(all(gate[k]['state']=='BLOCK' for k in ('missing','failed','before_recovery','stale')),
            'Regression gate failed open')
    for k in ('missing','failed','before_recovery','recovered','stale'):
        v=gate[k]
        require(g.mapping.digest_ok(v) and v['full_regression_required'] is True
                and v['selective_execution_authorized'] is False and all(v[x] is False for x in g.FLAGS),
                'Invalid gate digest or authority')
    failed=final['failed'];recovered=final['recovered']
    chain=recovered['registry']['history']
    require(len(chain)==4 and failed['registry']['history']==chain[:3] and final['stale']['registry']['history']==chain,
            'Execution history mismatch')
    f=failed['result']['priority_receipt'];r=recovered['result']['priority_receipt']
    for k,version,receipts in (('missing',2,[]),('failed',3,[f]),('recovered',4,[f,r]),('stale',4,[f,r])):
        v=h[k]
        require(v==dict(execution_history=chain[:version],priority_history=receipts,priority_audit_count=len(receipts)),
                'Durable history or audit mismatch: '+k)
    require(h['stale']==h['recovered'],'History changed after invalidation')
    for k,step,receipt,version,state in (('failed',failed,f,3,'BLOCK'),('recovered',recovered,r,4,'PASS')):
        s=receipt['snapshot'];report=step['result']['report']
        require(receipt==gate[k]['priority_receipt'] and receipt['digest']==g.pp.digest(s)
                and s['execution_version']==version and s['execution_receipt_digest']==chain[version-1]['digest']
                and s['report_digest']==g.pp.digest(report)==chain[version-1]['snapshot']['report_digest']
                and s['priority_digest']==g.pp.digest(s['priority']) and s['priority']['gate']==state
                and all(s[x] is False for x in g.FLAGS),'Invalid durable priority binding')
        require(report['gate']==state and report['executed_count']==report['case_count']==3
                and s['priority']['attempted_order']==s['priority']['schedule']['execution_order']
                and s['priority']['unattempted_order']==[],'Incomplete mandatory regression')
    require(gate['missing']['checks']['execution_quality']=='PASS'
            and gate['missing']['checks']['durable_priority_receipt']=='BLOCK'
            and gate['failed']['checks']['durable_priority_receipt']=='PASS'
            and gate['failed']['checks']['mandatory_regression']=='BLOCK'
            and all(v=='PASS' for v in gate['recovered']['checks'].values())
            and set(gate['recovered']['checks'])==set(g.CHECKS)
            and gate['stale']['priority_receipt'] is None,'Invalid regression gate lifecycle')

def chain_digest(hashes):
    require(set(hashes)==set(NAMES) and all(g.registry.hex_digest(v) for v in hashes.values()),'Incomplete evidence chain')
    return hashlib.sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def build(d,artifacts,hashes,identity):
    require(set(artifacts)==set(NAMES),'Incomplete evidence artifacts')
    for x in (d,*artifacts.values()):
        require(all(x[k]==v for k,v in identity.items()),'Evidence run identity mismatch')
    git,impact,mapping,priority,gate,final=[artifacts[k] for k in NAMES]
    validate_lifecycle(d,gate,final)
    gv=git['current'];iv=impact['current'];mv=mapping['recovered'];rv=gate['recovered']
    report=final['recovered']['result']['report']
    require(gv['state']=='GIT_CHANGE_EVIDENCE_READY' and iv['state']=='DEPENDENCY_IMPACT_READY'
            and mv['state']=='IMPACTED_TEST_MAPPING_READY' and all(g.mapping.digest_ok(v) for v in (gv,iv,mv)),
            'Invalid impact chain state')
    require(iv['source']['git_change_evidence_digest']==gv['evidence_digest']
            and iv['source']['git_source']==gv['source']
            and mv['source']['impact_evidence_digest']==iv['evidence_digest']
            and mv['source']['runner_source']==report['source']
            and rv['receipts']['mapping']==mv['evidence_digest']
            and rv['receipts']['report']==g.pp.digest(report),'Cross-stage evidence mismatch')
    require(all(x['stale']['state']=='BLOCK' for x in (git,impact,mapping,gate)),'Stale stage accepted')
    require(set(priority['runs'])=={'baseline_to_B','A_to_B'},'Incomplete real priority probes')
    for name,result in priority['runs'].items():
        trace=result['priority'];schedule=trace['schedule']
        require(result['report']==report and result['digest']==g.pp.digest(report)
                and result['priority_digest']==g.pp.digest(trace)
                and schedule['mapping_digest']==mv['evidence_digest'] and schedule['comparison']==name
                and schedule['required_count']==3 and schedule['impacted_count']==(3 if name=='baseline_to_B' else 0)
                and trace['attempted_order']==schedule['execution_order'] and trace['unattempted_order']==[]
                and trace['gate']=='PASS' and trace['full_regression_required'] is True
                and trace['selective_execution_authorized'] is False,'Incomplete prioritized regression proof')
    require(all(x['required_count']==3 and all(row['required'] is True for row in x['cases'])
                for x in mv['mappings'].values()),'Mandatory tests waived')
    return dict(schema='orbit.final-regression-impact-acceptance.v1',**identity,gate='PASS',
                evidence_sha256=hashes,evidence_chain_sha256=chain_digest(hashes),lifecycle=d,
                selected_candidate=report['source']['selected'],candidate_digest=report['source']['candidate_digest'],
                regression_gate_digest=rv['evidence_digest'],coverage=rv['coverage'],
                full_regression_required=True,selective_execution_authorized=False,**g.FLAGS)

def main():
    if len(sys.argv)!=9:raise ValueError('Expected lifecycle, output and six artifacts')
    d=json.loads(Path(sys.argv[1]).read_bytes())
    blobs={k:Path(p).read_bytes() for k,p in zip(NAMES,sys.argv[3:])}
    hashes={k:hashlib.sha256(v).hexdigest() for k,v in blobs.items()}
    identity={k:os.environ[v] for k,v in (('source_commit','GITHUB_SHA'),('run_id','GITHUB_RUN_ID'),('run_attempt','GITHUB_RUN_ATTEMPT'))}
    require(all(identity.values()),'Missing run identity')
    result=build(d,{k:json.loads(v) for k,v in blobs.items()},hashes,identity)
    out=Path(sys.argv[2])
    with out.open('x') as f:json.dump(result,f,sort_keys=True,separators=(',',':'))
    digest=hashlib.sha256(out.read_bytes()).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        f.write('evidence_sha256='+digest+'\nchain_sha256='+result['evidence_chain_sha256']+'\n')
    print('P6.4d.6 final regression impact acceptance PASS; sha256='+digest)
if __name__=='__main__':main()
