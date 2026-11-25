"""Persistent, single-dispatcher task queue. Never automatically replay an in-flight AI call."""
import hashlib
import json
import time
import uuid
import os
from contextlib import contextmanager
from pathlib import Path
import auth_store
import provider_settings as ps

ACTIVE=('queued','running','paused','waiting_approval')
TERMINAL=('succeeded','dead','interrupted','cancelled')
MAX_QUEUED=200

def migrate_requirements_kind(c):
    old=c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_queue'").fetchone()
    if not old or "'planning'" in old[0]:return
    # SQLite cannot alter CHECK constraints. Startup-only atomic rebuild with original IDs,
    # row order and dependent event/queue links preserved. Never disable FK inside a transaction.
    if c.in_transaction:raise RuntimeError('Queue migration requires an idle connection')
    enabled=c.execute('PRAGMA foreign_keys').fetchone()[0]
    sql=old[0].replace("CHECK(kind IN ('pipeline','coding'))","CHECK(kind IN ('pipeline','coding','requirements','planning'))").replace("CHECK(kind IN ('pipeline','coding','requirements'))","CHECK(kind IN ('pipeline','coding','requirements','planning'))")
    if sql==old[0]:raise RuntimeError('Unknown queue schema; migration blocked')
    sql=sql.replace('CREATE TABLE agent_queue(','CREATE TABLE agent_queue_new(',1)
    if 'CREATE TABLE agent_queue_new(' not in sql:
        raise RuntimeError('Unknown queue table declaration')
    c.execute('PRAGMA foreign_keys=OFF')
    try:
        c.execute('BEGIN IMMEDIATE')
        c.execute(sql)
        c.execute('INSERT INTO agent_queue_new(rowid,id,project_id,kind,mode,coding_job_id,actor,priority,dependency_id,retry_of,provider_revision,provider_fingerprint,status,control,reason,checkpoint_stage,attempts,deferrals,available_at,created_at,updated_at) SELECT rowid,id,project_id,kind,mode,coding_job_id,actor,priority,dependency_id,retry_of,provider_revision,provider_fingerprint,status,control,reason,checkpoint_stage,attempts,deferrals,available_at,created_at,updated_at FROM agent_queue')
        c.execute('DROP TABLE agent_queue')
        c.execute('ALTER TABLE agent_queue_new RENAME TO agent_queue')
        c.execute("CREATE UNIQUE INDEX aq_active_kind ON agent_queue(project_id,kind) WHERE status IN ('queued','running','paused','waiting_approval')")
        c.execute("CREATE UNIQUE INDEX aq_one_running_project ON agent_queue(project_id) WHERE status='running'")
        c.execute("CREATE INDEX aq_dispatch ON agent_queue(status,available_at,priority,created_at)")
        if c.execute('PRAGMA foreign_key_check').fetchone():raise RuntimeError('Queue migration foreign key violation')
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:c.execute('PRAGMA foreign_keys='+('ON' if enabled else 'OFF'))

