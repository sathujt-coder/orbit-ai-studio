"""P6.4e.6: final fail-closed byte-level validation of all defect and regression evidence."""
import hashlib
import json
import os
import sys
from pathlib import Path

FLAGS=('automatic_dispatch','execution_authorized','merge_authorized','production_approved',
       'production_release_authorized','publish_allowed','remote_writes_authorized')
# key: (artifact filename stem, producing job, job output, exact schema)
SPECS={
    'detection':('defect-detection','validate','defect_detection_sha256','automated-defect-detection-acceptance'),
    'integration':('defect-integration','requirements-browser','defect_integration_sha256','defect-detection-integration'),
    'classification':('defect-classification','requirements-browser','defect_classification_sha256','defect-classification-acceptance'),
    'severity':('severity','requirements-browser','severity_hardening_sha256','severity-hardening-acceptance'),
    'registry':('detected-registry','requirements-browser','detected_registry_sha256','detected-defect-registry-acceptance'),
    'repair':('defect-repair','requirements-browser','defect_repair_sha256','defect-repair-acceptance'),
    'positive_repair':('defect-repair-positive','requirements-browser','defect_repair_positive_sha256','defect-repair-positive-acceptance'),
    'retest':('defect-retest-quality','requirements-browser','defect_retest_quality_sha256','defect-retest-quality-acceptance'),
    'final_regression':('final-regression','requirements-browser','final_regression_evidence_sha256','final-regression-impact-acceptance'),
    'git_change':('git-change','requirements-browser','git_change_evidence_sha256','git-change-browser'),
    'dependency_impact':('dependency-impact','requirements-browser','dependency_impact_evidence_sha256','dependency-impact-browser'),
    'impacted_test':('impacted-test','requirements-browser','impacted_test_evidence_sha256','impacted-test-browser'),
    'regression_priority':('regression-priority','requirements-browser','regression_priority_evidence_sha256','regression-priority-browser'),
    'regression_gate':('regression-gate','requirements-browser','regression_gate_evidence_sha256','regression-quality-browser'),
    'final_execution':('final-execution','requirements-browser','final_execution_evidence_sha256','final-automated-test-execution'),
}
REGRESSION=('git_change','dependency_impact','impacted_test','regression_priority','regression_gate','final_execution')
DEFECT=('detection','integration','classification','severity','registry','repair','positive_repair','retest','final_regression')
LINKS=(('integration','final_regression_sha256','final_regression'),
       ('classification','integration_sha256','integration'),
       ('severity','classification_sha256','classification'),
       ('registry','severity_sha256','severity'),
       ('repair','registry_sha256','registry'),('repair','regression_sha256','final_regression'),
       ('positive_repair','repair_sha256','repair'),('retest','positive_repair_sha256','positive_repair'))
COUNTS={'detection':10,'classification':10,'severity':14,'registry':10,'repair':29}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(obj):return json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def require(condition,message):
    if not condition:raise ValueError(message)
def filename(key):return 'engineering-'+SPECS[key][0]+'-evidence.json'

