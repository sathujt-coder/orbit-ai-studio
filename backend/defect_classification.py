"""Versioned, deterministic triage of current trusted detection evidence.

Severity is a conservative triage priority, not proof of business impact.
No persistence, dispatch, closure, or authorization is performed here.
"""
import automated_defect_detection as detection
import engineering_assertion_registry as registry
import project_planning as pp

POLICY='orbit.defect-severity-policy.v1'
FLAGS=detection.FLAGS

def classify(pid,jid,v):
    out=dict(schema='orbit.defect-classification.v1',policy=POLICY,project_id=pid,
             job_id=jid,state='BLOCK',items=[],detection_digest=None,**FLAGS)
    try:
        if (v['schema']!='orbit.automated-defect-detection.v1'
            or (v['project_id'],v['job_id'])!=(pid,jid)
            or any(v.get(k) is not False for k in FLAGS)
            or v['evidence_digest']!=pp.digest({k:x for k,x in v.items() if k!='evidence_digest'})
            or v['state'] not in ('DETECTED','NO_FINDINGS')
            or v['reason'] is not None
            or not all(registry.hex_digest(v[k]) for k in ('receipt_digest','regression_digest'))
            or type(v['findings']) is not list
            or bool(v['findings'])!=(v['state']=='DETECTED')):
            raise ValueError('Current detection evidence required')
        items=[];seen=set()
        for f in v['findings']:
            identity={k:f[k] for k in ('project_id','job_id','case_id','assertion_digest','kind')}
            if (f['project_id'],f['job_id'])!=(pid,jid) or f['receipt_digest']!=v['receipt_digest']:
                raise ValueError('Finding scope mismatch')
            if (not isinstance(f['case_id'],str) or not f['case_id']
                or not all(registry.hex_digest(f[k]) for k in ('assertion_digest','module_sha256'))
                or f['finding_id']!=pp.digest(identity) or f['finding_id'] in seen):
                raise ValueError('Invalid finding identity')
            seen.add(f['finding_id'])
            kind,reason=f['kind'],f['reason']
            if kind=='ASSERTION_MISMATCH' and reason=='ASSERTION_MISMATCH':
                category,severity,domain='FUNCTIONAL','HIGH','PRODUCT'
            elif kind=='EXECUTION_ERROR' and reason in registry.ERRORS:
                category,severity,domain='TEST','HIGH','EXECUTION'
            elif kind=='MISSING_EXECUTION' and reason=='TOTAL_TIMEOUT':
                category,severity,domain='TEST','HIGH','COVERAGE'
            else:
                raise ValueError('Unsupported finding reason')
            items.append(dict(finding_id=f['finding_id'],category=category,severity=severity,
                              domain=domain,reason=reason,receipt_digest=f['receipt_digest'],
                              finding_digest=pp.digest(f),impact_confirmed=False))
        out.update(state='CLASSIFIED' if items else 'NO_FINDINGS',items=items,
                   detection_digest=v['evidence_digest'])
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,RecursionError):
        pass
    out['evidence_digest']=pp.digest(out)
    return out

def view(c,db,pid,jid):
    return classify(pid,jid,detection.view(c,db,pid,jid))
