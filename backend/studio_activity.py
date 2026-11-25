"""Project-scoped read model of recorded queue and inference evidence.

Pending ledger rows are not proof of a live provider connection. DEMO has no
usage rows. No per-agent activity is inferred from a department status.
"""
def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS studio_stage_runs(
        project_id TEXT NOT NULL REFERENCES projects(id),stage_id TEXT NOT NULL,
        run_id TEXT NOT NULL,queue_id TEXT,created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,stage_id,run_id))""")
    c.execute("CREATE INDEX IF NOT EXISTS studio_stage_runs_project ON studio_stage_runs(project_id,stage_id)")
    c.execute("CREATE INDEX IF NOT EXISTS studio_usage_agent ON ai_usage(project_id,agent_id)")

def bind(c,pid,sid,rid,qid,stamp):
    if qid is not None:
        q=c.execute("SELECT kind,status FROM agent_queue WHERE project_id=? AND id=?",(pid,qid)).fetchone()
        if not q or q['kind']!='pipeline' or q['status']!='running':raise ValueError('Invalid stage queue binding')
    c.execute('INSERT INTO studio_stage_runs VALUES(?,?,?,?,?)',(pid,sid,rid,qid,stamp))

def view(c,pid,stages,handoff):
    receipts={r['stage_id']:r.get('receipt') for r in handoff['roles']}
    queues=[dict(x) for x in c.execute("""SELECT id,kind,status,control,reason,attempts,deferrals,checkpoint_stage,updated_at,retry_of
        FROM agent_queue WHERE project_id=? ORDER BY rowid DESC LIMIT 30""",(pid,))]
    result=[]
    for stage in stages:
        sid=stage['id'];receipt=receipts.get(sid)
        rid=receipt['run_id'] if receipt else None
        binding=c.execute("SELECT queue_id FROM studio_stage_runs WHERE project_id=? AND stage_id=? AND run_id=?",(pid,sid,rid)).fetchone()
        queue=None
        if binding and binding['queue_id']:
            row=c.execute("SELECT id,kind,status,control,reason,attempts,deferrals,checkpoint_stage,updated_at,retry_of FROM agent_queue WHERE project_id=? AND id=?",(pid,binding['queue_id'])).fetchone()
            if row:queue=dict(row)
        agents=[]
        for lane in ('A','B'):
            aid=sid+'-'+lane
            fields='id,run_id,lane,provider,model,purpose,started_at,elapsed_ms,status,input_tokens,output_tokens,total_tokens,coverage,source'
            latest=c.execute('SELECT '+fields+' FROM ai_usage WHERE project_id=? AND agent_id=? AND lane=? ORDER BY rowid DESC LIMIT 1',(pid,aid,lane)).fetchone()
            attempt=dict(latest) if latest else None
            current=c.execute('SELECT '+fields+' FROM ai_usage WHERE project_id=? AND agent_id=? AND lane=? AND run_id=? AND purpose IN (\'stage_draft\',\'stage_review\',\'stage_synthesis\') ORDER BY rowid DESC LIMIT 1',(pid,aid,lane,rid)).fetchone()
            stage_attempt=dict(current) if current else None
            state='NO_EVIDENCE'
            if stage_attempt:
                status=stage_attempt['status']
                state='ATTEMPT_PENDING_UNCONFIRMED' if status=='pending' else 'ATTEMPT_RETURNED' if status=='ok' else 'ATTEMPT_ERROR'
                if status=='pending' and queue and queue['status'] in ('interrupted','dead','cancelled','succeeded'):state='ATTEMPT_UNRESOLVED'
            elif receipt and receipt.get('mode')=='demo' and lane in receipt.get('lanes',[]):state='DEMO_DRAFT_RECORDED'
            denied=c.execute('SELECT run_id,reason,created_at FROM inference_denials WHERE project_id=? AND agent_id=? AND run_id=? ORDER BY seq DESC LIMIT 1',(pid,aid,rid)).fetchone()
            agents.append(dict(agent_id=aid,lane=lane,state=state,stage_attempt=stage_attempt,latest_attempt=attempt,
                denial=dict(denied) if denied else None,draft_recorded=bool(receipt and lane in receipt.get('lanes',[]))))
        result.append(dict(stage_id=sid,run_id=rid,queue=queue,agents=agents))
    return dict(schema='orbit.studio-activity.v1',project_id=pid,roles=result,recent_queue=queues,
                note='Recorded attempts only; pending is not verified live; queue status is job-level, not agent-level.')
