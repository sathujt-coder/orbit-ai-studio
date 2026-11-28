"""P6.4e.3: immutable registration of authoritative classified findings.

This registry records observations, not repair or closure decisions. Absence of
a current finding never closes a historical defect. Only trusted local
operators may register; existing publication/quality gates remain unchanged.
"""
import json
import sqlite3
import defect_severity as severity
import project_planning as pp
import engineering_assertion_registry as assertions

FLAGS=severity.FLAGS
SCHEMA='orbit.detected-defect-receipt.v1'

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_detected_defects(
        project_id TEXT NOT NULL, job_id TEXT NOT NULL, finding_id TEXT NOT NULL,
        version INTEGER NOT NULL CHECK(version>0), execution_digest TEXT NOT NULL,
        snapshot TEXT NOT NULL, digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,finding_id,version),
        UNIQUE(project_id,job_id,finding_id,execution_digest))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS detected_defect_no_{op.lower()}
            BEFORE {op} ON engineering_detected_defects
            BEGIN SELECT RAISE(ABORT,'Immutable detected defect receipt'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS detected_defect_no_replace
        BEFORE INSERT ON engineering_detected_defects
        WHEN EXISTS(SELECT 1 FROM engineering_detected_defects WHERE
            project_id=NEW.project_id AND job_id=NEW.job_id AND finding_id=NEW.finding_id
            AND (version=NEW.version OR execution_digest=NEW.execution_digest))
        BEGIN SELECT RAISE(ABORT,'Duplicate detected defect receipt'); END""")

def history(c,pid,jid):
    chains={}
    for row in c.execute("""SELECT finding_id,version,execution_digest,snapshot,digest
        FROM engineering_detected_defects WHERE project_id=? AND job_id=?
        ORDER BY finding_id,version""",(pid,jid)):
        did,version,execution,raw,digest=tuple(row)
        e=json.loads(raw)
        chain=chains.setdefault(did,[])
        if (e['schema']!=SCHEMA or (e['project_id'],e['job_id'],e['finding_id'])!=(pid,jid,did)
            or pp.digest(e)!=digest or type(e['version']) is not int or e['version']!=version
            or version!=len(chain)+1 or e['previous_digest']!=(chain[-1]['digest'] if chain else None)
            or e['execution_digest']!=execution or e['finding']['finding_id']!=did
            or e['classification']['finding_id']!=did or e['classification']['receipt_digest']!=execution
            or e['finding']['receipt_digest']!=execution or pp.digest(e['finding'])!=e['classification']['finding_digest']
            or e['state']!='OPEN' or e['policy']!=severity.POLICY
            or e['classification']['severity'] not in ('CRITICAL','HIGH','MEDIUM','LOW')
            or not all(assertions.hex_digest(e[k]) for k in ('execution_digest','detection_digest','severity_digest'))
            or any(e.get(k) is not False for k in FLAGS)
            or not isinstance(e['actor'],str) or not e['actor']):
            raise ValueError('Invalid detected defect receipt')
        identity={k:e['finding'][k] for k in ('project_id','job_id','case_id','assertion_digest','kind')}
        if pp.digest(identity)!=did or (identity['project_id'],identity['job_id'])!=(pid,jid):
            raise ValueError('Finding identity mismatch')
        chain.append(dict(snapshot=e,digest=digest))
    return chains

def current(c,db,pid,jid):
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    d=severity.current(c,db,pid,jid)
    s=severity._severity_view(c,pid,jid,lambda:d)
    if s['state']=='BLOCK' or s['detection_digest']!=d['evidence_digest']:
        raise ValueError('Current authoritative evidence required')
    if s['quality_gate_override'] is not False or any(s.get(k) is not False for k in FLAGS):
        raise ValueError('Unexpected authorization')
    if [x['finding_id'] for x in d['findings']]!=[x['finding_id'] for x in s['items']]:
        raise ValueError('Incomplete classification')
    return d,s

def register(c,db,pid,jid,actor,expected_severity_digest,confirmation):
    if not c.in_transaction:raise ValueError('Audited transaction required')
    if confirmation!='REGISTER DETECTED DEFECTS '+jid:raise PermissionError('Explicit registration required')
    c.execute('SAVEPOINT detected_defect_register')
    try:
        pp.check_role(c,pid,actor,'approve')
        d,s=current(c,db,pid,jid)
        if s['evidence_digest']!=expected_severity_digest or s['state']!='CLASSIFIED':
            raise ValueError('Stale evidence or no findings')
        chains=history(c,pid,jid)
        inserted=[]
        for f,item in zip(d['findings'],s['items']):
            did=f['finding_id']; chain=chains.get(did,[])
            if any(x['snapshot']['execution_digest']==d['receipt_digest'] for x in chain):
                raise ValueError('Execution already registered')
            e=dict(schema=SCHEMA,project_id=pid,job_id=jid,finding_id=did,version=len(chain)+1,
                   previous_digest=chain[-1]['digest'] if chain else None,state='OPEN',actor=actor,
                   execution_digest=d['receipt_digest'],detection_digest=d['evidence_digest'],
                   severity_digest=s['evidence_digest'],policy=s['policy'],finding=f,classification=item,**FLAGS)
            digest=pp.digest(e)
            c.execute('INSERT INTO engineering_detected_defects VALUES(?,?,?,?,?,?,?)',
                      (pid,jid,did,e['version'],e['execution_digest'],json.dumps(e,sort_keys=True),digest))
            inserted.append(digest)
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                  (actor,pid,'engineering_detected_defects_register','allowed'))
        return inserted
    except Exception:
        c.execute('ROLLBACK TO detected_defect_register')
        raise
    finally:
        c.execute('RELEASE detected_defect_register')

def view(c,db,pid,jid):
    return _snapshot(c,db,pid,jid)[0]

def _snapshot(c,db,pid,jid):
    """Return the registry view and the exact authoritative detection used to build it."""
    detection=None
    out=dict(schema='orbit.detected-defect-registry.v1',project_id=pid,job_id=jid,state='BLOCK',
             history=[],current_finding_ids=[],unregistered_finding_ids=[],severity_digest=None,
             automatic_closure=False,quality_gate_override=False,**FLAGS)
    try:
        if not c.in_transaction:raise ValueError('Consistent transaction required')
        chains=history(c,pid,jid)
        out['history']=[x for did in sorted(chains) for x in chains[did]]
        d,s=current(c,db,pid,jid)
        ids=[x['finding_id'] for x in d['findings']]
        pending=[did for did in ids if not any(
            x['snapshot']['execution_digest']==d['receipt_digest'] and
            x['snapshot']['severity_digest']==s['evidence_digest'] for x in chains.get(did,[]))]
        out.update(state='REGISTRATION_REQUIRED' if pending else ('REGISTERED' if ids else 'NO_CURRENT_FINDINGS'),
                   current_finding_ids=ids,unregistered_finding_ids=pending,severity_digest=s['evidence_digest'])
        detection=d
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,sqlite3.Error,PermissionError,OSError):
        pass
    out['evidence_digest']=pp.digest(out)
    return out,detection
