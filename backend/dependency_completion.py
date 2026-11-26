"""P6.3b: current prerequisite evidence, not dependency dispatch authority.

A QA pass alone is insufficient. Explicit candidate-bound human completion
is a development evidence receipt; later phases must integrate eligibility.
"""
import json
import engineering_contract as ec
import studio_verification as qa
import project_planning as pp
import product_requirements as pr
import coding_factory as cf
from web_candidate_selection import decide
from verified_pr import verified_bundle

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_completions(
        project_id TEXT NOT NULL, adoption_version INTEGER NOT NULL,
        package_id TEXT NOT NULL, version INTEGER NOT NULL,
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        snapshot TEXT NOT NULL, digest TEXT NOT NULL, actor TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,adoption_version,package_id,version),
        FOREIGN KEY(project_id,adoption_version,package_id)
        REFERENCES studio_work_packages(project_id,adoption_version,package_id))""")

def source(c,pid,jid):
    src=qa.source(c,pid,jid)
    # A prior completion is not a bypass for outstanding defects.
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='engineering_defect_events'").fetchone():
        any_defect=c.execute("""SELECT 1 FROM engineering_defect_events e JOIN studio_coding_bindings b
            ON b.job_id=e.job_id AND b.project_id=e.project_id
            WHERE b.project_id=? AND b.adoption_version=? AND b.package_id=? LIMIT 1""",
            (pid,src['adoption_version'],src['package_id'])).fetchone()
        if any_defect:
            import engineering_quality as quality
            from pathlib import Path
            db_path=next((r[2] for r in c.execute('PRAGMA database_list') if r[1]=='main'),'')
            if not db_path:raise ValueError('Persistent defect evidence database required')
            quality.guard_no_open_defects(c,pid,jid,Path(db_path))
    if src['project_id']!=pid or src['job_id']!=jid:raise ValueError('QA source scope mismatch')
    v,p=src['adoption_version'],src['package_id']
    contract=ec.source(c,pid,p)
    row=ec.require_confirmed(c,pid,contract)
    if (contract['adoption_version']!=v
        or contract['binding_digest']!=src['binding_digest'] or contract['spec_digest']!=src['spec_digest']
        or (contract['predecessors'] and not src.get('dependency_source_digest'))):
        raise ValueError('Current confirmed engineering contract required')
    state=qa.view(c,pid,jid)
    receipt=state['receipt']
    if state['state']!='HUMAN_QA_PASS' or state['source']!=src or not receipt:
        raise ValueError('Current passing human QA receipt required')
    criteria=receipt['criteria']
    expected={x['id'] for x in src['acceptance']}
    if not expected or len(criteria)!=len(expected) or {x['id'] for x in criteria}!=expected:
        raise ValueError('Exact QA criteria required')
    for item in criteria:
        pr.fields(item,('id','verdict','rationale'))
        if item['verdict']!='PASS' or not isinstance(item['rationale'],str) or not 20<=len(item['rationale'].strip())<=1200:
            raise ValueError('Passing QA criterion evidence required')
    return dict(schema='orbit.dependency-completion-source.v1',project_id=pid,job_id=jid,
        adoption_version=v,package_id=p,contract_version=row['version'],contract_digest=row['digest'],
        graph_digest=contract['graph_digest'],qa_version=receipt['version'],qa_digest=receipt['digest'],
        qa_source_digest=pp.digest(src),report_id=src['report_id'],report_digest=src['report_digest'],
        candidates=src['candidates'],execution_authorized=False,**({'dependency_source_digest':src['dependency_source_digest']} if src.get('dependency_source_digest') else {}))

def latest(c,pid,v,p):
    return c.execute('SELECT * FROM engineering_completions WHERE project_id=? AND adoption_version=? AND package_id=? ORDER BY version DESC LIMIT 1',(pid,v,p)).fetchone()

def selection(c,pid,src,actor,lane,rationale):
    job=cf.detail(c,src['job_id'])
    row=c.execute('SELECT report_json FROM coding_verifications WHERE project_id=? AND job_id=? AND id=?',(pid,src['job_id'],src['report_id'])).fetchone()
    if not row or job['project_id']!=pid:raise ValueError('Current verification required')
    import hashlib
    if hashlib.sha256(row['report_json'].encode()).hexdigest()!=src['report_digest']:raise ValueError('Report digest mismatch')
    report=json.loads(row['report_json'])
    decision=decide(job,report,selected=lane,techlead=actor,rationale=rationale,confirmation='SELECT DEV-'+lane+' '+job['id'])
    verified_bundle(job,report,decision=decision)
    return decision

def record(c,pid,actor,body,stamp):
    pp.check_role(c,pid,actor,'approve')
    pr.fields(body,('job_id','source_digest','expected_version','selected','rationale','confirmation'))
    if not isinstance(body['job_id'],str) or body['selected'] not in ('A','B') or type(body['expected_version']) is not int:
        raise ValueError('Invalid completion identity')
    if body['confirmation']!='CONFIRM DEPENDENCY COMPLETION DEV-'+body['selected']+' '+body['job_id']:
        raise ValueError('Explicit candidate-bound completion required')
    src=source(c,pid,body['job_id'])
    if pp.digest(src)!=body['source_digest']:raise ValueError('Current completion source required')
    row=latest(c,pid,src['adoption_version'],src['package_id'])
    v=row['version'] if row else 0
    if v!=body['expected_version']:raise ValueError('Stale completion version')
    if row and json.loads(row['snapshot']).get('source')==src:raise ValueError('Current source already confirmed')
    decision=selection(c,pid,src,actor,body['selected'],body['rationale'])
    snap=dict(source=src,decision=decision,scope='development_evidence_only',
        execution_authorized=False,automatic_dispatch=False,production_release_authorized=False)
    digest=pp.digest(snap)
    c.execute('INSERT INTO engineering_completions VALUES(?,?,?,?,?,?,?,?,?)',(pid,src['adoption_version'],src['package_id'],v+1,src['job_id'],pr.canonical(snap),digest,actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'engineering_completion_confirm','allowed'))
    return dict(version=v+1,digest=digest,execution_authorized=False,automatic_dispatch=False,production_release_authorized=False)

def view(c,pid):
    out=dict(project_id=pid,items=[],execution_authorized=False,automatic_dispatch=False,production_release_authorized=False)
    rows=c.execute('SELECT job_id,adoption_version,package_id FROM studio_coding_bindings WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,)).fetchall()
    for b in rows:
        jid,v,p=b['job_id'],b['adoption_version'],b['package_id']
        row=latest(c,pid,v,p)
        item=dict(job_id=jid,adoption_version=v,package_id=p,state='STALE' if row else 'BLOCK',source=None,source_digest=None,latest_version=row['version'] if row else 0,receipt=None)
        try:
            if row:
                snap=json.loads(row['snapshot'])
                item['receipt']={k:row[k] for k in ('version','digest','actor','created_at')}
                if pp.digest(snap)!=row['digest']:
                    item['state']='INVALID';out['items'].append(item);continue
                if row['job_id']!=jid:
                    # Only verified lineage may classify a historical job as superseded.
                    retry_table=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='studio_bound_retries'").fetchone()
                    linked=retry_table and c.execute("""WITH RECURSIVE lineage(job_id) AS (
                        SELECT ? UNION SELECT r.job_id FROM studio_bound_retries r JOIN lineage l
                        ON r.previous_job_id=l.job_id WHERE r.project_id=?)
                        SELECT 1 FROM lineage WHERE job_id=?""",(jid,pid,row['job_id'])).fetchone()
                    item.update(state='SUPERSEDED' if linked else 'INVALID',receipt=None)
                    out['items'].append(item);continue
            src=source(c,pid,jid)
            item.update(source=src,source_digest=pp.digest(src))
            if not row:item['state']='AWAITING_CONFIRMATION'
            elif snap['source']==src:
                decision=snap['decision']
                current=selection(c,pid,src,row['actor'],decision['selected'],decision['rationale'])
                # The timestamp is generated afresh; all other evidence must match.
                if {k:v for k,v in current.items() if k!='decided_at'}!={k:v for k,v in decision.items() if k!='decided_at'}:
                    raise ValueError('Candidate decision mismatch')
                item['state']='COMPLETION_EVIDENCE_CONFIRMED'
                item['receipt']['selected']=decision['selected']
                item['receipt']['selected_digest']=decision['selected_digest']
        except (ValueError,TypeError,KeyError,AttributeError,PermissionError):pass
        out['items'].append(item)
    return out
