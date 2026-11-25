"""Durable source-bound AI decomposition evidence, project-scoped."""
import json
from urllib.parse import urlsplit
import product_requirements as pr
import project_planning as pp
import work_breakdown as w
import wbs_decomposition as d
import agent_queue as q

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS decomposition_inputs(
        queue_id TEXT PRIMARY KEY REFERENCES agent_queue(id),project_id TEXT NOT NULL REFERENCES projects(id),
        wbs_version INTEGER NOT NULL,wbs_digest TEXT NOT NULL,snapshot TEXT NOT NULL,
        FOREIGN KEY(project_id,wbs_version) REFERENCES work_breakdowns(project_id,version))""")
    c.execute("""CREATE TABLE IF NOT EXISTS decomposition_runs(
        queue_id TEXT PRIMARY KEY REFERENCES decomposition_inputs(queue_id),project_id TEXT NOT NULL REFERENCES projects(id),
        evidence TEXT NOT NULL,model TEXT NOT NULL,ready INTEGER NOT NULL CHECK(ready IN (0,1)),created_at TEXT NOT NULL)""")

def local_lane(lanes,lane):
    model=lanes[lane];url=urlsplit(model.base_url)
    if model.provider!='ollama' or url.hostname not in ('127.0.0.1','localhost','::1') or model.api_key or 'cloud' in model.model.lower():
        raise ValueError('Decomposition requires local loopback Ollama without API key')
    if model.context_window<8192 or model.max_tokens<d.MAX_OUTPUT:raise ValueError('Decomposition requires 8192 context and 1536 output tokens')
    return model

def snapshot(c,pid,version,digest):
    row=w.latest(c,pid)
    if not row or type(version) is not int or row['version']!=version or row['digest']!=digest:
        raise ValueError('Current WBS version and digest required')
    src=w.current_source(c,pid,row['lane'])
    if any(row[k]!=v for k,v in w.bindings(src).items()):raise ValueError('Stale WBS source')
    doc=json.loads(row['document'])
    if pp.digest(doc)!=digest:raise ValueError('WBS digest mismatch')
    d.blank(src,doc)
    return dict(source=src,document=doc,wbs_version=version,wbs_digest=digest)

def input_for(c,pid,identifier):
    row=c.execute('SELECT * FROM decomposition_inputs WHERE queue_id=? AND project_id=?',(identifier,pid)).fetchone()
    if not row:raise ValueError('Decomposition input not found')
    return row

def enqueue(c,pid,actor,revision,lanes,body,*,priority=5,dependency_id=None,retry_of=None,routing=None):
    pr.fields(body,('wbs_version','wbs_digest','confirmation'))
    if body['confirmation']!='RUN AI DECOMPOSITION':raise ValueError('Explicit RUN AI DECOMPOSITION required')
    if not q.permitted(c,actor,pid):raise PermissionError('Project write permission required')
    snap=snapshot(c,pid,body['wbs_version'],body['wbs_digest'])
    local_lane(lanes,snap['source']['lane'])
    if retry_of:
        old=input_for(c,pid,retry_of)
        if old['snapshot']!=pr.canonical(snap):raise ValueError('Stale decomposition retry; submit a new task')
    identifier=q.enqueue(c,pid,'decomposition',actor,revision,lanes,priority=priority,dependency_id=dependency_id,retry_of=retry_of,routing=routing)
    c.execute('INSERT INTO decomposition_inputs VALUES(?,?,?,?,?)',(identifier,pid,snap['wbs_version'],snap['wbs_digest'],pr.canonical(snap)))
    return identifier

def checked_input(c,pid,identifier):
    row=q.get(c,pid,identifier)
    if row['kind']!='decomposition' or row['status']!='running' or not q.permitted(c,row['actor'],pid):
        raise PermissionError('Decomposition no longer authorized')
    saved=input_for(c,pid,identifier);snap=snapshot(c,pid,saved['wbs_version'],saved['wbs_digest'])
    if saved['snapshot']!=pr.canonical(snap):raise ValueError('Decomposition snapshot mismatch')
    return snap

def ledger_valid(c,pid,identifier,evidence,provenance):
    # Independently match every audited attempt to the durable usage ledger.
    lane=provenance['lane']
    if lane not in ('A','B') or provenance['provider']!='ollama':return False
    phases=[a['phase'] for b in evidence['history'] for a in b['attempts']]
    calls=[dict(x) for x in c.execute('SELECT agent_id,lane,provider,model,purpose,status,coverage,total_tokens FROM ai_usage WHERE project_id=? AND run_id=? ORDER BY rowid',(pid,identifier))]
    return bool(phases and len(calls)==len(phases) and [x['purpose'] for x in calls]==phases and all(
        x['agent_id']=='wbs-'+lane and x['lane']==lane and x['provider']==provenance['provider'] and x['model']==provenance['model']
        and x['status']=='ok' and x['coverage']=='complete' and (x['total_tokens'] or 0)>0 for x in calls))

def persist(c,pid,identifier,evidence,model,stamp):
    snap=checked_input(c,pid,identifier);gate=d.gate(evidence,snap['source'],snap['document'])
    lane=snap['source']['lane'];provenance=dict(lane=lane,provider=model.provider,model=model.model)
    ledger=ledger_valid(c,pid,identifier,evidence,provenance)
    ready=bool(gate['ready'] and ledger)
    payload=pr.canonical({**evidence,**gate,'ready':ready,'ledger_valid':ledger,'source':w.bindings(snap['source']),
        'wbs_version':snap['wbs_version'],'wbs_digest':snap['wbs_digest'],'origin':'model_generated'})
    if len(payload.encode())>400000:raise ValueError('Decomposition evidence exceeds 400 KB')
    c.execute('INSERT INTO decomposition_runs VALUES(?,?,?,?,?,?)',(identifier,pid,payload,pr.canonical(provenance),int(ready),stamp))
    return 'ready' if ready else 'needs_revision'

def workflow_guidance(state):
    """Read-only workflow guidance, not model qualification or authorization.

    An explicit queue retry uses the current configured local lane and retains
    the original source snapshot. It never changes providers automatically.
    """
    if state['stale']:
        action='refresh_source'
    elif state['ready']:
        action='human_review'
    elif state['status'] in ('dead','interrupted','cancelled'):
        action='operator_review'
    elif state['status'] in ('queued','running','paused','waiting_approval'):
        action='wait_for_queue'
    else:
        action='operator_review'
    return dict(schema='orbit.wbs-workflow-guidance.v1',next_action=action,
        operator_retry_available=action=='operator_review' and state['status'] in ('dead','interrupted','cancelled'),
        automatic_fallback=False,automatic_adoption=False,model_qualification='not_assessed')

def latest(c,pid):
    row=c.execute("""SELECT q.id AS queue_id,q.status,q.reason,i.wbs_version,i.wbs_digest,i.snapshot,
        r.evidence,r.model,r.ready FROM decomposition_inputs i JOIN agent_queue q ON q.id=i.queue_id
        LEFT JOIN decomposition_runs r ON r.queue_id=i.queue_id WHERE i.project_id=? ORDER BY q.rowid DESC LIMIT 1""",(pid,)).fetchone()
    if not row:return None
    data=dict(row);saved=data.pop('snapshot');data['stale']=True
    data['ready']=bool(data['ready'] and data['status']=='succeeded')
    try:
        snap=snapshot(c,pid,data['wbs_version'],data['wbs_digest'])
        data['stale']=pr.canonical(snap)!=saved
        for key in ('evidence','model'):data[key]=json.loads(data[key]) if data[key] else None
        if data['ready'] and not data['stale']:
            e=data['evidence'];g=d.gate(e,snap['source'],snap['document'])
            data['ready']=bool(g['ready'] and e.get('ready') is True and e.get('ledger_valid') is True
                and e.get('source')==w.bindings(snap['source']) and e.get('candidate_digest')==g['candidate_digest']
                and data['model']['lane']==snap['source']['lane'] and ledger_valid(c,pid,data['queue_id'],e,data['model']))
    except (ValueError,KeyError,TypeError):data['ready']=False
    data['ready']=bool(data['ready'] and not data['stale'])
    # Always decode for UI even when stale, without implying current readiness.
    for key in ('evidence','model'):
        if isinstance(data[key],str):
            try:data[key]=json.loads(data[key])
            except ValueError:data[key]=None
    data['workflow']=workflow_guidance(data)
    return data
