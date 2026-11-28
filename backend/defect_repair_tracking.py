"""P6.4e.4: append-only, audited defect repair tracking. No execution authority."""
import json
import sqlite3
import detected_defect_registry as registry
import engineering_assertion_registry as runs
import regression_quality_gate as regression
import project_planning as pp

FLAGS=registry.FLAGS
SCHEMA='orbit.defect-repair-receipt.v1'
TRANSITIONS={
    ('OPEN','ASSIGN'):'ASSIGNED', ('ASSIGNED','REASSIGN'):'ASSIGNED',
    ('IN_PROGRESS','REASSIGN'):'ASSIGNED', ('ASSIGNED','START'):'IN_PROGRESS',
    ('IN_PROGRESS','SUBMIT'):'REPAIR_SUBMITTED', ('REPAIR_SUBMITTED','REJECT'):'IN_PROGRESS',
    ('REPAIR_SUBMITTED','VERIFY'):'VERIFIED', ('VERIFIED','CLOSE'):'CLOSED',
    ('VERIFIED','REJECT'):'IN_PROGRESS',
}
REVIEW={'ASSIGN','REASSIGN','REJECT','VERIFY','CLOSE'}
def permission(action):
    if not isinstance(action,str) or action not in {a for _,a in TRANSITIONS}:
        raise ValueError('Unknown repair action')
    return 'approve' if action in REVIEW else 'write'

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_defect_repair_events(
        project_id TEXT NOT NULL,job_id TEXT NOT NULL,finding_id TEXT NOT NULL,
        registration_digest TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),
        snapshot TEXT NOT NULL,digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,finding_id,registration_digest,version), UNIQUE(digest))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS defect_repair_no_{op.lower()}
          BEFORE {op} ON engineering_defect_repair_events
          BEGIN SELECT RAISE(ABORT,'Immutable repair receipt'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS defect_repair_no_replace
      BEFORE INSERT ON engineering_defect_repair_events WHEN EXISTS(
        SELECT 1 FROM engineering_defect_repair_events WHERE digest=NEW.digest OR
        (project_id=NEW.project_id AND job_id=NEW.job_id AND finding_id=NEW.finding_id
        AND registration_digest=NEW.registration_digest AND version=NEW.version))
      BEGIN SELECT RAISE(ABORT,'Duplicate repair receipt'); END""")

def history(c,pid,jid,registered):
    bindings={x['digest']:x['snapshot'] for chain in registered.values() for x in chain}
    result={}
    for row in c.execute("""SELECT finding_id,registration_digest,version,snapshot,digest
        FROM engineering_defect_repair_events WHERE project_id=? AND job_id=?
        ORDER BY registration_digest,version""",(pid,jid)):
        did,rd,version,raw,digest=tuple(row)
        e=json.loads(raw); chain=result.setdefault(rd,[])
        prev=chain[-1]['snapshot'] if chain else None
        state=prev['state'] if prev else 'OPEN'
        if (rd not in bindings or bindings[rd]['finding_id']!=did
            or e['schema']!=SCHEMA or (e['project_id'],e['job_id'],e['finding_id'],e['registration_digest'])!=(pid,jid,did,rd)
            or e['version']!=version or type(e['version']) is not int or version!=len(chain)+1
            or e['previous_digest']!=(chain[-1]['digest'] if chain else None)
            or pp.digest(e)!=digest or TRANSITIONS.get((state,e['action']))!=e['state']
            or e['severity']!=bindings[rd]['classification']['severity']
            or any(e.get(k) is not False for k in FLAGS)
            or not isinstance(e['actor'],str) or not e['actor']
            or not isinstance(e['assignee'],str) or not e['assignee']
            or not isinstance(e['note'],str) or not 1<=len(e['note'])<=1000
            or not isinstance(e['created_at'],str) or not e['created_at']):
            raise ValueError('Invalid repair history')
        action=e['action']
        if action not in ('ASSIGN','REASSIGN') and (not prev or e['assignee']!=prev['assignee']):
            raise ValueError('Assignee binding mismatch')
        if action in ('START','SUBMIT') and e['actor']!=e['assignee']:
            raise ValueError('Repair actor mismatch')
        if action in REVIEW and e['actor']==e['assignee']:
            raise ValueError('Independent actor required')
        if action=='CLOSE' and e['actor']==prev['actor']:
            raise ValueError('Independent closure reviewer required')
        if action=='SUBMIT':
            if (not isinstance(e['repair'],dict) or set(e['repair'])!={'execution_digest','candidate_digest','regression_digest'}
                or not all(runs.hex_digest(x) for x in e['repair'].values())
                or e['repair']['execution_digest']==bindings[rd]['execution_digest']):
                raise ValueError('Invalid repair evidence')
        elif action in ('VERIFY','CLOSE','REJECT'):
            if not prev or e['repair']!=prev['repair']:
                raise ValueError('Repair evidence changed')
        elif e['repair'] is not None:raise ValueError('Unexpected repair evidence')
        chain.append(dict(snapshot=e,digest=digest))
    return result

def view(c,db,pid,jid):
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    out=dict(schema='orbit.defect-repair-tracking.v1',project_id=pid,job_id=jid,state='BLOCK',
             registry_digest=None,registry_state='BLOCK',items=[],current_execution=None,
             automatic_closure=False,quality_gate_override=False,**FLAGS)
    try:
        registered=registry.history(c,pid,jid); events=history(c,pid,jid,registered)
        for did,chain in sorted(registered.items()):
            for x in chain:
                rd=x['digest']; ev=events.get(rd,[]); last=ev[-1]['snapshot'] if ev else None
                out['items'].append(dict(finding_id=did,registration_digest=rd,latest=x==chain[-1],
                    severity=x['snapshot']['classification']['severity'],state=last['state'] if last else 'OPEN',
                    assignee=last['assignee'] if last else None,history=ev))
        v=registry.view(c,db,pid,jid)
        out.update(registry_digest=v['evidence_digest'],registry_state=v['state'])
        if v['state'] not in ('REGISTERED','NO_CURRENT_FINDINGS'):raise ValueError('Registry not current')
        d,_=registry.current(c,db,pid,jid)
        out.update(state='READY',current_execution=d['receipt_digest'])
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,sqlite3.Error,PermissionError,OSError):
        pass
    out['evidence_digest']=pp.digest(out)
    return out

def repair_evidence(c,db,pid,jid,original,*,verify=False):
    d,_=registry.current(c,db,pid,jid)
    g=regression.view(c,db,pid,jid)
    run=runs.view(c,db,pid,jid)
    receipt=run['current_receipt']
    if (not receipt or receipt['digest']!=d['receipt_digest'] or
        receipt['digest']==original['execution_digest'] or
        g['receipts'].get('execution')!=receipt['digest'] or
        g['evidence_digest']!=d['regression_digest'] or
        any(g.get(k) is not False for k in FLAGS)):
        raise ValueError('Fresh authoritative execution required')
    report=receipt['snapshot']['report']
    candidate=report['source']['candidate_digest']
    if not runs.hex_digest(candidate):raise ValueError('Invalid candidate digest')
    if verify:
        # A rewritten/deleted assertion is not evidence that the original defect is fixed.
        if (g['state']!='REGRESSION_QUALITY_PASS' or d['state']!='NO_FINDINGS' or
            not any(x['case_id']==original['finding']['case_id'] and
                    x['assertion_digest']==original['finding']['assertion_digest'] and
                    x['status']=='PASS' for x in report['results'])):
            raise ValueError('Independent verification requires original assertion and current full regression PASS')
    return dict(execution_digest=receipt['digest'],candidate_digest=candidate,regression_digest=g['evidence_digest'])

def record(c,db,pid,jid,actor,body,stamp):
    if not c.in_transaction:raise ValueError('Audited transaction required')
    fields={'action','finding_id','registration_digest','expected_digest','assignee','note','confirmation'}
    if not isinstance(body,dict) or set(body)!=fields:raise ValueError('Exact repair fields required')
    action=body['action']; role=permission(action)
    did=body['finding_id']; rd=body['registration_digest']
    if not all(runs.hex_digest(x) for x in (did,rd,body['expected_digest'])):raise ValueError('Invalid digest')
    note=body['note']
    if not isinstance(note,str) or not 1<=len(note.strip())<=1000 or any(ord(x)<32 and x not in '\n\t' for x in note):
        raise ValueError('Bounded repair note required')
    if body['confirmation']!=action+' DEFECT '+jid+' '+did:raise PermissionError('Explicit confirmation required')
    c.execute('SAVEPOINT defect_repair_record')
    try:
        pp.check_role(c,pid,actor,role)
        v=view(c,db,pid,jid)
        if v['state']!='READY' or v['evidence_digest']!=body['expected_digest']:
            raise ValueError('Stale repair view or registry')
        item=next((x for x in v['items'] if x['finding_id']==did and x['registration_digest']==rd and x['latest']),None)
        if not item:raise ValueError('Current registered defect required')
        state=TRANSITIONS.get((item['state'],action))
        if not state:raise ValueError('Invalid repair transition')
        chain=item['history']; prev=chain[-1]['snapshot'] if chain else None
        assignee=body['assignee'] if action in ('ASSIGN','REASSIGN') else item['assignee']
        if action not in ('ASSIGN','REASSIGN') and body['assignee'] is not None:raise ValueError('Unexpected assignee')
        if not isinstance(assignee,str) or not assignee or len(assignee)>100:raise ValueError('Assignee required')
        if action in ('ASSIGN','REASSIGN','START','SUBMIT'):pp.check_role(c,pid,assignee,'write')
        if action in REVIEW and actor==assignee:raise PermissionError('Independent reviewer required')
        if action not in REVIEW and actor!=assignee:raise PermissionError('Assigned developer required')
        original=registry.history(c,pid,jid)[did][-1]['snapshot']
        evidence=None
        if action=='SUBMIT':evidence=repair_evidence(c,db,pid,jid,original)
        if action in ('VERIFY','CLOSE','REJECT'):
            evidence=prev['repair']
            if action!='REJECT' and repair_evidence(c,db,pid,jid,original,verify=True)!=evidence:
                raise ValueError('Submitted repair evidence is stale')
            if action=='CLOSE' and actor==prev['actor']:
                raise PermissionError('Independent closure reviewer required')
        e=dict(schema=SCHEMA,project_id=pid,job_id=jid,finding_id=did,registration_digest=rd,
               version=len(chain)+1,previous_digest=chain[-1]['digest'] if chain else None,
               severity=item['severity'],state=state,action=action,actor=actor,assignee=assignee,
               note=note.strip(),created_at=stamp,repair=evidence,**FLAGS)
        digest=pp.digest(e)
        c.execute('INSERT INTO engineering_defect_repair_events VALUES(?,?,?,?,?,?,?)',
                  (pid,jid,did,rd,e['version'],json.dumps(e,sort_keys=True),digest))
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                  (actor,pid,'engineering_defect_repair_'+action.lower(),'allowed'))
        return dict(snapshot=e,digest=digest)
    except Exception:
        c.execute('ROLLBACK TO defect_repair_record')
        raise
    finally:c.execute('RELEASE defect_repair_record')
