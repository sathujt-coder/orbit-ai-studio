"""P6.3f: explicit, immutable candidate selection bound to a pristine Git baseline.

Reuses the existing bound-source, cross-review and sandbox gates. No candidate
materialization, Git mutation, queue dispatch or publishing is permitted here.
"""
import hashlib
import json
import re
import sqlite3

import coding_factory
import engineering_contract as ec
import product_requirements as pr
import project_planning as pp
import project_git_workspace as ws
import studio_verification as qa
from web_candidate_selection import decide
from verified_pr import verified_bundle

FLAGS = dict(ws.FLAGS, publish_allowed=False, production_approved=False)
ID = re.compile(r'[A-Za-z0-9_-]{1,100}\Z')


def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_candidate_selections(
        project_id TEXT NOT NULL REFERENCES projects(id),
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        version INTEGER NOT NULL CHECK(version>0),
        source_digest TEXT NOT NULL, snapshot TEXT NOT NULL, digest TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,version),
        UNIQUE(project_id,job_id,source_digest))""")
    for operation in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS engineering_selection_no_{operation.lower()}
            BEFORE {operation} ON engineering_candidate_selections
            BEGIN SELECT RAISE(ABORT,'Immutable engineering selection receipt'); END""")


def source(c, db_path, pid, jid):
    if not isinstance(jid,str) or not ID.fullmatch(jid):
        raise ValueError('Invalid coding job identity')
    baseline = ws.view(db_path,pid)
    if baseline['state'] != 'READY':
        raise ValueError('Current isolated project Git workspace required')
    evidence = qa.source(c,pid,jid)
    if evidence['project_id'] != pid or evidence['job_id'] != jid:
        raise ValueError('Bound candidate scope mismatch')
    contract = ec.source(c,pid,evidence['package_id'])
    receipt = ec.require_confirmed(c,pid,contract)
    if (contract['adoption_version'] != evidence['adoption_version']
        or contract['binding_digest'] != evidence['binding_digest']
        or contract['spec_digest'] != evidence['spec_digest']
        or (contract['predecessors'] and not evidence.get('dependency_source_digest'))):
        raise ValueError('Current confirmed engineering contract required')
    src = dict(schema='orbit.engineering-selection-source.v1',
        project_id=pid, job_id=jid, workspace_id=baseline['workspace_id'],
        base_commit=baseline['base_commit'], base_branch=baseline['branch'],
        adoption_version=evidence['adoption_version'], package_id=evidence['package_id'],
        contract_version=receipt['version'], contract_digest=receipt['digest'],
        qa_source_digest=pp.digest(evidence), bound_evidence=evidence, **FLAGS)
    # Confirm all legacy selection/export preflight checks for BOTH candidates.
    # The generated temporary decision is never stored or used as approval.
    job, report = current_inputs(c,pid,src)
    for lane in ('A','B'):
        preflight = decide(job,report,selected=lane,techlead='ORBIT Preflight',
            rationale='Read-only validation of both verified candidate sources.',
            confirmation='SELECT DEV-'+lane+' '+jid)
        verified_bundle(job,report,decision=preflight)
    return src


def current_inputs(c,pid,src):
    evidence=src['bound_evidence']
    jid=src['job_id']
    row=c.execute('SELECT report_json FROM coding_verifications WHERE project_id=? AND job_id=? AND id=?',
                  (pid,jid,evidence['report_id'])).fetchone()
    if not row or hashlib.sha256(row['report_json'].encode()).hexdigest()!=evidence['report_digest']:
        raise ValueError('Verification report changed')
    job=coding_factory.detail(c,jid)
    if (job['project_id']!=pid or job['id']!=jid
        or pp.digest(job['manifest'])!=evidence['manifest_digest']
        or pp.digest([job['review_a'],job['review_b']])!=evidence['review_digest']):
        raise ValueError('Candidate job/review changed')
    return job,json.loads(row['report_json'])


def latest(c,pid,jid):
    return c.execute('SELECT * FROM engineering_candidate_selections WHERE project_id=? AND job_id=? ORDER BY version DESC LIMIT 1',
                     (pid,jid)).fetchone()


def decision_for(c,pid,src,actor,lane,rationale):
    job,report=current_inputs(c,pid,src)
    decision=decide(job,report,selected=lane,techlead=actor,rationale=rationale,
                    confirmation='SELECT DEV-'+lane+' '+src['job_id'])
    verified_bundle(job,report,decision=decision)
    expected=src['bound_evidence']['candidates']
    if {k:{'digest':v['digest'],'test_count':v['test_count']} for k,v in decision['candidates'].items()}!=expected:
        raise ValueError('Candidate source digest mismatch')
    return decision


