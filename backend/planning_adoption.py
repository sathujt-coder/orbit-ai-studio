"""Explicit human approval and immutable adoption of a reviewed planning bundle."""
import json
import product_requirements as pr
import project_planning as pp
import planning_review as review
import agent_queue as q
import auth_store

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS planning_adoptions(
        project_id TEXT NOT NULL REFERENCES projects(id),version INTEGER NOT NULL,
        bundle_digest TEXT NOT NULL,review_id TEXT NOT NULL REFERENCES planning_review_runs(queue_id),
        evidence_digest TEXT NOT NULL,snapshot TEXT NOT NULL,digest TEXT NOT NULL,
        approved_by TEXT NOT NULL,approved_at TEXT NOT NULL,
        PRIMARY KEY(project_id,version),UNIQUE(project_id,bundle_digest))""")

def latest(c,pid):
    return c.execute('SELECT * FROM planning_adoptions WHERE project_id=? ORDER BY version DESC LIMIT 1',(pid,)).fetchone()

def candidate(c,pid,w):
    state=review.view(c,pid,w);r=state['latest']
    if not state['quality_ready'] or not r:raise ValueError('Current cross-review quality gate required')
    snap=review.snapshot(c,pid,w)
    # The original proposal and review jobs must both be successful and project scoped.
    for identifier,kind in ((snap['proposal_run'],'planning'),(r['queue_id'],'planning_review')):
        job=q.get(c,pid,identifier)
        if job['kind']!=kind or job['status']!='succeeded':raise ValueError('Planning queue dependency not successful')
    if q.active(c,pid,'planning') or q.active(c,pid,'decomposition') or q.active(c,pid,'planning_review'):
        raise ValueError('Planning work still active')
    return dict(bundle=snap,bundle_digest=pp.digest(snap),review_id=r['queue_id'],
        evidence_digest=r['evidence_digest'],review_evidence=r['evidence'])

def view(c,pid,w):
    row=latest(c,pid);current=None;stale=False;binding=None;reason=None
    try:
        data=candidate(c,pid,w)
        binding={k:data[k] for k in ('bundle_digest','review_id','evidence_digest')}
    except (ValueError,KeyError,TypeError) as err:reason=str(err)
    if row:
        current=dict(row);stale=True
        try:
            current['snapshot']=json.loads(row['snapshot'])
            stale=not binding or any(row[k]!=v for k,v in binding.items()) or pp.digest(current['snapshot'])!=row['digest'] or current['snapshot']!=data
        except (ValueError,KeyError,TypeError):current['snapshot']=None
    duplicate=bool(binding and c.execute('SELECT 1 FROM planning_adoptions WHERE project_id=? AND bundle_digest=?',(pid,binding['bundle_digest'])).fetchone())
    can_adopt=bool(binding and not duplicate)
    status=('adopted' if current and not stale else 'stale' if current else 'ready_for_human_approval' if can_adopt else 'blocked')
    return dict(current=current,stale=bool(stale),binding=binding,can_adopt=can_adopt,status=status,
        reason=reason,duplicate=duplicate,execution_authorized=False,
        history=[dict(x) for x in c.execute("""SELECT version,bundle_digest,review_id,evidence_digest,digest,approved_by,approved_at
            FROM planning_adoptions WHERE project_id=? ORDER BY version DESC LIMIT 50""",(pid,))])

def adopt(c,pid,actor,body,stamp,w):
    pp.check_role(c,pid,actor,'approve')
    pr.fields(body,('expected_version','bundle_digest','review_id','evidence_digest','confirmation'))
    if body['confirmation']!='APPROVE AND ADOPT PLANNING BUNDLE':raise ValueError('Explicit human approval and adoption required')
    data=candidate(c,pid,w)
    if any(body[k]!=data[k] for k in ('bundle_digest','review_id','evidence_digest')):
        raise ValueError('Current reviewed bundle and evidence binding required')
    row=latest(c,pid);version=body['expected_version']
    if type(version) is not int or version!=(row['version'] if row else 0):raise ValueError('Stale adoption version')
    if c.execute('SELECT 1 FROM planning_adoptions WHERE project_id=? AND bundle_digest=?',(pid,data['bundle_digest'])).fetchone():
        raise ValueError('Bundle already adopted')
    payload=pr.canonical(data)
    if len(payload.encode())>160000:raise ValueError('Adoption snapshot exceeds 160 KB')
    c.execute('INSERT INTO planning_adoptions VALUES(?,?,?,?,?,?,?,?,?)',
        (pid,version+1,data['bundle_digest'],data['review_id'],data['evidence_digest'],payload,pp.digest(data),actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
        (actor,pid,'planning_adopt:'+str(version+1),'allowed'))
    return view(c,pid,w)
