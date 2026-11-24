"""Project-scoped durable AI discovery evidence; adoption is explicit and never approves."""
import json
import hashlib
import product_requirements as pr
import agent_queue
import model_provider as mp

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS requirement_discovery_inputs(
        queue_id TEXT PRIMARY KEY REFERENCES agent_queue(id), project_id TEXT NOT NULL REFERENCES projects(id),
        idea TEXT NOT NULL, base_version INTEGER NOT NULL, created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS requirement_discovery_runs(
        queue_id TEXT PRIMARY KEY REFERENCES requirement_discovery_inputs(queue_id),
        project_id TEXT NOT NULL REFERENCES projects(id), evidence TEXT NOT NULL,
        models TEXT NOT NULL, digest TEXT NOT NULL, ready INTEGER NOT NULL CHECK(ready IN (0,1)),
        created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS requirement_discovery_adoptions(
        queue_id TEXT PRIMARY KEY REFERENCES requirement_discovery_runs(queue_id),
        project_id TEXT NOT NULL, version INTEGER NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(project_id,version) REFERENCES product_requirements(project_id,version))""")

def enqueue(c,pid,actor,revision,lanes,stamp,*,priority=5,dependency_id=None,retry_of=None,routing=None):
    mp.require_distinct_real(lanes)
    project=c.execute('SELECT idea FROM projects WHERE id=?',(pid,)).fetchone()
    if not project:raise ValueError('Project not found')
    current=pr.latest(c,pid)
    identifier=agent_queue.enqueue(c,pid,'requirements',actor,revision,lanes,priority=priority,
        dependency_id=dependency_id,retry_of=retry_of,routing=routing)
    c.execute('INSERT INTO requirement_discovery_inputs VALUES(?,?,?,?,?)',
        (identifier,pid,pr.string(project[0],10000),current['version'] if current else 0,stamp))
    return identifier

def input_for(c,pid,identifier):
    row=c.execute('SELECT * FROM requirement_discovery_inputs WHERE project_id=? AND queue_id=?',(pid,identifier)).fetchone()
    if not row:raise ValueError('Discovery input not found')
    return row

def persist(c,pid,identifier,evidence,lanes,stamp):
    row=agent_queue.get(c,pid,identifier)
    if row['kind']!='requirements' or row['status']!='running':raise ValueError('Discovery task not running')
    if not agent_queue.permitted(c,row['actor'],pid):raise PermissionError('Project write permission revoked')
    input_for(c,pid,identifier)
    mp.require_distinct_real(lanes)
    document=pr.validate(evidence['document'])
    ready=bool(evidence['ready_for_human_review'] and not evidence['final_review']['blocking'] and not document['open_questions'])
    payload=pr.canonical(evidence)
    if len(payload.encode())>250000:raise ValueError('Discovery evidence too large')
    digest=hashlib.sha256(pr.canonical(document).encode()).hexdigest()
    models={k:dict(provider=v.provider,model=v.model) for k,v in lanes.items()}
    c.execute('INSERT INTO requirement_discovery_runs VALUES(?,?,?,?,?,?,?)',
        (identifier,pid,payload,pr.canonical(models),digest,int(ready),stamp))
    return 'ready' if ready else 'needs_revision'

def latest(c,pid):
    row=c.execute("""SELECT q.id AS queue_id,q.status,q.reason,i.base_version,i.created_at,
        r.evidence,r.models,r.digest,r.ready,a.version AS adopted_version
        FROM requirement_discovery_inputs i JOIN agent_queue q ON q.id=i.queue_id
        LEFT JOIN requirement_discovery_runs r ON r.queue_id=q.id
        LEFT JOIN requirement_discovery_adoptions a ON a.queue_id=q.id
        WHERE i.project_id=? ORDER BY q.rowid DESC LIMIT 1""",(pid,)).fetchone()
    if not row:return None
    data=dict(row)
    for key in ('evidence','models'):
        data[key]=json.loads(data[key]) if data[key] else None
    data['ready']=bool(data['ready'])
    current=pr.latest(c,pid)
    data['can_adopt']=bool(data['status']=='succeeded' and data['ready'] and data['adopted_version'] is None
        and data['base_version']==(current['version'] if current else 0))
    return data

def adopt(c,pid,actor,body,stamp):
    pr.fields(body,('queue_id','digest','expected_version','confirmation'))
    if body['confirmation']!='ADOPT AI REQUIREMENTS':raise ValueError('Explicit adoption required')
    if not agent_queue.permitted(c,actor,pid):raise PermissionError('Project write permission required')
    if type(body['expected_version']) is not int:raise ValueError('Invalid version')
    row=latest(c,pid)
    if not row or body['queue_id']!=row['queue_id'] or not row['can_adopt'] or row['digest']!=body['digest'] or row['base_version']!=body['expected_version']:
        raise ValueError('Current reviewed discovery and matching base version/digest required')
    data=pr.save(c,pid,actor,dict(expected_version=body['expected_version'],document=row['evidence']['document']),stamp)
    if data['current']['digest']!=row['digest']:raise RuntimeError('Discovery digest mismatch')
    c.execute('INSERT INTO requirement_discovery_adoptions VALUES(?,?,?,?,?)',
        (row['queue_id'],pid,data['current']['version'],actor,stamp))
    return data
