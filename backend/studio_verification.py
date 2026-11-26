"""QA/QC evidence contract. Human criterion attestations, never automatic acceptance."""
import json
import hashlib
import product_requirements as pr
import project_planning as pp
import studio_coding as sc
import coding_factory
import agent_queue
from web_candidate_selection import compare

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS studio_qa_receipts(
        project_id TEXT NOT NULL REFERENCES projects(id),
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        version INTEGER NOT NULL, snapshot TEXT NOT NULL, digest TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,version))""")

def source(c,pid,jid):
    b=sc.evidence(c,pid,jid)
    if not b or b['state']!='BOUND':raise ValueError('Current bound coding source required')
    q=agent_queue.get(c,pid,b['queue_id'])
    if q['status']!='succeeded':raise ValueError('Successful coding queue required')
    snap=sc.checked_package(c,pid,b['adoption_version'],b['package_id'],b['binding_digest'])
    job=coding_factory.detail(c,jid)
    if job['project_id']!=pid:raise ValueError('Coding project mismatch')
    row=c.execute('SELECT * FROM coding_verifications WHERE project_id=? AND job_id=? ORDER BY rowid DESC LIMIT 1',(pid,jid)).fetchone()
    if not row:raise ValueError('Current sandbox report required')
    report=json.loads(row['report_json'])
    if report['project_id']!=pid or report['job_id']!=jid or row['verdict']!=report['verdict'] or report.get('sandbox',{}).get('network')!='none':
        raise ValueError('Verification provenance mismatch')
    result=compare(job,report)
    return dict(schema='orbit.studio-qa-source.v1',project_id=pid,job_id=jid,queue_id=b['queue_id'],
        package_id=b['package_id'],adoption_version=b['adoption_version'],binding_digest=b['binding_digest'],
        spec_digest=b['spec_digest'],manifest_digest=pp.digest(job['manifest']),
        review_digest=pp.digest([job['review_a'],job['review_b']]),
        report_id=row['id'],report_digest=hashlib.sha256(row['report_json'].encode()).hexdigest(),
        candidates={lane:{'digest':v['digest'],'test_count':v['test_count']} for lane,v in result['candidates'].items()},
        acceptance=snap['acceptance'])

def attest(c,pid,actor,body,stamp):
    pp.check_role(c,pid,actor,'approve')
    pr.fields(body,('job_id','source_digest','expected_version','criteria','confirmation'))
    if body['confirmation']!='ATTEST WORK PACKAGE QA':raise ValueError('Explicit QA attestation required')
    if not isinstance(body['job_id'],str):raise ValueError('Invalid job ID')
    src=source(c,pid,body['job_id'])
    if body['source_digest']!=pp.digest(src):raise ValueError('Current QA source digest required')
    items=body['criteria']
    expected={x['id'] for x in src['acceptance']}
    if not isinstance(items,list) or len(items)!=len(expected):raise ValueError('Exact criterion coverage required')
    seen=set()
    for item in items:
        pr.fields(item,('id','verdict','rationale'))
        if not isinstance(item['id'],str) or item['id'] not in expected or item['id'] in seen:
            raise ValueError('Unknown or duplicate criterion')
        seen.add(item['id'])
        if item['verdict'] not in ('PASS','BLOCK') or not isinstance(item['rationale'],str) or not 20<=len(item['rationale'].strip())<=1200:
            raise ValueError('Explicit criterion verdict and rationale required')
    version=c.execute('SELECT COALESCE(MAX(version),0) FROM studio_qa_receipts WHERE project_id=? AND job_id=?',(pid,body['job_id'])).fetchone()[0]
    if type(body['expected_version']) is not int or version!=body['expected_version']:raise ValueError('Stale QA version')
    receipt=dict(source=src,criteria=items,attestation='human_criterion_review',execution_authorized=False,production_release_authorized=False)
    digest=pp.digest(receipt)
    c.execute('INSERT INTO studio_qa_receipts VALUES(?,?,?,?,?,?,?)',(pid,body['job_id'],version+1,pr.canonical(receipt),digest,actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'studio_qa_attest','allowed'))
    return dict(version=version+1,digest=digest,execution_authorized=False,production_release_authorized=False)

def view(c,pid,jid):
    out=dict(state='BLOCK',source=None,source_digest=None,receipt=None,dependency_completed=False,execution_authorized=False,production_release_authorized=False)
    row=c.execute('SELECT * FROM studio_qa_receipts WHERE project_id=? AND job_id=? ORDER BY version DESC LIMIT 1',(pid,jid)).fetchone()
    try:
        src=source(c,pid,jid)
        out.update(state='AWAITING_HUMAN_QA',source=src,source_digest=pp.digest(src))
        if row:
            receipt=json.loads(row['snapshot'])
            out['receipt']={k:row[k] for k in ('version','digest','actor','created_at')}
            if pp.digest(receipt)!=row['digest']:out['state']='INVALID'
            elif receipt['source']!=src:out['state']='STALE'
            else:
                out['receipt']['criteria']=receipt['criteria']
                out['state']='HUMAN_QA_PASS' if all(x['verdict']=='PASS' for x in receipt['criteria']) else 'HUMAN_QA_BLOCK'
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError):
        if row:out['state']='STALE'
    return out
