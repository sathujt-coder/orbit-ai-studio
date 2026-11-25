"""Unified read-only workflow contracts, not dispatch or adoption authority."""
import hashlib
import json
import agent_queue
import coding_factory
import product_requirements
import project_planning
import work_breakdown
from web_candidate_selection import compare

def contract(row,keys):
    return {k:row.get(k) for k in keys} if row else None

def view(c,pid):
    prd=product_requirements.view(c,pid)
    current=prd['current']
    try:approved=project_planning.current_input(c,pid)
    except (ValueError,TypeError,KeyError):approved=None
    requirements=dict(state='APPROVED' if approved else 'UNAPPROVED' if current else 'MISSING',
        revision=contract(current,('version','digest','approved_at','approved_by')),
        approved=contract(approved,('version','digest','approved_at','approved_by')))
    try:
        w=work_breakdown.view(c,pid)
        a=w['adoption'];adopted=a['current']
        planning=dict(state=a['status'],stale=a['stale'],reason=a['reason'],
            wbs=contract(w['current'],('version','digest','requirements_version','requirements_digest','queue_id')),
            adoption=contract(adopted,('version','digest','bundle_digest','review_id','evidence_digest','approved_at','approved_by')),
            binding=a['binding'],execution_authorized=False)
    except (ValueError,TypeError,KeyError):
        planning=dict(state='invalid_evidence',stale=True,reason='Planning evidence could not be validated',
            wbs=None,adoption=None,binding=None,execution_authorized=False)
    queue=agent_queue.view(c,pid)
    jobs=[]
    for item in coding_factory.list_jobs(c,pid):
        jid=item['id']
        q=c.execute("SELECT id,status,dependency_id,retry_of FROM agent_queue WHERE project_id=? AND coding_job_id=? AND kind='coding'",(pid,jid)).fetchone()
        rec=dict(job_id=jid,status=item['status'],queue=dict(q) if q else None,
                 planning_binding='NOT_RECORDED',manifest_digest=None,verification=None,execution_authorized=False)
        report=c.execute("SELECT id,verdict,report_json,created_at FROM coding_verifications WHERE project_id=? AND job_id=? ORDER BY rowid DESC LIMIT 1",(pid,jid)).fetchone()
        try:
            job=coding_factory.detail(c,jid)
            if job['project_id']!=pid:raise ValueError('Project mismatch')
            if job['manifest']:rec['manifest_digest']=project_planning.digest(job['manifest'])
            if report:
                rec['verification']=dict(id=report['id'],verdict=report['verdict'],created_at=report['created_at'],
                    digest=hashlib.sha256(report['report_json'].encode()).hexdigest(),gate=None,state='BLOCK',candidates=None)
                data=json.loads(report['report_json'])
                rec['verification']['gate']=data.get('gate')
                if data.get('project_id')!=pid or data.get('job_id')!=jid:raise ValueError('Verification scope mismatch')
                result=compare(job,data)
                rec['verification'].update(state='VERIFIED_CANDIDATES',candidates={k:contract(v,('digest','test_count')) for k,v in result['candidates'].items()})
        except (ValueError,TypeError,KeyError,AttributeError,PermissionError):
            if rec['verification']:rec['verification']['state']='BLOCK'
        jobs.append(rec)
    return dict(schema='orbit.studio-workflow.v1',project_id=pid,requirements=requirements,planning=planning,
        coding_jobs=jobs,queue=queue,next_checkpoint='APPROVE_PRD' if not approved else 'ADOPT_PLANNING' if planning['state']!='adopted' else 'WORK_PACKAGE_BINDING_REQUIRED',
        execution_authorized=False,automatic_dispatch=False,production_release_authorized=False,
        note='Existing coding jobs are not bound to adopted work packages. Verification is not release approval.')