def ensure_schema(c):
    migrate_requirements_kind(c)
    c.execute("""CREATE TABLE IF NOT EXISTS agent_queue(
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
        kind TEXT NOT NULL CHECK(kind IN ('pipeline','coding','requirements','planning')), mode TEXT,
        coding_job_id TEXT UNIQUE, actor TEXT NOT NULL,
        priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 9),
        dependency_id TEXT REFERENCES agent_queue(id), retry_of TEXT REFERENCES agent_queue(id),
        provider_revision INTEGER NOT NULL, provider_fingerprint TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','running','paused','waiting_approval','succeeded','dead','interrupted','cancelled')),
        control TEXT NOT NULL DEFAULT '' CHECK(control IN ('','pause','cancel')),
        reason TEXT NOT NULL DEFAULT '', checkpoint_stage TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, deferrals INTEGER NOT NULL DEFAULT 0,
        available_at INTEGER NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS aq_active_kind ON agent_queue(project_id,kind) WHERE status IN ('queued','running','paused','waiting_approval')")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS aq_one_running_project ON agent_queue(project_id) WHERE status='running'")
    c.execute("CREATE INDEX IF NOT EXISTS aq_dispatch ON agent_queue(status,available_at,priority,created_at)")
    c.execute("""CREATE TABLE IF NOT EXISTS agent_queue_events(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES agent_queue(id),
        status TEXT NOT NULL, reason TEXT NOT NULL, created_at INTEGER NOT NULL)""")

def fingerprint(lanes,routing=None):
    # Bind nonsecret provider settings, including endpoint and presence of credentials.
    base={k:dict(ps.lane_form(v),key_configured=bool(v.api_key)) for k,v in lanes.items()}
    if routing is not None:base['routing_policy']=routing
    return hashlib.sha256(json.dumps(base,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def event(c,identifier,status,reason,now):
    c.execute('INSERT INTO agent_queue_events(task_id,status,reason,created_at) VALUES(?,?,?,?)',(identifier,status,reason,now))

def next_stage(c,pid):
    return c.execute("SELECT stage_id,status FROM tasks WHERE project_id=? AND status NOT IN ('done','approved') ORDER BY position LIMIT 1",(pid,)).fetchone()

def permitted(c,actor,pid):
    return bool(c.execute("""SELECT 1 FROM auth_memberships m JOIN auth_users u ON u.id=m.user_id
          WHERE m.user_id=? AND m.project_id=? AND m.role IN ('owner','developer') AND u.active=1""",(actor,pid)).fetchone())

def active(c,pid,kind):
    return c.execute("SELECT * FROM agent_queue WHERE project_id=? AND kind=? AND status IN ('queued','running','paused','waiting_approval')",(pid,kind)).fetchone()

def get(c,pid,identifier):
    row=c.execute('SELECT * FROM agent_queue WHERE project_id=? AND id=?',(pid,identifier)).fetchone()
    if not row:raise ValueError('Queue task not found')
    return row

def enqueue(c,pid,kind,actor,revision,lanes,*,mode=None,coding_job_id=None,priority=5,dependency_id=None,retry_of=None,now=None,routing=None):
    now=int(time.time()) if now is None else now
    if not permitted(c,actor,pid):raise PermissionError('Project write permission required')
    if kind not in ('pipeline','coding','requirements','planning') or type(priority) is not int or not 0<=priority<=9:raise ValueError('Priority must be 0–9')
    if kind=='pipeline' and (mode not in ('next','all') or coding_job_id is not None):raise ValueError('Invalid pipeline task')
    if kind=='coding' and (not coding_job_id or mode is not None):raise ValueError('Invalid coding task')
    if kind in ('requirements','planning') and (mode is not None or coding_job_id is not None):raise ValueError('Invalid discovery task')
    if active(c,pid,kind):raise ValueError('Project already has an active task of this kind')
    if c.execute("SELECT COUNT(*) FROM agent_queue WHERE status IN ('queued','running','paused','waiting_approval')").fetchone()[0]>=MAX_QUEUED:
        raise ValueError('Queue capacity reached')
    if dependency_id is not None:
        if not isinstance(dependency_id,str):raise ValueError('Invalid dependency')
        dep=get(c,pid,dependency_id)
        if dep['status'] in ('dead','interrupted','cancelled'):raise ValueError('Dependency failed; select a successful or active task')
    if retry_of is not None:get(c,pid,retry_of)
    identifier=uuid.uuid4().hex
    c.execute("""INSERT INTO agent_queue(id,project_id,kind,mode,coding_job_id,actor,priority,dependency_id,retry_of,
         provider_revision,provider_fingerprint,status,available_at,created_at,updated_at)
         VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)""",
         (identifier,pid,kind,mode,coding_job_id,actor,priority,dependency_id,retry_of,revision,fingerprint(lanes,routing),now,now,now))
    event(c,identifier,'queued','accepted',now)
    return identifier

def change(c,row,status,reason,now,**fields):
    allowed={'control','available_at','checkpoint_stage','attempts','deferrals','priority'}
    if set(fields)-allowed:raise ValueError('Invalid queue fields')
    assignments=['status=?','reason=?','updated_at=?']+[k+'=?' for k in fields]
    result=c.execute('UPDATE agent_queue SET '+','.join(assignments)+' WHERE id=? AND status=?',
                     (status,reason,now,*fields.values(),row['id'],row['status']))
    if result.rowcount!=1:raise RuntimeError('Queue transition conflict')
    event(c,row['id'],status,reason,now)

def coding_terminal(c,row,status,reason,stamp):
    if row['kind']=='coding':
        c.execute("UPDATE coding_jobs SET status=?,error=?,updated_at=? WHERE id=? AND status IN ('queued','generating','reviewing')",
                  (status,reason,stamp,row['coding_job_id']))

def fail(c,row,reason,now,stamp):
    change(c,row,'dead',reason,now,control='')
    coding_terminal(c,row,'failed',reason,stamp)

def claim(c,now,stamp):
    # Called under the process-wide DB lock; the server owns an exclusive dispatcher file lock.
    # No external requests in this transaction.
    for row in c.execute("""SELECT q.* FROM agent_queue q JOIN agent_queue d ON d.id=q.dependency_id
                   WHERE q.status='queued' AND d.status IN ('dead','interrupted','cancelled')""").fetchall():
        fail(c,row,'dependency_failed',now,stamp)
    row=c.execute("""SELECT q.* FROM agent_queue q LEFT JOIN agent_queue d ON d.id=q.dependency_id
                   WHERE q.status='queued' AND q.available_at<=? AND (q.dependency_id IS NULL OR d.status='succeeded')
                   AND NOT EXISTS (SELECT 1 FROM agent_queue r WHERE r.project_id=q.project_id AND r.status='running')
                   ORDER BY q.priority DESC,q.created_at,q.rowid LIMIT 1""",(now,)).fetchone()
    if not row:return None
    if not permitted(c,row['actor'],row['project_id']):
        fail(c,row,'permission_revoked',now,stamp);return None
    change(c,row,'running','claimed',now,attempts=row['attempts']+1)
    return get(c,row['project_id'],row['id'])

def defer(c,row,now,stamp):
    # Only before any stage/coding execution. No inference or billing attempt has begun.
    if row['control']=='cancel':
        change(c,row,'cancelled','cancelled_before_dispatch',now,control='');coding_terminal(c,row,'failed','queue_cancelled',stamp)
    elif row['control']=='pause':
        change(c,row,'paused','paused_before_dispatch',now,control='')
    elif row['deferrals']>=2:
        fail(c,row,'resource_retry_exhausted',now,stamp)
    else:
        n=row['deferrals']+1
        change(c,row,'queued','resource_preflight_retry',now,deferrals=n,available_at=now+2**n)

def boundary(c,row,result,now,stamp,stage=None):
    # Finish one dispatch unit. Never interrupt model calls in flight.
    if result=='failed':
        fail(c,row,'execution_failed',now,stamp);return
    if result=='needs_revision':
        fail(c,row,'quality_gate',now,stamp);return
    if row['kind']=='planning':
        persisted=c.execute('SELECT ready FROM planning_runs WHERE queue_id=? AND project_id=?',(row['id'],row['project_id'])).fetchone()
        if result!='ready' or not persisted or not persisted[0]:
            fail(c,row,'planning_completion_mismatch',now,stamp);return
        change(c,row,'succeeded','proposals_ready',now,control='');return
    if row['kind']=='requirements':
        persisted=c.execute('SELECT ready FROM requirement_discovery_runs WHERE queue_id=? AND project_id=?',(row['id'],row['project_id'])).fetchone()
        if result!='ready' or not persisted or not persisted[0]:
            fail(c,row,'requirements_completion_mismatch',now,stamp);return
        change(c,row,'succeeded','ready_for_human_review',now,control='');return
    if row['kind']=='coding':
        # The persisted job is authoritative. Recheck inside the queue completion
        # transaction, not just the dispatcher's earlier result.
        persisted=c.execute('SELECT status FROM coding_jobs WHERE id=? AND project_id=?',
                            (row['coding_job_id'],row['project_id'])).fetchone()
        if result!='ready' or not persisted or persisted[0]!='ready':
            fail(c,row,'coding_completion_mismatch',now,stamp);return
        change(c,row,'succeeded','ready',now,control='',checkpoint_stage=stage);return
    if row['control']=='cancel':
        change(c,row,'cancelled','cancelled_at_boundary',now,control='',checkpoint_stage=stage);return
    if result=='awaiting_approval':
        change(c,row,'waiting_approval','stage_approval_required',now,control='',checkpoint_stage=stage);return
    if row['mode']=='next':
        change(c,row,'succeeded',result,now,control='',checkpoint_stage=stage);return
    if row['control']=='pause':
        change(c,row,'paused','paused_at_boundary',now,control='',checkpoint_stage=stage);return
    if next_stage(c,row['project_id']) is None:
        change(c,row,'succeeded','pipeline_complete',now,control='',checkpoint_stage=stage);return
    change(c,row,'queued','stage_complete',now,control='',checkpoint_stage=stage,available_at=now,deferrals=0)

def control(c,pid,identifier,actor,action,now,stamp,priority=None):
    if not permitted(c,actor,pid):raise PermissionError('Project write permission required')
    row=get(c,pid,identifier);status=row['status']
    if action=='priority':
        if status not in ('queued','paused','waiting_approval') or type(priority) is not int or not 0<=priority<=9:raise ValueError('Priority must be 0–9 for a waiting task')
        change(c,row,status,'priority_changed',now,priority=priority)
    elif action=='pause' and status=='queued':
        change(c,row,'paused','paused_by_user',now)
    elif action=='cancel' and status in ('queued','paused','waiting_approval'):
        change(c,row,'cancelled','cancelled_by_user',now,control='');coding_terminal(c,row,'failed','queue_cancelled',stamp)
    elif action in ('pause','cancel') and status=='running' and row['kind']=='pipeline':
        if row['control']=='cancel' and action=='pause':raise ValueError('Cancellation already requested')
        change(c,row,'running',action+'_requested',now,control=action)
    elif action=='resume' and status in ('paused','waiting_approval'):
        if row['kind']=='pipeline':
            stage=next_stage(c,pid)
            if stage is not None and stage['status']!='queued':raise ValueError('Resolve the stage quality/approval gate before resuming')
        if not permitted(c,row['actor'],pid):raise ValueError('Original submitter no longer has write permission; cancel and submit again')
        if status=='waiting_approval' and row['kind']=='pipeline' and row['mode']=='next' and row['checkpoint_stage']:
            approved=c.execute('SELECT status FROM tasks WHERE project_id=? AND stage_id=?',(pid,row['checkpoint_stage'])).fetchone()
            if not approved or approved[0]!='approved':raise ValueError('Stage approval required')
            change(c,row,'succeeded','stage_approved',now,control='')
        else:change(c,row,'queued','resumed',now,control='',available_at=now)
    else:raise ValueError('Invalid transition; running coding jobs cannot be interrupted')
    return get(c,pid,identifier)

def recover(c,now,stamp):
    # Only on startup after exclusive dispatcher lock acquisition.
    for row in c.execute("SELECT * FROM agent_queue WHERE status='running'").fetchall():
        change(c,row,'interrupted','restart_uncertain_execution',now,control='')
        coding_terminal(c,row,'failed','queue_interrupted',stamp)
        if row['kind']=='pipeline':
            c.execute("UPDATE tasks SET status='needs_revision' WHERE project_id=? AND status IN ('drafting','reviewing','synthesizing')",(row['project_id'],))
    # Legacy pre-queue in-flight work is also uncertain, never replay.
    c.execute("""UPDATE coding_jobs SET status='failed',error='legacy_interrupted',updated_at=?
         WHERE status IN ('queued','generating','reviewing') AND NOT EXISTS
         (SELECT 1 FROM agent_queue q WHERE q.coding_job_id=coding_jobs.id AND q.status IN ('queued','paused','waiting_approval'))""",(stamp,))
    c.execute("UPDATE tasks SET status='needs_revision' WHERE status IN ('drafting','reviewing','synthesizing')")

def view(c,pid):
    fields='id,project_id,kind,mode,coding_job_id,priority,dependency_id,retry_of,provider_revision,status,control,reason,checkpoint_stage,attempts,deferrals,available_at,created_at,updated_at'
    rows=c.execute('SELECT '+fields+',(SELECT j.status FROM coding_jobs j WHERE j.id=agent_queue.coding_job_id AND j.project_id=agent_queue.project_id) AS coding_status FROM agent_queue WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,)).fetchall()
    totals={r[0]:r[1] for r in c.execute('SELECT status,COUNT(*) FROM agent_queue WHERE project_id=? GROUP BY status',(pid,))}
    return {'schema':'orbit.agent-queue.v1','project_id':pid,'tasks':[dict(r) for r in rows],'counts':totals,'truncated':sum(totals.values())>len(rows)}

def history(c,pid,identifier):
    get(c,pid,identifier)
    return [dict(r) for r in c.execute('SELECT status,reason,created_at FROM agent_queue_events WHERE task_id=? ORDER BY seq DESC LIMIT 100',(identifier,))]

@contextmanager
def dispatcher_lock(db_path):
    # Linux/macOS advisory lock held for server lifetime; never unlink the lock file.
    import fcntl
    path=Path(str(Path(db_path).resolve())+'.dispatcher.lock')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another ORBIT dispatcher owns this database') from None
        yield
    finally:os.close(fd)