def validate(directory,needs,identity):
    require(set(identity)=={'source_commit','run_id','run_attempt'} and all(isinstance(x,str) and x for x in identity.values()),'Invalid CI identity')
    docs={};hashes={}
    for key,(_,job,output,schema) in SPECS.items():
        require(needs[job]['result']=='success','Producer not successful: '+job)
        raw=(Path(directory)/filename(key)).read_bytes()
        v=json.loads(raw);h=sha(raw)
        require(h==needs[job]['outputs'][output],'Raw digest mismatch: '+key)
        require(v['schema']=='orbit.'+schema+'.v1','Schema mismatch: '+key)
        require(all(v.get(k)==x for k,x in identity.items()),'Run identity mismatch: '+key)
        if key in DEFECT:
            require(v['gate']=='PASS','Gate BLOCK: '+key)
            flags=FLAGS if key!='detection' else ('automatic_dispatch','execution_authorized','production_release_authorized')
            require(all(v.get(k) is False for k in flags),'Unexpected authorization: '+key)
        require(all(v[k] is False for k in FLAGS if k in v),'Unexpected optional authorization: '+key)
        if key in COUNTS:require(v['tests']==COUNTS[key],'Regression count mismatch: '+key)
        docs[key]=v;hashes[key]=h
    require(docs['detection']['failures']==docs['detection']['errors']==0,'Detection failures')
    for child,field,parent in LINKS:
        require(docs[child][field]==hashes[parent],'Cross-artifact binding mismatch: '+child+'.'+field)
    regression={k:hashes[k] for k in REGRESSION};chain=sha(canonical(regression))
    f=docs['final_regression']
    require(f['evidence_sha256']==regression and f['evidence_chain_sha256']==chain
            and needs['requirements-browser']['outputs']['final_regression_chain_sha256']==chain,
            'Six-artifact regression chain mismatch')
    require(f['full_regression_required'] is True and f['selective_execution_authorized'] is False,'Regression policy changed')
    o=docs['retest']['observations'];points=o['points']
    require(all(o.get(k)==v for k,v in identity.items()),'Retest observation identity mismatch')
    require(len(o['executions'])==5 and len(points)==11 and len(set(o['registrations']))==2,'Incomplete retest lifecycle')
    require(all(o[k] is True for k in ('same_run_rejected','failed_verify_rejected','stale_digest_rejected','live_unchanged')),'Retest rejection or preservation missing')
    expected={'open','recovered','first_closed','reopened','same_run_rejected','recurrence','fresh','historical_closed','both_closed','stale','final'}
    require(set(points)==expected,'Retest checkpoints mismatch')
    for k,p in points.items():
        g=p['gate'];require(g['state']==('RETEST_QUALITY_PASS' if k in ('first_closed','both_closed','final') else 'BLOCK'),'Checkpoint verdict mismatch: '+k)
        require(g['evidence_digest']==sha(canonical({a:b for a,b in g.items() if a!='evidence_digest'})),'Retest gate digest mismatch: '+k)
    require(all(x['status']=='STALE_RETEST' for x in points['stale']['gate']['items']) and len(points['stale']['gate']['items'])==2,'Stale closure missing')
    items=points['final']['tracking']['items']
    require(len(items)==2 and sorted(len(x['history']) for x in items)==[10,17] and {x['registration_digest'] for x in items}==set(o['registrations']),'Receipt inventory mismatch')
    require({x['latest'] for x in items}=={True,False},'Historical occurrence missing')
    final_execution=o['executions'][-1]['receipt']['digest']
    for item in items:
        previous=None
        for version,event in enumerate(item['history'],1):
            snap=event['snapshot']
            require(event['digest']==sha(canonical(snap)) and snap['version']==version and snap['previous_digest']==previous
                    and snap['registration_digest']==item['registration_digest'] and all(snap.get(k) is False for k in FLAGS),'Immutable repair chain mismatch')
            previous=event['digest']
        require(item['state']=='CLOSED' and item['history'][-1]['snapshot']['repair']['execution_digest']==final_execution,'Closure execution mismatch')
    g=points['final']['gate'];require(len(g['items'])==2 and all(x['status']=='CURRENT_CLOSURE' for x in g['items'])
            and g['execution_digest']==final_execution and all(x=='PASS' for x in g['checks'].values()),'Final closure not current')
    race=o['reopen_race'];require(race['action']=='REOPEN' and sorted(x['status'] for x in race['results'])==['accepted','stale']
            and race['audit_after']==race['audit_before']+1,'Concurrent REOPEN failed')
    chain_hashes={k:hashes[k] for k in DEFECT}
    return dict(schema='orbit.final-automated-defect-acceptance.v1',**identity,gate='PASS',
        evidence_sha256=chain_hashes,evidence_chain_sha256=sha(canonical(chain_hashes)),
        regression_chain_sha256=chain,regression_evidence_sha256=regression,
        coverage=dict(defect_chain_artifacts=9,regression_chain_artifacts=6,real_docker_executions=5,
                      retest_checkpoints=11,registered_occurrences=2,repair_receipts=27),
        development_scope='development_only',real_ai_acceptance='NOT_ASSESSED',model_qualification='NOT_ASSESSED',
        **dict.fromkeys(FLAGS,False))

def main():
    identity=dict(source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    report=validate(Path(sys.argv[1]),json.loads(os.environ['STUDIO_NEEDS']),identity)
    blob=canonical(report)
    with Path(sys.argv[2]).open('xb') as file:file.write(blob)
    with open(os.environ['GITHUB_OUTPUT'],'a') as file:file.write('evidence_sha256='+sha(blob)+'\n')
if __name__=='__main__':main()
