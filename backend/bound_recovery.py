"""Explicit immutable bound-job retry. Never resume uncertain model execution."""
import json
import agent_queue as aq
import studio_coding as sc
import dependency_queue as dq
import project_planning as pp
import product_requirements as pr

TERMINAL=('dead','interrupted','cancelled')

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS studio_bound_retries(
        job_id TEXT PRIMARY KEY REFERENCES studio_coding_bindings(job_id),
        previous_job_id TEXT NOT NULL UNIQUE REFERENCES studio_coding_bindings(job_id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        snapshot TEXT NOT NULL,digest TEXT NOT NULL,actor TEXT NOT NULL,created_at TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS sc_package_attempts ON studio_coding_bindings(project_id,adoption_version,package_id)")
    # Retain database-level initial uniqueness: only an explicitly linked
    # terminal predecessor may have a successor for the same package.
    c.execute("""CREATE TRIGGER IF NOT EXISTS sc_retry_lineage_guard BEFORE INSERT ON studio_coding_bindings
        WHEN EXISTS(SELECT 1 FROM studio_coding_bindings b WHERE b.project_id=NEW.project_id
            AND b.adoption_version=NEW.adoption_version AND b.package_id=NEW.package_id)
        AND NOT EXISTS(
            SELECT 1 FROM agent_queue q JOIN studio_coding_bindings b ON b.queue_id=q.retry_of
            JOIN agent_queue old ON old.id=b.queue_id
            WHERE q.id=NEW.queue_id AND q.project_id=NEW.project_id AND q.coding_job_id=NEW.job_id
            AND q.kind='coding' AND q.actor=NEW.actor AND q.status='queued'
            AND b.project_id=NEW.project_id AND b.adoption_version=NEW.adoption_version AND b.package_id=NEW.package_id
            AND b.binding_digest=NEW.binding_digest AND b.spec_digest=NEW.spec_digest
            AND old.status IN ('dead','interrupted','cancelled')
            AND NOT EXISTS(SELECT 1 FROM studio_bound_retries r WHERE r.previous_job_id=b.job_id)
            AND NOT EXISTS(SELECT 1 FROM studio_coding_bindings later
                WHERE later.project_id=b.project_id AND later.adoption_version=b.adoption_version
                AND later.package_id=b.package_id AND later.rowid>b.rowid))
        BEGIN SELECT RAISE(ABORT,'Invalid bound retry lineage'); END""")

def snapshot(c,pid,qid):
    old=aq.get(c,pid,qid)
    if old['kind']!='coding' or old['status'] not in TERMINAL:
        raise ValueError('Terminal bound coding queue required')
    row=sc.lookup(c,pid,old['coding_job_id'])
    if not row or row['queue_id']!=qid or row['actor']!=old['actor']:
        raise ValueError('Exact prior bound queue required')
    job=c.execute('SELECT * FROM coding_jobs WHERE id=? AND project_id=?',(row['job_id'],pid)).fetchone()
    if not job or job['status'] not in ('failed','needs_revision'):
        raise ValueError('Failed or needs-revision coding job required')
    if old['dependency_id'] and aq.get(c,pid,old['dependency_id'])['status']!='succeeded':
        raise ValueError('Original queue dependency not successful')
    for table in ('studio_qa_receipts','engineering_completions','coding_verifications'):
        if c.execute('SELECT 1 FROM '+table+' WHERE project_id=? AND job_id=?',(pid,row['job_id'])).fetchone():
            raise ValueError('Prior verification or approval evidence requires separate review')
    snap=sc.checked_job_package(c,pid,row)
    if job['spec']!=sc.spec_for(snap) or pp.digest(job['spec'])!=row['spec_digest']:
        raise ValueError('Prior specification digest mismatch')
    pin=c.execute('SELECT snapshot,digest FROM engineering_queue_sources WHERE project_id=? AND job_id=?',(pid,row['job_id'])).fetchone()
    if pin:
        if not sc.effective_predecessors(c,pid,row['adoption_version'],snap):
            raise ValueError('Pinned dependency graph no longer current')
        dq.checked_package(c,pid,row)
    defects=[]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='engineering_defect_events'").fetchone():
        defects=[dict(x) for x in c.execute('SELECT * FROM engineering_defect_events WHERE project_id=? AND job_id=? ORDER BY defect_id,version',(pid,row['job_id']))]
    return dict(schema='orbit.bound-recovery-source.v1',project_id=pid,previous_job_id=row['job_id'],
        previous_queue_id=qid,previous_status=old['status'],previous_reason=old['reason'],
        previous_job_digest=pp.digest(dict(job)),previous_queue_digest=pp.digest(dict(old)),
        adoption_version=row['adoption_version'],package_id=row['package_id'],binding_digest=row['binding_digest'],
        spec_digest=row['spec_digest'],dependency_source_digest=pin['digest'] if pin else None,
        execution_authorized=False,**({'defect_history_digest':pp.digest(defects)} if defects else {})),job['spec']

def source(c,pid,qid):
    src,spec=snapshot(c,pid,qid)
    current=c.execute('SELECT job_id FROM studio_coding_bindings WHERE project_id=? AND adoption_version=? AND package_id=? ORDER BY rowid DESC LIMIT 1',
                      (pid,src['adoption_version'],src['package_id'])).fetchone()
    if not current or current['job_id']!=src['previous_job_id'] or c.execute('SELECT 1 FROM studio_bound_retries WHERE previous_job_id=?',(src['previous_job_id'],)).fetchone():
        raise ValueError('Prior bound attempt already superseded')
    return src,spec

def request(c,pid,actor,body):
    pp.check_role(c,pid,actor,'write')
    pr.fields(body,('queue_id','source_digest','rationale','confirmation'))
    if body['confirmation']!='RETRY BOUND WORK PACKAGE' or not isinstance(body['queue_id'],str):
        raise ValueError('Explicit RETRY BOUND WORK PACKAGE required')
    if not isinstance(body['rationale'],str) or not 20<=len(body['rationale'].strip())<=1200:
        raise ValueError('Explicit recovery rationale required')
    src,spec=source(c,pid,body['queue_id'])
    if body['source_digest']!=pp.digest(src):raise ValueError('Current bound recovery source digest required')
    return src,spec

def record(c,pid,actor,body,jid,qid,stamp):
    src,spec=request(c,pid,actor,body)
    old=aq.get(c,pid,src['previous_queue_id'])
    new=aq.get(c,pid,qid)
    if (new['retry_of']!=old['id'] or new['coding_job_id']!=jid or new['actor']!=actor or new['status']!='queued'
        or new['kind']!='coding' or new['provider_revision']!=old['provider_revision']
        or new['provider_fingerprint']!=old['provider_fingerprint'] or new['dependency_id']!=old['dependency_id']):
        raise ValueError('Retry queue lineage or provider identity mismatch')
    job=c.execute('SELECT spec,status FROM coding_jobs WHERE project_id=? AND id=?',(pid,jid)).fetchone()
    if not job or job['spec']!=spec or job['status']!='queued':raise ValueError('Retry specification mismatch')
    c.execute('INSERT INTO studio_coding_bindings VALUES(?,?,?,?,?,?,?,?,?)',
        (jid,pid,qid,src['adoption_version'],src['package_id'],src['binding_digest'],src['spec_digest'],actor,stamp))
    if src['dependency_source_digest']:
        pin=c.execute('SELECT snapshot,digest FROM engineering_queue_sources WHERE project_id=? AND job_id=?',(pid,src['previous_job_id'])).fetchone()
        c.execute('INSERT INTO engineering_queue_sources VALUES(?,?,?,?)',(jid,pid,pin['snapshot'],pin['digest']))
    receipt=dict(source=src,job_id=jid,queue_id=qid,actor=actor,rationale=body['rationale'].strip(),
                 automatic_dispatch=False,execution_authorized=False,production_release_authorized=False)
    digest=pp.digest(receipt)
    c.execute('INSERT INTO studio_bound_retries VALUES(?,?,?,?,?,?,?)',(jid,src['previous_job_id'],pid,pr.canonical(receipt),digest,actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'studio_bound_retry','allowed'))
    return digest

def validate_retry(c,pid,row,q):
    saved=c.execute('SELECT * FROM studio_bound_retries WHERE project_id=? AND job_id=?',(pid,row['job_id'])).fetchone()
    if not saved:raise ValueError('Missing bound retry receipt')
    receipt=json.loads(saved['snapshot'])
    previous=aq.get(c,pid,q['retry_of'])
    if (previous['id']==q['id'] or previous['provider_revision']!=q['provider_revision']
        or previous['provider_fingerprint']!=q['provider_fingerprint'] or previous['dependency_id']!=q['dependency_id']):
        raise ValueError('Retry provider or lineage mismatch')
    src,spec=snapshot(c,pid,q['retry_of'])
    if (pp.digest(receipt)!=saved['digest'] or receipt['source']!=src or saved['previous_job_id']!=src['previous_job_id']
        or receipt['job_id']!=row['job_id'] or receipt['queue_id']!=q['id'] or receipt['actor']!=q['actor'] or saved['actor']!=q['actor']
        or any(receipt.get(k) is not False for k in ('automatic_dispatch','execution_authorized','production_release_authorized'))
        or any(row[k]!=src[k] for k in ('adoption_version','package_id','binding_digest','spec_digest'))):
        raise ValueError('Invalid bound retry receipt')
    pin=c.execute('SELECT digest FROM engineering_queue_sources WHERE project_id=? AND job_id=?',(pid,row['job_id'])).fetchone()
    if (pin['digest'] if pin else None)!=src['dependency_source_digest']:raise ValueError('Retry prerequisite pin mismatch')

def view(c,pid,qid):
    out=dict(state='BLOCK',source=None,source_digest=None,automatic_dispatch=False,production_release_authorized=False)
    try:
        src,_=source(c,pid,qid)
        out.update(state='READY_FOR_EXPLICIT_RETRY',source=src,source_digest=pp.digest(src))
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError):pass
    return out
