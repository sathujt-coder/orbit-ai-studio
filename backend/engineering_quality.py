"""Evidence-bound append-only engineering defect tracking (P6.3i)."""
import json
import re
import sqlite3
import engineering_sandbox as sb
import studio_verification as qa
import studio_coding as sc
import project_planning as pp
import product_requirements as pr

FLAGS=sb.FLAGS
ID=re.compile(r'[A-Za-z0-9_-]{1,80}\Z')
SEVERITIES=('CRITICAL','HIGH','MEDIUM','LOW')
CATEGORIES=('FUNCTIONAL','SECURITY','TEST','INTEGRATION','OTHER')
NEXT={'OPEN':{'READY_FOR_RETEST'},'READY_FOR_RETEST':{'OPEN','CLOSED'},'CLOSED':{'OPEN'}}


def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_defect_events(
        project_id TEXT NOT NULL REFERENCES projects(id),
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        defect_id TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),
        snapshot TEXT NOT NULL,digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,defect_id,version))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS engineering_defect_no_{op.lower()}
            BEFORE {op} ON engineering_defect_events
            BEGIN SELECT RAISE(ABORT,'Immutable defect history'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS engineering_defect_no_replace
        BEFORE INSERT ON engineering_defect_events
        WHEN EXISTS(SELECT 1 FROM engineering_defect_events WHERE project_id=NEW.project_id
          AND job_id=NEW.job_id AND defect_id=NEW.defect_id AND version=NEW.version)
        BEGIN SELECT RAISE(ABORT,'Duplicate defect event'); END""")


def source(c,db,pid,jid):
    if not isinstance(jid,str) or not ID.fullmatch(jid):raise ValueError('Invalid job identity')
    b=sc.evidence(c,pid,jid)
    if not b or b['state']!='BOUND':raise ValueError('Current bound coding job required')
    q=qa.view(c,pid,jid)
    s=sb.view(c,db,pid,jid)
    return dict(schema='orbit.engineering-quality-source.v1',project_id=pid,job_id=jid,
        binding={k:b[k] for k in ('adoption_version','package_id','binding_digest','spec_digest')},
        qa=dict(state=q['state'],source_digest=q['source_digest'],
                receipt_digest=(q.get('receipt') or {}).get('digest')),
        sandbox=dict(state=s['state'],source_digest=s['source_digest'],version=s['latest_version'],
                     receipt_digest=(s.get('receipt') or {}).get('digest')),**FLAGS)


def require_retest(src,prior):
    s,p,q=src['sandbox'],prior['sandbox'],src['qa']
    if (s['state']!='PASS' or q['state']!='HUMAN_QA_PASS'
        or not s['receipt_digest'] or not q['receipt_digest'] or not q['source_digest']
        or type(s['version']) is not int or s['version']<=p['version']
        or s['receipt_digest']==p['receipt_digest']):
        raise ValueError('Fresh passing Git sandbox replay and current human QA required')


def lineage(c,pid,jid):
    """Only the latest exact-package attempt may mutate or publish defects."""
    import bound_recovery as br
    import agent_queue as aq
    target=sc.lookup(c,pid,jid)
    if not target:raise ValueError('Unknown bound defect job')
    keys=('adoption_version','package_id','binding_digest','spec_digest')
    rows=c.execute("""SELECT * FROM studio_coding_bindings WHERE project_id=? AND adoption_version=?
        AND package_id=? ORDER BY rowid""",(pid,target['adoption_version'],target['package_id'])).fetchall()
    if not rows or rows[-1]['job_id']!=jid:raise ValueError('Superseded defect job')
    previous=None
    for row in rows:
        if any(row[k]!=target[k] for k in keys):raise ValueError('Retry defect binding mismatch')
        queue=aq.get(c,pid,row['queue_id'])
        if queue['coding_job_id']!=row['job_id'] or queue['actor']!=row['actor'] or queue['kind']!='coding':
            raise ValueError('Invalid defect queue binding')
        if previous:
            if queue['retry_of']!=previous['queue_id']:raise ValueError('Nonlinear defect retry lineage')
            br.validate_retry(c,pid,row,queue)
        elif queue['retry_of'] or c.execute('SELECT 1 FROM studio_bound_retries WHERE job_id=?',(row['job_id'],)).fetchone():
            raise ValueError('Missing defect lineage root')
        previous=row
    return [row['job_id'] for row in rows]


def history(c,pid,jid):
    result={}
    jobs=lineage(c,pid,jid)
    rows=[row for job in jobs for row in c.execute("""SELECT * FROM engineering_defect_events
        WHERE project_id=? AND job_id=? ORDER BY defect_id,version""",(pid,job))]
    for row in rows:
        e=json.loads(row['snapshot'])
        did=row['defect_id'];chain=result.setdefault(did,[])
        prev=chain[-1] if chain else None
        if (pp.digest(e)!=row['digest'] or e['project_id']!=pid or e['job_id']!=row['job_id']
            or e['defect_id']!=did or e['version']!=row['version'] or e['version']!=len(chain)+1
            or e['previous_digest']!=(prev['digest'] if prev else None)
            or e['source']['project_id']!=pid or e['source']['job_id']!=row['job_id']
            or e['source_digest']!=pp.digest(e['source'])
            or e['severity'] not in SEVERITIES or e['category'] not in CATEGORIES
            or any(e[k] is not False for k in FLAGS)):
            raise ValueError('Invalid defect chain')
        if prev:
            p=prev['event']
            if e['state'] not in NEXT[p['state']] or any(e[k]!=p[k] for k in ('severity','category','title')):
                raise ValueError('Invalid defect transition')
            if e['source']['binding']!=p['source']['binding']:raise ValueError('Defect binding changed')
            if e['state']=='CLOSED':
                if p['job_id']!=e['job_id']:raise ValueError('Retest handoff required on current retry job')
                require_retest(e['source'],p['source'])
        elif e['state']!='OPEN':raise ValueError('Defect must start OPEN')
        chain.append(dict(digest=row['digest'],event=e))
    return result


def guard_no_open_defects(c,pid,jid,db=None):
    chains=history(c,pid,jid)
    if any(chain[-1]['event']['state']!='CLOSED' for chain in chains.values()):
        raise ValueError('Unresolved engineering defects block draft publication')
    if chains and db is not None:
        src=source(c,db,pid,jid)
        if any(chain[-1]['event']['source']!=src for chain in chains.values()):
            raise ValueError('Stale defect closure evidence blocks draft publication')


def text_field(value,minimum,maximum):
    if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum or '\x00' in value:
        raise ValueError('Invalid defect text')
    return value.strip()


def record(c,db,pid,jid,actor,body,stamp):
    if not isinstance(body,dict):raise ValueError('Invalid defect request')
    action=body.get('action')
    if action not in ('OPEN','READY_FOR_RETEST','CLOSED','REOPEN'):raise ValueError('Unknown defect action')
    common=('action','defect_id','expected_version','source_digest','rationale','confirmation')
    pr.fields(body,common+('severity','category','title') if action=='OPEN' else common)
    did=body['defect_id'];version=body['expected_version']
    if not isinstance(did,str) or not ID.fullmatch(did) or type(version) is not int or version<0:
        raise ValueError('Invalid defect identity or version')
    if body['confirmation']!='DEFECT '+action+' '+jid+' '+did:raise ValueError('Explicit defect confirmation required')
    rationale=text_field(body['rationale'],20,1600)
    c.execute('SAVEPOINT engineering_defect')
    try:
        pp.check_role(c,pid,actor,'write' if action=='READY_FOR_RETEST' else 'approve')
        src=source(c,db,pid,jid)
        if body['source_digest']!=pp.digest(src):raise ValueError('Stale quality source')
        chain=history(c,pid,jid).get(did,[])
        if version!=len(chain):raise ValueError('Stale defect version')
        previous=chain[-1] if chain else None
        if action=='OPEN':
            if previous:raise ValueError('Defect already exists')
            severity,category=body['severity'],body['category']
            title=text_field(body['title'],5,200)
            if severity not in SEVERITIES or category not in CATEGORIES:raise ValueError('Unknown defect classification')
            state='OPEN'
        else:
            if not previous:raise ValueError('Unknown defect')
            p=previous['event'];state='OPEN' if action=='REOPEN' else action
            if state not in NEXT[p['state']] or src['binding']!=p['source']['binding']:
                raise ValueError('Invalid defect transition or binding')
            severity,category,title=(p[k] for k in ('severity','category','title'))
            if state=='CLOSED':
                if p['job_id']!=jid:raise ValueError('Retest handoff required on current retry job')
                require_retest(src,p['source'])
        event=dict(schema='orbit.engineering-defect-event.v1',project_id=pid,job_id=jid,
            defect_id=did,version=version+1,state=state,severity=severity,category=category,title=title,
            rationale=rationale,actor=actor,created_at=stamp,source=src,source_digest=pp.digest(src),
            previous_digest=previous['digest'] if previous else None,**FLAGS)
        digest=pp.digest(event)
        c.execute('INSERT INTO engineering_defect_events VALUES(?,?,?,?,?,?)',
                  (pid,jid,did,version+1,pr.canonical(event),digest))
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                  (actor,pid,'engineering_defect_'+action.lower(),'allowed'))
        c.execute('RELEASE engineering_defect')
    except Exception:
        c.execute('ROLLBACK TO engineering_defect');c.execute('RELEASE engineering_defect');raise
    return dict(event=event,digest=digest,**FLAGS)


def view(c,db,pid,jid):
    out=dict(project_id=pid,job_id=jid,state='BLOCK',source=None,source_digest=None,
             defects=[],counts=dict(OPEN=0,READY_FOR_RETEST=0,CLOSED=0),**FLAGS)
    try:
        src=source(c,db,pid,jid)
        chains=history(c,pid,jid)
        out.update(source=src,source_digest=pp.digest(src),lineage=lineage(c,pid,jid))
        for did,chain in chains.items():
            last=chain[-1]['event']
            if last['source']['binding']!=src['binding']:raise ValueError('Stale defect binding')
            out['counts'][last['state']]+=1
            out['defects'].append(dict(defect_id=did,state=last['state'],version=last['version'],
                severity=last['severity'],category=last['category'],title=last['title'],
                digest=chain[-1]['digest'],origin_job_id=chain[0]['event']['job_id'],last_event_job_id=last['job_id'],history=chain))
        # Closed defects become stale if the current reviewed source is replaced.
        fresh=all(x['state']=='CLOSED' and x['history'][-1]['event']['source']==src for x in out['defects'])
        if fresh and src['sandbox']['state']=='PASS' and src['qa']['state']=='HUMAN_QA_PASS':
            out['state']='QUALITY_EVIDENCE_PASS'
    except (ValueError,TypeError,KeyError,AttributeError,PermissionError,sqlite3.Error,OSError):
        out.update(state='BLOCK',source=None,source_digest=None,defects=[],
                   counts=dict(OPEN=0,READY_FOR_RETEST=0,CLOSED=0))
    return out
