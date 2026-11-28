"""P6.4e.5a: read-only exact current retest/closure evidence. No authority."""
import sqlite3
import defect_repair_tracking as repair

FLAGS=repair.FLAGS
pp=repair.pp
CHECKS=('repair_tracking','mandatory_regression','current_detection','explicit_closure')

def evaluate(pid,jid,tracking,detection,regression,registrations,receipt):
    checks={k:'BLOCK' for k in CHECKS}
    out=dict(schema='orbit.defect-retest-quality.v1',project_id=pid,job_id=jid,state='BLOCK',
             checks=checks,items=[],repair_digest=None,regression_digest=None,execution_digest=None,
             automatic_closure=False,quality_gate_override=False,**FLAGS)
    try:
        for v in (tracking,detection,regression):
            if ((v['project_id'],v['job_id'])!=(pid,jid) or any(v.get(k) is not False for k in FLAGS)
                or v['evidence_digest']!=pp.digest({k:x for k,x in v.items() if k!='evidence_digest'})):
                raise ValueError('Invalid retest evidence')
        out.update(repair_digest=tracking['evidence_digest'],regression_digest=regression['evidence_digest'])
        if tracking['state']!='READY' or tracking['quality_gate_override'] is not False or tracking['automatic_closure'] is not False:
            raise ValueError('Current tracking required')
        if tracking['current_execution']!=detection['receipt_digest'] or detection['regression_digest']!=regression['evidence_digest']:
            raise ValueError('Retest source mismatch')
        checks['repair_tracking']='PASS'
        if (regression['state']=='REGRESSION_QUALITY_PASS' and regression['checks']
            and all(x=='PASS' for x in regression['checks'].values())
            and regression['full_regression_required'] is True and regression['selective_execution_authorized'] is False):
            checks['mandatory_regression']='PASS'
        if detection['state']=='NO_FINDINGS' and detection['findings']==[] and tracking['registry_state']=='NO_CURRENT_FINDINGS':
            checks['current_detection']='PASS'
        if not receipt or receipt['digest']!=detection['receipt_digest'] or receipt['digest']!=regression['receipts']['execution']:
            raise ValueError('Current execution receipt required')
        snap=receipt['snapshot']; report=snap['report']
        if (receipt['digest']!=pp.digest(snap) or snap['report_digest']!=pp.digest(report)
            or (snap['project_id'],snap['job_id'])!=(pid,jid)
            or (report['source']['project_id'],report['source']['job_id'])!=(pid,jid)
            or any(report.get(k) is not False or snap.get(k) is not False for k in FLAGS)):
            raise ValueError('Invalid execution binding')
        out['execution_digest']=receipt['digest']
        expected=dict(execution_digest=receipt['digest'],candidate_digest=report['source']['candidate_digest'],
                      regression_digest=regression['evidence_digest'])
        by_digest={r['digest']:r['snapshot'] for chain in registrations.values() for r in chain}
        if len(by_digest)!=len(tracking['items']) or len({x['registration_digest'] for x in tracking['items']})!=len(by_digest):
            raise ValueError('Incomplete registry inventory')
        for item in tracking['items']:
            rd=item['registration_digest']; original=by_digest[rd]
            if original['finding_id']!=item['finding_id'] or original['classification']['severity']!=item['severity']:
                raise ValueError('Registration binding mismatch')
            status='UNRESOLVED'; events=item['history']
            if item['state']=='CLOSED' and events:
                close=events[-1]['snapshot']
                status='STALE_RETEST'
                if (close['action']=='CLOSE' and close['repair']==expected and
                    receipt['digest']!=original['execution_digest'] and report['gate']=='PASS'
                    and checks['mandatory_regression']==checks['current_detection']=='PASS'
                    and any(x['case_id']==original['finding']['case_id'] and
                            x['assertion_digest']==original['finding']['assertion_digest'] and
                            x['status']=='PASS' and x['executed'] is True for x in report['results'])):
                    status='CURRENT_CLOSURE'
            out['items'].append(dict(finding_id=item['finding_id'],registration_digest=rd,
                latest=item['latest'],severity=item['severity'],repair_state=item['state'],status=status,
                closure_digest=events[-1]['digest'] if item['state']=='CLOSED' and events else None))
        # Conservative initial policy: every registered occurrence is visible and
        # unresolved historical occurrences also block; never infer closure.
        if all(x['status']=='CURRENT_CLOSURE' for x in out['items']):
            checks['explicit_closure']='PASS'
        if all(x=='PASS' for x in checks.values()):out['state']='RETEST_QUALITY_PASS'
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,sqlite3.Error,PermissionError,OSError):
        checks['explicit_closure']='BLOCK'
    out['evidence_digest']=pp.digest(out)
    return out

def view(c,db,pid,jid):
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    try:
        v,d=repair._snapshot(c,db,pid,jid)
        if d is None:return evaluate(pid,jid,v,{}, {},{},None)
        g=repair.regression.view(c,db,pid,jid)
        registrations=repair.registry.history(c,pid,jid)
        runs=repair.runs.history(c,pid,jid)
        return evaluate(pid,jid,v,d,g,registrations,runs[-1] if runs else None)
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,sqlite3.Error,PermissionError,OSError):
        return evaluate(pid,jid,{}, {}, {},{},None)

def require_current(c,db,pid,jid,expected_digest):
    v=view(c,db,pid,jid)
    if v['state']!='RETEST_QUALITY_PASS' or v['evidence_digest']!=expected_digest:
        raise ValueError('Current defect retest quality gate required')
    return v
