"""P6.2a: approved requirements -> immutable, reviewed planning revisions.
Structural traceability only: no AI generation, execution or automatic estimates.
All mutations run in the server's existing LOCK + database transaction.
"""
import hashlib
import heapq
import json
import re
import product_requirements as pr
import auth_store

MAX_BYTES=26000
MAX_TASKS=150

def digest(value):
    return hashlib.sha256(pr.canonical(value).encode('utf-8')).hexdigest()

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS project_plans(
        project_id TEXT NOT NULL REFERENCES projects(id), version INTEGER NOT NULL,
        requirements_version INTEGER NOT NULL, requirements_digest TEXT NOT NULL,
        document TEXT NOT NULL, digest TEXT NOT NULL, author TEXT NOT NULL,
        created_at TEXT NOT NULL, approved_by TEXT, approved_at TEXT,
        PRIMARY KEY(project_id,version),
        FOREIGN KEY(project_id,requirements_version) REFERENCES product_requirements(project_id,version))""")

def current_input(c,pid):
    row=pr.latest(c,pid)
    if not row or not row['approved_at'] or not row['approved_by']:return None
    document=pr.validate(json.loads(row['document']))
    if document['open_questions'] or digest(document)!=row['digest']:return None
    return dict(version=row['version'],digest=row['digest'],document=document,
        approved_by=row['approved_by'],approved_at=row['approved_at'])

def require_input(c,pid,version,source_digest):
    source=current_input(c,pid)
    if (not source or type(version) is not int or version!=source['version']
            or source_digest!=source['digest']):
        raise ValueError('Current approved requirements version and digest required')
    return source

def latest(c,pid):
    return c.execute('SELECT * FROM project_plans WHERE project_id=? ORDER BY version DESC LIMIT 1',(pid,)).fetchone()

def validate(document,requirements):
    pr.fields(document,('objective','tasks'))
    objective=pr.string(document['objective'],240)
    requirements=pr.validate(requirements)
    required={r['id'] for r in requirements['requirements']}
    raw=document['tasks']
    if not isinstance(raw,list) or not 2<=len(raw)<=MAX_TASKS:
        raise ValueError('Expected 2–150 plan tasks')
    tasks=[];by_id={};builders={r:set() for r in required};verifiers={r:set() for r in required}
    for task in raw:
        pr.fields(task,('id','title','kind','requirements','depends_on','effort_minutes'))
        tid=task['id']
        if not isinstance(tid,str) or not re.fullmatch(r'TASK-[1-9][0-9]{0,3}',tid) or tid in by_id:
            raise ValueError('Invalid or duplicate task ID')
        kind=task['kind']
        if kind not in ('implement','verify'):raise ValueError('Invalid task kind')
        refs=pr.strings(task['requirements'],1,50)
        if len(set(refs))!=len(refs) or not set(refs)<=required:
            raise ValueError('Unknown or duplicate requirement reference')
        deps=pr.strings(task['depends_on'],0,MAX_TASKS)
        if len(set(deps))!=len(deps) or tid in deps:raise ValueError('Invalid task dependencies')
        effort=task['effort_minutes']
        if effort is not None and (type(effort) is not int or not 1<=effort<=60000):
            raise ValueError('Effort must be null or integer minutes 1–60000')
        entry=dict(id=tid,title=pr.string(task['title'],160),kind=kind,
            requirements=sorted(refs),depends_on=sorted(deps),effort_minutes=effort)
        by_id[tid]=entry;tasks.append(entry)
        for rid in refs:(builders if kind=='implement' else verifiers)[rid].add(tid)
    if any(not builders[r] or not verifiers[r] for r in required):
        raise ValueError('Every approved requirement needs implementation and verification tasks')
    outgoing={tid:[] for tid in by_id};degree={}
    for tid,t in by_id.items():
        if not set(t['depends_on'])<=by_id.keys():raise ValueError('Unknown dependency')
        degree[tid]=len(t['depends_on'])
        for dep in t['depends_on']:outgoing[dep].append(tid)
    ready=[tid for tid,n in degree.items() if n==0];heapq.heapify(ready)
    ordered=[];ancestors={}
    while ready:
        tid=heapq.heappop(ready);ordered.append(tid)
        parent=set()
        for dep in by_id[tid]['depends_on']:parent.add(dep);parent.update(ancestors[dep])
        ancestors[tid]=parent
        for child in outgoing[tid]:
            degree[child]-=1
            if degree[child]==0:heapq.heappush(ready,child)
    if len(ordered)!=len(tasks):raise ValueError('Cyclic dependency graph')
    for rid in required:
        for tid in verifiers[rid]:
            if not builders[rid]<=ancestors[tid]:
                raise ValueError('Verification must follow all implementation tasks for '+rid)
    result=dict(objective=objective,tasks=sorted(tasks,key=lambda t:t['id']))
    if len(pr.canonical(result).encode('utf-8'))>MAX_BYTES:raise ValueError('Plan exceeds 26 KB')
    return result

def analyze(document,requirements):
    doc=validate(document,requirements)
    tasks={t['id']:t for t in doc['tasks']}
    pending=set(tasks);order=[];finish={}
    while pending:
        runnable=sorted(tid for tid in pending if set(tasks[tid]['depends_on'])<=finish.keys())
        for tid in runnable:
            t=tasks[tid];effort=t['effort_minutes']
            deps=[finish[d] for d in t['depends_on']]
            finish[tid]=None if effort is None or any(v is None for v in deps) else effort+max(deps,default=0)
            order.append(tid);pending.remove(tid)
    missing=[tid for tid in order if tasks[tid]['effort_minutes'] is None]
    trace={}
    for rid in sorted(r['id'] for r in requirements['requirements']):
        trace[rid]={kind:[tid for tid in order if tasks[tid]['kind']==kind and rid in tasks[tid]['requirements']]
            for kind in ('implement','verify')}
    return dict(task_count=len(tasks),execution_order=order,traceability=trace,unestimated_tasks=missing,
        total_effort_minutes=None if missing else sum(t['effort_minutes'] for t in tasks.values()),
        dependency_lower_bound_minutes=None if missing else max(finish.values()))

def seed_document(requirements):
    req=pr.validate(requirements)
    tasks=[]
    for i,r in enumerate(req['requirements'],1):
        rid=r['id'];build='TASK-'+str(i*2-1);verify='TASK-'+str(i*2)
        tasks.extend([dict(id=build,title='Implement '+rid,kind='implement',requirements=[rid],depends_on=[],effort_minutes=None),
            dict(id=verify,title='Verify '+rid+' against approved acceptance criteria',kind='verify',requirements=[rid],depends_on=[build],effort_minutes=None)])
    return validate(dict(objective='Deliver the approved requirements',tasks=tasks),req)

def check_role(c,pid,actor,role):
    if not auth_store.authorize(c,actor,pid,role):raise PermissionError('Project permission required')

def view(c,pid):
    source=current_input(c,pid);row=latest(c,pid)
    current=None;analysis=None;stale=False
    if row:
        current=dict(row);current['document']=json.loads(current['document'])
        stale=not source or (source['version'],source['digest'])!=(row['requirements_version'],row['requirements_digest'])
        if not stale:
            analysis=analyze(current['document'],source['document'])
    history=[dict(r) for r in c.execute("""SELECT version,requirements_version,requirements_digest,digest,author,created_at,approved_by,approved_at
        FROM project_plans WHERE project_id=? ORDER BY version DESC LIMIT 100""",(pid,))]
    return dict(project_id=pid,requirements_input=source,current=current,history=history,
        input_ready=source is not None,stale=bool(stale),analysis=analysis,
        execution_ready=bool(current and not stale and current['approved_at'] and current['approved_by']
            and digest(current['document'])==current['digest'] and analysis and not analysis['unestimated_tasks']))

def save(c,pid,actor,body,stamp,*,seed=False):
    check_role(c,pid,actor,'write')
    keys=('expected_version','requirements_version','requirements_digest','confirmation') if seed else ('expected_version','requirements_version','requirements_digest','document')
    pr.fields(body,keys)
    if seed and body['confirmation']!='CREATE PLAN DRAFT':raise ValueError('Explicit CREATE PLAN DRAFT required')
    source=require_input(c,pid,body['requirements_version'],body['requirements_digest'])
    row=latest(c,pid);expected=body['expected_version']
    if type(expected) is not int or expected!=(row['version'] if row else 0):
        raise ValueError('Stale plan version; reload before saving')
    doc=seed_document(source['document']) if seed else validate(body['document'],source['document'])
    c.execute("""INSERT INTO project_plans(project_id,version,requirements_version,requirements_digest,document,digest,author,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",(pid,expected+1,source['version'],source['digest'],pr.canonical(doc),digest(doc),actor,stamp))
    return view(c,pid)

def approve(c,pid,actor,body,stamp):
    check_role(c,pid,actor,'approve')
    pr.fields(body,('version','digest','requirements_version','requirements_digest','confirmation'))
    if body['confirmation']!='APPROVE PROJECT PLAN':raise ValueError('Explicit APPROVE PROJECT PLAN required')
    source=require_input(c,pid,body['requirements_version'],body['requirements_digest'])
    row=latest(c,pid)
    if (not row or type(body['version']) is not int or body['version']!=row['version'] or body['digest']!=row['digest']
            or row['requirements_version']!=source['version'] or row['requirements_digest']!=source['digest']):
        raise ValueError('Current plan and requirements version/digest required')
    if row['approved_at']:raise ValueError('Plan already approved')
    doc=json.loads(row['document'])
    if digest(doc)!=row['digest']:raise ValueError('Plan digest mismatch')
    if analyze(doc,source['document'])['unestimated_tasks']:raise ValueError('Estimate all tasks before approval')
    c.execute('UPDATE project_plans SET approved_by=?,approved_at=? WHERE project_id=? AND version=?',(actor,stamp,pid,row['version']))
    return view(c,pid)
