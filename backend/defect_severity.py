"""P6.4e.2.1: authoritative, reviewed impact attestations, never gate overrides."""
import json
import sqlite3
import defect_classification as base
import automated_defect_detection as detection
import project_planning as pp

POLICY='orbit.defect-severity-policy.v2'
FLAGS=base.FLAGS
LEVELS={'DATA_LOSS':'CRITICAL','SECURITY_BREACH':'CRITICAL','ESSENTIAL_FUNCTION_UNAVAILABLE':'CRITICAL',
        'MANDATORY_FAILURE':'HIGH','LIMITED_FUNCTIONAL_IMPACT':'MEDIUM','COSMETIC_IMPACT':'LOW'}

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_severity_attestations(
        project_id TEXT NOT NULL,job_id TEXT NOT NULL,finding_id TEXT NOT NULL,
        receipt_digest TEXT NOT NULL,snapshot TEXT NOT NULL,digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,finding_id,receipt_digest))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS severity_no_{op.lower()}
            BEFORE {op} ON engineering_severity_attestations
            BEGIN SELECT RAISE(ABORT,'Immutable severity attestation'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS severity_no_replace BEFORE INSERT ON engineering_severity_attestations
        WHEN EXISTS(SELECT 1 FROM engineering_severity_attestations WHERE project_id=NEW.project_id
          AND job_id=NEW.job_id AND finding_id=NEW.finding_id AND receipt_digest=NEW.receipt_digest)
        BEGIN SELECT RAISE(ABORT,'Duplicate severity attestation'); END""")

def current(c,db,pid,jid,submitted=None):
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    v=detection.view(c,db,pid,jid)
    if submitted is not None and submitted!=v:raise ValueError('Forged or stale detection evidence')
    return v

def attest(c,db,pid,jid,actor,finding_id,expected_digest,impact, rationale,confirmation):
    if not c.in_transaction:raise ValueError('Audited transaction required')
    if confirmation!='ATTEST SEVERITY '+jid+' '+finding_id:raise PermissionError('Explicit confirmation required')
    c.execute('SAVEPOINT severity_attest')
    try:
        return _attest(c,db,pid,jid,actor,finding_id,expected_digest,impact,rationale)
    except Exception:
        c.execute('ROLLBACK TO severity_attest')
        raise
    finally:
        c.execute('RELEASE severity_attest')

def _attest(c,db,pid,jid,actor,finding_id,expected_digest,impact,rationale):
    pp.check_role(c,pid,actor,'approve')
    v=current(c,db,pid,jid)
    if v['state']!='DETECTED' or v['evidence_digest']!=expected_digest:raise ValueError('Stale detection')
    f=next((x for x in v['findings'] if x['finding_id']==finding_id),None)
    if not f or f['kind']!='ASSERTION_MISMATCH' or impact not in LEVELS:
        raise ValueError('Reviewed product finding required')
    if not isinstance(rationale,str) or not 20<=len(rationale.strip())<=1600 or '\x00' in rationale:
        raise ValueError('Impact rationale required')
    e=dict(schema='orbit.severity-attestation.v1',project_id=pid,job_id=jid,finding_id=finding_id,
           receipt_digest=v['receipt_digest'],detection_digest=v['evidence_digest'],finding_digest=pp.digest(f),
           impact=impact,actor=actor,rationale=rationale.strip(),**FLAGS)
    digest=pp.digest(e)
    c.execute('INSERT INTO engineering_severity_attestations VALUES(?,?,?,?,?,?)',
              (pid,jid,finding_id,v['receipt_digest'],json.dumps(e,sort_keys=True),digest))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
              (actor,pid,'engineering_severity_attest','allowed'))
    return digest

def view(c,db,pid,jid,submitted=None):
    out=dict(schema='orbit.defect-severity.v2',policy=POLICY,project_id=pid,job_id=jid,
             state='BLOCK',items=[],detection_digest=None,quality_gate_override=False,**FLAGS)
    try:
        v=current(c,db,pid,jid,submitted)
        result=base.classify(pid,jid,v)
        if result['state']=='BLOCK':raise ValueError('Invalid detection')
        items=[]
        for item in result['items']:
            f=next(x for x in v['findings'] if x['finding_id']==item['finding_id'])
            row=c.execute('SELECT snapshot,digest FROM engineering_severity_attestations WHERE project_id=? AND job_id=? AND finding_id=? AND receipt_digest=?',
                          (pid,jid,f['finding_id'],v['receipt_digest'])).fetchone()
            if row:
                e=json.loads(row[0])
                if (pp.digest(e)!=row[1] or e['schema']!='orbit.severity-attestation.v1'
                    or (e['project_id'],e['job_id'],e['finding_id'])!=(pid,jid,f['finding_id'])
                    or e['receipt_digest']!=v['receipt_digest'] or e['detection_digest']!=v['evidence_digest']
                    or e['finding_digest']!=pp.digest(f) or f['kind']!='ASSERTION_MISMATCH'
                    or any(e.get(k) is not False for k in FLAGS) or e['impact'] not in LEVELS):
                    raise ValueError('Invalid impact attestation')
                item=dict(item,severity=LEVELS[e['impact']],impact_confirmed=True,attestation_digest=row[1],
                          impact_basis='AUTHORIZED_REVIEW')
            else:
                item=dict(item,attestation_digest=None,impact_basis='MANDATORY_TEST_DEFAULT')
            items.append(item)
        out.update(state=result['state'],items=items,detection_digest=v['evidence_digest'])
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,StopIteration,sqlite3.Error,PermissionError):
        pass
    out['evidence_digest']=pp.digest(out)
    return out