def validated_receipt(c,pid,row,src):
    snap=json.loads(row['snapshot'])
    if pp.digest(snap)!=row['digest'] or pp.digest(snap['source'])!=row['source_digest']:
        raise ValueError('Selection receipt integrity mismatch')
    if snap['source']!=src:
        raise ValueError('Selection receipt stale')
    decision=snap['decision']
    current=decision_for(c,pid,src,row['actor'],decision['selected'],decision['rationale'])
    if ({k:v for k,v in current.items() if k!='decided_at'}
        !={k:v for k,v in decision.items() if k!='decided_at'}
        or snap!=dict(source=src,decision=decision,scope='development_evidence_only',**FLAGS)):
        raise ValueError('Selection decision integrity mismatch')
    return snap


def record(c,db_path,pid,actor,body,stamp):
    pp.check_role(c,pid,actor,'approve')
    pr.fields(body,('job_id','source_digest','expected_version','selected','rationale','confirmation'))
    jid,lane=body['job_id'],body['selected']
    if (not isinstance(jid,str) or not ID.fullmatch(jid) or lane not in ('A','B')
        or type(body['expected_version']) is not int):
        raise ValueError('Invalid candidate selection identity')
    if body['confirmation']!='SELECT ENGINEERING DEV-'+lane+' '+jid:
        raise ValueError('Explicit engineering candidate selection required')
    src=source(c,db_path,pid,jid)
    digest=pp.digest(src)
    if body['source_digest']!=digest:
        raise ValueError('Current selection source required')
    row=latest(c,pid,jid)
    version=row['version'] if row else 0
    if version!=body['expected_version']:
        raise ValueError('Stale selection version')
    if row:
        old=json.loads(row['snapshot'])
        if pp.digest(old)!=row['digest'] or pp.digest(old['source'])!=row['source_digest']:
            raise ValueError('Invalid historical selection receipt')
    if c.execute('SELECT 1 FROM engineering_candidate_selections WHERE project_id=? AND job_id=? AND source_digest=?',
                 (pid,jid,digest)).fetchone():
        raise ValueError('Current source already selected')
    decision=decision_for(c,pid,src,actor,lane,body['rationale'])
    # Revalidate baseline/source before recording; no filesystem writes.
    if source(c,db_path,pid,jid)!=src:
        raise ValueError('Selection source changed')
    snap=dict(source=src,decision=decision,scope='development_evidence_only',**FLAGS)
    receipt_digest=pp.digest(snap)
    c.execute('SAVEPOINT engineering_selection')
    try:
        c.execute('INSERT INTO engineering_candidate_selections VALUES(?,?,?,?,?,?,?,?)',
            (pid,jid,version+1,digest,pr.canonical(snap),receipt_digest,actor,stamp))
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
            (actor,pid,'engineering_candidate_select','allowed'))
        c.execute('RELEASE engineering_selection')
    except Exception:
        c.execute('ROLLBACK TO engineering_selection')
        c.execute('RELEASE engineering_selection')
        raise
    return dict(version=version+1,digest=receipt_digest,source_digest=digest,selected=lane,
                selected_digest=decision['selected_digest'],**FLAGS)


def view(c,db_path,pid,jid):
    out=dict(project_id=pid,job_id=jid,state='BLOCK',source=None,source_digest=None,
             latest_version=0,receipt=None,**FLAGS)
    row=latest(c,pid,jid)
    if row:
        out['latest_version']=row['version']
        out['state']='STALE'
        try:
            snap=json.loads(row['snapshot'])
            if pp.digest(snap)!=row['digest'] or pp.digest(snap['source'])!=row['source_digest']:
                out['state']='INVALID'
                return out
        except (ValueError,TypeError,KeyError):
            out['state']='INVALID'
            return out
    try:
        src=source(c,db_path,pid,jid)
        out.update(source=src,source_digest=pp.digest(src))
        if not row:
            out['state']='AWAITING_SELECTION'
        elif snap['source']==src:
            try:
                validated_receipt(c,pid,row,src)
            except (ValueError,TypeError,KeyError,AttributeError,PermissionError):
                out['state']='INVALID'
                return out
            out['state']='SELECTED'
            out['receipt']={k:row[k] for k in ('version','digest','actor','created_at')}
            out['receipt'].update(selected=snap['decision']['selected'],
                                  selected_digest=snap['decision']['selected_digest'])
    except (ValueError,TypeError,KeyError,AttributeError,PermissionError,sqlite3.Error):
        pass
    return out
