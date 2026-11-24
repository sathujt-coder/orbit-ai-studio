"""Durable per-attempt token ledger. Provider-reported counts only; no prompts or keys."""
import time
import uuid
import model_provider as mp
import cost_store

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS ai_usage(
      id TEXT PRIMARY KEY, project_id TEXT, agent_id TEXT NOT NULL, lane TEXT NOT NULL,
      provider TEXT NOT NULL, model TEXT NOT NULL, purpose TEXT NOT NULL, run_id TEXT,
      started_at INTEGER NOT NULL, elapsed_ms INTEGER,
      status TEXT NOT NULL CHECK(status IN ('pending','ok','output_error','provider_error','internal_error')),
      input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
      coverage TEXT NOT NULL CHECK(coverage IN ('unknown','partial','complete','inconsistent')),
      source TEXT NOT NULL)""")
    c.execute('CREATE INDEX IF NOT EXISTS ai_usage_project_time ON ai_usage(project_id,started_at)')
    c.execute('CREATE INDEX IF NOT EXISTS ai_usage_time ON ai_usage(started_at)')
    cost_store.ensure_schema(c)

def start(c,lane,project_id,agent_id,purpose,run_id=None):
    if lane.provider=='demo':raise ValueError('Demo does not consume model tokens')
    identifier=uuid.uuid4().hex
    c.execute("""INSERT INTO ai_usage(id,project_id,agent_id,lane,provider,model,purpose,run_id,started_at,status,coverage,source)
                 VALUES(?,?,?,?,?,?,?,?,?,'pending','unknown','none')""",
              (identifier,project_id,agent_id,lane.lane,lane.provider,lane.model,purpose,run_id,int(time.time())))
    cost_store.snapshot(c,identifier,lane)
    return identifier

def finish(c,identifier,event):
    result=c.execute("""UPDATE ai_usage SET elapsed_ms=?,status=?,input_tokens=?,output_tokens=?,total_tokens=?,coverage=?,source=?
                       WHERE id=? AND status='pending'""",
                     (event['elapsed_ms'],event['status'],event['input_tokens'],event['output_tokens'],event['total_tokens'],
                      event['coverage'],event['source'],identifier))
    if result.rowcount!=1:raise RuntimeError('Usage ledger completion conflict')

def tracked_chat(conn_factory,lock,lane,system,user,*,project_id,agent_id,purpose,run_id=None,**kwargs):
    # Commit before calling the provider. A crash leaves a visible pending attempt.
    # Database errors fail closed; do not retry a possibly billable request.
    with lock,conn_factory() as c:identifier=start(c,lane,project_id,agent_id,purpose,run_id)
    started=time.monotonic()
    observed={}
    def observer(event):observed.update(event)
    try:
        return mp.chat(lane,system,user,usage_observer=observer,**kwargs)
    finally:
        event=observed or dict(mp.token_usage(None,False),status='internal_error',elapsed_ms=round((time.monotonic()-started)*1000))
        with lock,conn_factory() as c:finish(c,identifier,event)

AGG="""COUNT(*) AS requests, COALESCE(SUM(status='ok'),0) AS successful_calls,
 COALESCE(SUM(status IN ('output_error','provider_error','internal_error')),0) AS failed_calls,
 COALESCE(SUM(status='pending'),0) AS pending_calls,
 COALESCE(SUM(coverage='complete'),0) AS complete_calls,
 COALESCE(SUM(coverage='partial'),0) AS partial_calls,
 COALESCE(SUM(coverage='inconsistent'),0) AS inconsistent_calls,
 COALESCE(SUM(coverage='unknown'),0) AS unknown_calls,
 SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, SUM(total_tokens) AS total_tokens"""

def summary(c,project_id,days=7,*,all_projects=False,now=None):
    if type(days) is not int or days not in (1,7,30,90):raise ValueError('Days must be 1, 7, 30 or 90')
    if not all_projects and not project_id:raise ValueError('Project required')
    end=int(time.time()) if now is None else int(now)
    cutoff=end-days*86400
    where='started_at>=? AND started_at<=?';params=[cutoff,end]
    if not all_projects:where+=' AND project_id=?';params.append(project_id)
    def query(sql):
        cursor=c.execute(sql,params)
        keys=[d[0] for d in cursor.description]
        return [dict(zip(keys,row)) for row in cursor.fetchall()]
    totals=query('SELECT '+AGG+' FROM ai_usage WHERE '+where)[0]
    groups=query('SELECT agent_id,lane,provider,model,purpose,'+AGG+' FROM ai_usage WHERE '+where+
                 ' GROUP BY agent_id,lane,provider,model,purpose ORDER BY requests DESC,agent_id,model,purpose LIMIT 201')
    daily=query("SELECT date(started_at,'unixepoch') AS day,"+AGG+' FROM ai_usage WHERE '+where+' GROUP BY day ORDER BY day')
    projects=query('SELECT project_id,'+AGG+' FROM ai_usage WHERE '+where+' GROUP BY project_id ORDER BY requests DESC,project_id LIMIT 201') if all_projects else []
    return {'schema':'orbit.token-usage.v1','scope':'all' if all_projects else 'project','project_id':project_id,
            'days':days,'since':cutoff,'until':end,'totals':totals,'by_agent_model':groups[:200],'groups_truncated':len(groups)>200,
            'daily':daily,'by_project':projects[:200],'projects_truncated':len(projects)>200,
            'note':'Provider-reported counts only. Unknown/partial/inconsistent counts are not zero. Totals are known subtotals, not a bill.'}
