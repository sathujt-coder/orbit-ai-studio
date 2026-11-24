"""Project-scoped durable AI discovery evidence; adoption is explicit and never approves."""
import json
import hashlib
import product_requirements as pr
import agent_queue
import model_provider as mp
import requirements_scope as sc

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS requirement_discovery_inputs(
        queue_id TEXT PRIMARY KEY REFERENCES agent_queue(id), project_id TEXT NOT NULL REFERENCES projects(id),
        idea TEXT NOT NULL, base_version INTEGER NOT NULL, created_at TEXT NOT NULL)""")
    if 'scope_contract' not in {r[1] for r in c.execute('PRAGMA table_info(requirement_discovery_inputs)')}:
        c.execute('ALTER TABLE requirement_discovery_inputs ADD COLUMN scope_contract TEXT')
    c.execute("""CREATE TABLE IF NOT EXISTS requirement_discovery_runs(
        queue_id TEXT PRIMARY KEY REFERENCES requirement_discovery_inputs(queue_id),
        project_id TEXT NOT NULL REFERENCES projects(id), evidence TEXT NOT NULL,
        models TEXT NOT NULL, digest TEXT NOT NULL, ready INTEGER NOT NULL CHECK(ready IN (0,1)),
        created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS requirement_discovery_adoptions(
        queue_id TEXT PRIMARY KEY REFERENCES requirement_discovery_runs(queue_id),
        project_id TEXT NOT NULL, version INTEGER NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(project_id,version) REFERENCES product_requirements(project_id,version))""")

def enqueue(c,pid,actor,revision,lanes,stamp,*,priority=5,dependency_id=None,retry_of=None,routing=None,scope_contract=None):
    mp.require_distinct_real(lanes)
    project=c.execute('SELECT idea FROM projects WHERE id=?',(pid,)).fetchone()
    if not project:raise ValueError('Project not found')
    if retry_of and scope_contract is None:
        prior=input_for(c,pid,retry_of)['scope_contract']
        scope_contract=json.loads(prior) if prior else None
    idea=pr.string(project[0],10000)
    contract=sc.validate(idea,scope_contract)
    current=pr.latest(c,pid)
    identifier=agent_queue.enqueue(c,pid,'requirements',actor,revision,lanes,priority=priority,
        dependency_id=dependency_id,retry_of=retry_of,routing=routing)
    c.execute('INSERT INTO requirement_discovery_inputs(queue_id,project_id,idea,base_version,created_at,scope_contract) VALUES(?,?,?,?,?,?)',
        (identifier,pid,idea,current['version'] if current else 0,stamp,pr.canonical(contract)))
    return identifier

def input_for(c,pid,identifier):
    row=c.execute('SELECT * FROM requirement_discovery_inputs WHERE project_id=? AND queue_id=?',(pid,identifier)).fetchone()
    if not row:raise ValueError('Discovery input not found')
    return row

def quality_gate(evidence,contract):
    """Recompute content and convergence independently at storage/adoption."""
    if contract is None:return False,None,None
    document=pr.validate(evidence['document'])
    findings=sc.assess(document,contract)
    revision=evidence.get('quality_revision')
    progress=None
    try:
        if revision is not None:
            progress=sc.convergence(revision['before_document'],document,contract,
                revision['before_review'],evidence['final_review'])
        elif evidence.get('scope_recheck'):
            initial=evidence['initial_final_review']
            progress=sc.convergence(initial['document'],document,contract,
                initial['review'],evidence['final_review'])
    except (KeyError,TypeError,ValueError):
        return False,findings,None
    ready=bool(findings['passed'] and evidence['ready_for_human_review']
        and not evidence.get('no_op_repair') and not evidence['final_review']['blocking']
        and not document['open_questions'] and (progress is None or progress['passed']))
    return ready,findings,progress

def persist(c,pid,identifier,evidence,lanes,stamp):
    row=agent_queue.get(c,pid,identifier)
    if row['kind']!='requirements' or row['status']!='running':raise ValueError('Discovery task not running')
    if not agent_queue.permitted(c,row['actor'],pid):raise PermissionError('Project write permission revoked')
    snapshot=input_for(c,pid,identifier)
    mp.require_distinct_real(lanes)
    document=pr.validate(evidence['document'])
    contract=sc.validate(snapshot['idea'],json.loads(snapshot['scope_contract'])) if snapshot['scope_contract'] else None
    ready,findings,progress=quality_gate(evidence,contract)
    final_mismatch=bool(findings and sc.hard_issues(findings) and not evidence['final_review']['blocking'])
    evidence=dict(evidence,scope_contract=contract,scope_findings=findings,convergence=progress,
        false_approval_detected=bool(evidence.get('false_approval_detected') or final_mismatch),
        ready_for_human_review=ready)
    payload=pr.canonical(evidence)
    if len(payload.encode())>250000:raise ValueError('Discovery evidence too large')
    digest=hashlib.sha256(pr.canonical(document).encode()).hexdigest()
    models={k:dict(provider=v.provider,model=v.model) for k,v in lanes.items()}
    c.execute('INSERT INTO requirement_discovery_runs VALUES(?,?,?,?,?,?,?)',
        (identifier,pid,payload,pr.canonical(models),digest,int(ready),stamp))
    return 'ready' if ready else 'needs_revision'

def latest(c,pid):
    row=c.execute("""SELECT q.id AS queue_id,q.status,q.reason,i.base_version,i.created_at,
        r.evidence,r.models,r.digest,r.ready,i.scope_contract,a.version AS adopted_version
        FROM requirement_discovery_inputs i JOIN agent_queue q ON q.id=i.queue_id
        LEFT JOIN requirement_discovery_runs r ON r.queue_id=q.id
        LEFT JOIN requirement_discovery_adoptions a ON a.queue_id=q.id
        WHERE i.project_id=? ORDER BY q.rowid DESC LIMIT 1""",(pid,)).fetchone()
    if not row:return None
    data=dict(row)
    for key in ('evidence','models','scope_contract'):
        data[key]=json.loads(data[key]) if data[key] else None
    data['ready']=bool(data['ready'])
    current=pr.latest(c,pid)
    data['can_adopt']=bool(data['status']=='succeeded' and data['ready'] and data['adopted_version'] is None
        and data['scope_contract'] is not None and data['base_version']==(current['version'] if current else 0))
    if data['can_adopt']:
        snapshot=input_for(c,pid,data['queue_id'])
        contract=sc.validate(snapshot['idea'],data['scope_contract'])
        data['can_adopt']=quality_gate(data['evidence'],contract)[0]
    return data

def adopt(c,pid,actor,body,stamp):
    pr.fields(body,('queue_id','digest','expected_version','confirmation'))
    if body['confirmation']!='ADOPT AI REQUIREMENTS':raise ValueError('Explicit adoption required')
    if not agent_queue.permitted(c,actor,pid):raise PermissionError('Project write permission required')
    if type(body['expected_version']) is not int:raise ValueError('Invalid version')
    row=latest(c,pid)
    if not row or body['queue_id']!=row['queue_id'] or not row['can_adopt'] or row['digest']!=body['digest'] or row['base_version']!=body['expected_version']:
        raise ValueError('Current reviewed discovery and matching base version/digest required')
    snapshot=input_for(c,pid,row['queue_id'])
    contract=sc.validate(snapshot['idea'],row['scope_contract'])
    if not quality_gate(row['evidence'],contract)[0]:
        raise ValueError('Scope contract or convergence gate failed')
    data=pr.save(c,pid,actor,dict(expected_version=body['expected_version'],document=row['evidence']['document']),stamp)
    if data['current']['digest']!=row['digest']:raise RuntimeError('Discovery digest mismatch')
    c.execute('INSERT INTO requirement_discovery_adoptions VALUES(?,?,?,?,?)',
        (row['queue_id'],pid,data['current']['version'],actor,stamp))
    return data
