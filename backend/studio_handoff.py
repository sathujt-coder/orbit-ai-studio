"""Read-only evidence of legacy stage handoff eligibility; never dispatch authority.

Durable receipts bind exact legacy context, not production approval.
Prepared context and completed draft calls are deliberately distinct evidence.
"""
import hashlib
import json
import github_bridge

def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS studio_handoff_receipts(
        project_id TEXT NOT NULL REFERENCES projects(id), stage_id TEXT NOT NULL,
        run_id TEXT NOT NULL, snapshot TEXT NOT NULL, digest TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(project_id,stage_id,run_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS studio_handoff_drafts(
        project_id TEXT NOT NULL, stage_id TEXT NOT NULL, run_id TEXT NOT NULL,
        lane TEXT NOT NULL CHECK(lane IN ('A','B')), created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,stage_id,run_id,lane),
        FOREIGN KEY(project_id,stage_id,run_id) REFERENCES studio_handoff_receipts(project_id,stage_id,run_id))""")

def prepare(c,pid,stages,sid,run_id,mode,stamp):
    """Build and persist exactly the context returned to both draft calls."""
    tasks=c.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY position',(pid,)).fetchall()
    roles=view(c,pid,stages,tasks)['roles']
    role=next(x for x in roles if x['stage_id']==sid)
    sources=role['inputs']
    if any(x['status']!='reviewed_output' for x in sources):
        raise ValueError('Handoff source quality gate blocked')
    chunks=[]
    for source in sources:
        row=c.execute("SELECT content FROM artifacts WHERE project_id=? AND id=? AND stage_id=? AND run_id=? AND kind='final'",
            (pid,source['artifact_id'],source['stage_id'],source['run_id'])).fetchone()
        if not row or digest(row['content'])!=source['content_digest']:
            raise ValueError('Handoff source changed')
        chunks.append('['+source['stage_id']+'] '+row['content'][:1200])
    context='\\n\\n'.join(chunks)[-7500:]
    snapshot=dict(schema='orbit.studio-handoff-receipt.v1',project_id=pid,stage_id=sid,run_id=run_id,
                  mode=mode,sources=sources,context=context,context_digest=digest(context))
    payload=canonical(snapshot)
    c.execute('INSERT INTO studio_handoff_receipts VALUES(?,?,?,?,?,?)',(pid,sid,run_id,payload,digest(payload),stamp))
    return context

def record_draft(c,pid,sid,run_id,lane,stamp):
    # Called in the transaction persisting the successful draft artifact.
    c.execute('INSERT INTO studio_handoff_drafts VALUES(?,?,?,?,?)',(pid,sid,run_id,lane,stamp))

def receipt_view(c,pid,sid,inputs):
    row=c.execute('SELECT * FROM studio_handoff_receipts WHERE project_id=? AND stage_id=? ORDER BY rowid DESC LIMIT 1',(pid,sid)).fetchone()
    if not row:return None,'NOT_RECORDED'
    info=dict(run_id=row['run_id'],digest=row['digest'],created_at=row['created_at'],mode=None,lanes=[],sources=[],context_digest=None)
    try:
        snap=json.loads(row['snapshot'])
        if (digest(row['snapshot'])!=row['digest'] or snap['project_id']!=pid or snap['stage_id']!=sid
            or snap['run_id']!=row['run_id'] or digest(snap['context'])!=snap['context_digest']):
            return info,'INVALID'
        info.update(mode=snap['mode'],sources=snap['sources'],context_digest=snap['context_digest'])
        lanes=[x['lane'] for x in c.execute('SELECT lane FROM studio_handoff_drafts WHERE project_id=? AND stage_id=? AND run_id=? ORDER BY lane',(pid,sid,row['run_id']))]
        drafts={x['agent_id'] for x in c.execute("SELECT agent_id FROM artifacts WHERE project_id=? AND stage_id=? AND run_id=? AND kind='draft'",(pid,sid,row['run_id']))}
        if any(sid+'-'+lane not in drafts for lane in lanes):return info,'INVALID'
        info['lanes']=lanes
        if snap['sources']!=inputs:return info,'STALE'
        if snap['mode']=='demo':return info,'DEMO_DRAFTS' if lanes else 'PREPARED'
        return info,'DRAFTS_RETURNED' if lanes==['A','B'] else 'PARTIAL' if lanes else 'PREPARED'
    except (ValueError,KeyError,TypeError,AttributeError):return info,'INVALID'

def view(c,pid,stages,tasks):
    by_id={t['stage_id']:t for t in tasks}
    outputs=[]
    for stage in stages:
        sid=stage['id'];task=by_id.get(sid)
        entry=dict(stage_id=sid,status='blocked',reason='stage_not_complete',
                   artifact_id=None,run_id=None,content_digest=None,version=None,
                   execution_authorized=False)
        # Human-gated stages must actually be approved, not merely done.
        if task and task['status'] in ('done','approved') and (not stage['approval'] or task['status']=='approved'):
            latest=c.execute("SELECT id FROM artifacts WHERE project_id=? AND stage_id=? AND kind='final' ORDER BY rowid DESC LIMIT 1",(pid,sid)).fetchone()
            if latest:
                try:
                    artifact=github_bridge.reviewed_artifact(c,pid,latest['id'])
                    # Reject a final belonging to a superseded run even when a
                    # newer attempt has not produced a final yet.
                    newest=c.execute("SELECT run_id FROM artifacts WHERE project_id=? AND stage_id=? AND kind IN ('draft','final') ORDER BY rowid DESC LIMIT 1",(pid,sid)).fetchone()
                    if not newest or newest['run_id']!=artifact['run_id']:raise ValueError('Superseded run')
                    version=c.execute("SELECT COUNT(*) FROM artifacts WHERE project_id=? AND stage_id=? AND kind='final'",(pid,sid)).fetchone()[0]
                    entry.update(status='reviewed_output',reason=None,artifact_id=artifact['id'],
                        run_id=artifact['run_id'],content_digest=hashlib.sha256(artifact['content'].encode('utf-8')).hexdigest(),version=version)
                except (ValueError,TypeError,KeyError):entry['reason']='review_or_source_invalid'
            else:entry['reason']='missing_final'
        outputs.append(entry)
    roles=[]
    for i,stage in enumerate(stages):
        previous=outputs[:i]
        receipt,consumption=receipt_view(c,pid,stage['id'],previous)
        roles.append(dict(stage_id=stage['id'],output=outputs[i],inputs=previous,receipt=receipt,
            input_status='project_idea' if not previous else 'reviewed_sources_available' if all(x['status']=='reviewed_output' for x in previous) else 'blocked',
            consumption_status=consumption,execution_authorized=False))
    return dict(schema='orbit.studio-handoff.v1',project_id=pid,scope='legacy_pipeline',
        roles=roles,production_release_authorized=False)
