"""Explicit coding queue submission for current adopted implementation packages."""
import json
import product_requirements as pr
import project_planning as pp
import work_package_binding as binding
import coding_factory
import agent_queue

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS studio_coding_bindings(
        job_id TEXT PRIMARY KEY REFERENCES coding_jobs(id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        queue_id TEXT NOT NULL UNIQUE REFERENCES agent_queue(id),
        adoption_version INTEGER NOT NULL, package_id TEXT NOT NULL,
        binding_digest TEXT NOT NULL, spec_digest TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE(project_id,adoption_version,package_id),
        FOREIGN KEY(project_id,adoption_version,package_id)
        REFERENCES studio_work_packages(project_id,adoption_version,package_id))""")

def exact_package(c,pid,version,package_id,digest):
    row=c.execute("SELECT * FROM studio_work_packages WHERE project_id=? AND adoption_version=? AND package_id=?",(pid,version,package_id)).fetchone()
    if not row or row['digest']!=digest:raise ValueError('Current work package binding required')
    snap=json.loads(row['snapshot'])
    if pp.digest(snap)!=digest or snap!=binding.source(c,pid,package_id):
        raise ValueError('Stale or invalid work package binding')
    package=snap['package']
    if package['kind']!='implement':raise ValueError('Only implementation work packages may enter Coding Factory')
    return snap

def effective_predecessors(c,pid,v,snap):
    import wbs_dependency_extension as ext
    return ext.predecessors(c,pid,v,snap['package'])

def checked_package(c,pid,version,package_id,digest):
    snap=exact_package(c,pid,version,package_id,digest)
    if effective_predecessors(c,pid,version,snap):
        raise ValueError('Dependent work packages require explicit dependency queue submission')
    return snap

def spec_for(snap):
    # Exact source fields as data, no free-form replacement or truncation.
    data={k:snap[k] for k in ('deliverable_id','requirement','outcome','package','acceptance')}
    spec=pr.canonical(data)
    if not 15<=len(spec)<=coding_factory.MAX_SPEC:raise ValueError('Package specification exceeds coding input limit')
    return spec

def request(c,pid,actor,body):
    pp.check_role(c,pid,actor,'write')
    pr.fields(body,('adoption_version','package_id','binding_digest','confirmation'))
    if body['confirmation']!='QUEUE ADOPTED WORK PACKAGE':raise ValueError('Explicit coding queue confirmation required')
    if type(body['adoption_version']) is not int or not isinstance(body['package_id'],str) or not isinstance(body['binding_digest'],str):
        raise ValueError('Invalid binding identity')
    snap=checked_package(c,pid,body['adoption_version'],body['package_id'],body['binding_digest'])
    if c.execute("SELECT 1 FROM studio_coding_bindings WHERE project_id=? AND adoption_version=? AND package_id=?",(pid,body['adoption_version'],body['package_id'])).fetchone():
        raise ValueError('Work package already submitted')
    return spec_for(snap)

def record(c,pid,actor,body,jid,qid,spec,stamp):
    if request(c,pid,actor,body)!=spec:raise ValueError('Package specification changed')
    c.execute('INSERT INTO studio_coding_bindings VALUES(?,?,?,?,?,?,?,?,?)',(jid,pid,qid,body['adoption_version'],body['package_id'],body['binding_digest'],pp.digest(spec),actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'studio_coding_queue','allowed'))

def lookup(c,pid,jid):
    row=c.execute('SELECT * FROM studio_coding_bindings WHERE job_id=?',(jid,)).fetchone()
    if row and row['project_id']!=pid:raise ValueError('Coding binding project mismatch')
    return row

def checked_job_package(c,pid,row):
    # Legacy root jobs use the unchanged SG.6 contract. Dependent jobs
    # must have a current pinned prerequisite receipt, never queue success.
    snap=exact_package(c,pid,row['adoption_version'],row['package_id'],row['binding_digest'])
    if effective_predecessors(c,pid,row['adoption_version'],snap):
        import dependency_queue
        return dependency_queue.checked_package(c,pid,row)
    return snap

def validate(c,pid,jid,qid):
    row=lookup(c,pid,jid)
    if not row:return None
    q=agent_queue.get(c,pid,qid)
    if row['queue_id']!=qid or q['coding_job_id']!=jid or q['kind']!='coding' or q['actor']!=row['actor'] or q['status']!='running':
        raise ValueError('Coding queue binding mismatch')
    pp.check_role(c,pid,row['actor'],'write')
    snap=checked_job_package(c,pid,row)
    job=c.execute('SELECT spec FROM coding_jobs WHERE id=? AND project_id=?',(jid,pid)).fetchone()
    if not job or job['spec']!=spec_for(snap) or pp.digest(job['spec'])!=row['spec_digest']:
        raise ValueError('Coding specification digest mismatch')
    return snap

def evidence(c,pid,jid):
    row=lookup(c,pid,jid)
    if not row:return None
    result={k:row[k] for k in ('job_id','queue_id','adoption_version','package_id','binding_digest','spec_digest')}
    result['state']='STALE'
    try:
        snap=checked_job_package(c,pid,row)
        job=c.execute('SELECT spec FROM coding_jobs WHERE id=? AND project_id=?',(jid,pid)).fetchone()
        q=agent_queue.get(c,pid,row['queue_id'])
        if job and job['spec']==spec_for(snap) and pp.digest(job['spec'])==row['spec_digest'] and q['coding_job_id']==jid and q['kind']=='coding' and q['actor']==row['actor']:
            result['state']='BOUND'
            if effective_predecessors(c,pid,row['adoption_version'],snap):
                pinned=c.execute('SELECT digest FROM engineering_queue_sources WHERE job_id=? AND project_id=?',(jid,pid)).fetchone()
                if not pinned:raise ValueError('Missing pinned prerequisite evidence')
                result['dependency_source_digest']=pinned['digest']
    except (ValueError,KeyError,TypeError,PermissionError):pass
    return result
