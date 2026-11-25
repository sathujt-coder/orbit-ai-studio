"""Durable PM proposal evidence; no automatic plan adoption."""
import json
import agent_queue as q
import product_requirements as pr
import project_planning as pp
import planning_discovery as pd
import model_provider as mp

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS planning_inputs(
        queue_id TEXT PRIMARY KEY REFERENCES agent_queue(id),
        project_id TEXT NOT NULL REFERENCES projects(id), requirements_version INTEGER NOT NULL,
        requirements_digest TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL,
        FOREIGN KEY(project_id,requirements_version) REFERENCES product_requirements(project_id,version))""")
    c.execute("""CREATE TABLE IF NOT EXISTS planning_runs(
        queue_id TEXT PRIMARY KEY REFERENCES planning_inputs(queue_id),
        project_id TEXT NOT NULL REFERENCES projects(id), evidence TEXT NOT NULL,
        models TEXT NOT NULL, ready INTEGER NOT NULL CHECK(ready IN (0,1)), created_at TEXT NOT NULL)""")

def input_for(c,pid,identifier):
    row=c.execute('SELECT * FROM planning_inputs WHERE queue_id=? AND project_id=?',(identifier,pid)).fetchone()
    if not row:raise ValueError('Planning input not found')
    return row

def enqueue(c,pid,actor,revision,lanes,stamp,*,version,digest,priority=5,dependency_id=None,retry_of=None,routing=None):
    mp.require_distinct_real(lanes)
    if not q.permitted(c,actor,pid):raise PermissionError('Project write permission required')
    source=pp.require_input(c,pid,version,digest);pd.packet(source)
    if retry_of:
        old=input_for(c,pid,retry_of)
        if (old['requirements_version'],old['requirements_digest'])!=(version,digest):
            raise ValueError('Stale planning retry; submit a new run')
    identifier=q.enqueue(c,pid,'planning',actor,revision,lanes,priority=priority,
        dependency_id=dependency_id,retry_of=retry_of,routing=routing)
    c.execute('INSERT INTO planning_inputs VALUES(?,?,?,?,?,?)',
        (identifier,pid,version,digest,pr.canonical(source),stamp))
    return identifier

def checked_input(c,pid,identifier):
    row=q.get(c,pid,identifier)
    if row['kind']!='planning' or row['status']!='running' or not q.permitted(c,row['actor'],pid):
        raise PermissionError('Planning task no longer authorized')
    saved=input_for(c,pid,identifier)
    source=pp.require_input(c,pid,saved['requirements_version'],saved['requirements_digest'])
    if pr.canonical(source)!=saved['snapshot']:raise ValueError('Planning snapshot mismatch')
    return source

def persist(c,pid,identifier,evidence,lanes,stamp):
    source=checked_input(c,pid,identifier)
    mp.require_distinct_real(lanes)
    if (evidence['source_version'],evidence['source_digest'])!=(source['version'],source['digest']):
        raise ValueError('Proposal source mismatch')
    proposals=evidence['proposals']
    if not isinstance(proposals,dict) or not set(proposals)<={'A','B'}:raise ValueError('Invalid proposal lanes')
    validated={lane:pp.validate(doc,source['document']) for lane,doc in proposals.items()}
    for doc in validated.values():
        if any(t['effort_minutes'] is not None for t in doc['tasks']):raise ValueError('AI estimates not supported in P6.2b')
    ready=set(validated)=={'A','B'}
    payload=pr.canonical(dict(evidence,proposals=validated,structurally_ready=ready,semantic_reviewed=False))
    if len(payload.encode())>100000:raise ValueError('Planning evidence too large')
    models={k:dict(provider=v.provider,model=v.model) for k,v in lanes.items()}
    c.execute('INSERT INTO planning_runs VALUES(?,?,?,?,?,?)',(identifier,pid,payload,pr.canonical(models),int(ready),stamp))
    return 'ready' if ready else 'needs_revision'

def latest(c,pid):
    row=c.execute("""SELECT q.id AS queue_id,q.status,q.reason,i.requirements_version,i.requirements_digest,
        i.created_at,r.evidence,r.models,r.ready FROM planning_inputs i JOIN agent_queue q ON q.id=i.queue_id
        LEFT JOIN planning_runs r ON r.queue_id=i.queue_id WHERE i.project_id=? ORDER BY q.rowid DESC LIMIT 1""",(pid,)).fetchone()
    if not row:return None
    data=dict(row);source=pp.current_input(c,pid)
    for key in ('evidence','models'):data[key]=json.loads(data[key]) if data[key] else None
    data['stale']=not source or (data['requirements_version'],data['requirements_digest'])!=(source['version'],source['digest'])
    data['ready']=bool(data['ready'] and data['status']=='succeeded' and not data['stale'])
    return data
