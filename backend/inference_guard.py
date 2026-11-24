"""Durable budget reservation and circuit breaker. One server process per DB."""
import os,time,json
from datetime import datetime,timezone
from urllib.parse import urlsplit
import cost_store as cost
import model_provider as mp
import provider_settings as ps

def policy(env):
    mode=env.get('ORBIT_BUDGET_MODE','observe')
    if mode not in ('observe','enforce'):raise ValueError('Invalid budget mode')
    def integer(key,default,lo,hi):
        try:n=int(env.get(key,str(default)))
        except (ValueError,TypeError):raise ValueError('Invalid '+key) from None
        if not lo<=n<=hi:raise ValueError('Invalid '+key)
        return n
    def money(key):
        x=env.get(key,'')
        return None if x=='' else cost.money(x,100000000)*10**6
    return {'mode':mode,'global_cost_picos':money('ORBIT_MONTHLY_GLOBAL_USD'),
            'agent_cost_picos':money('ORBIT_MONTHLY_AGENT_USD'),
            'project_tokens':integer('ORBIT_MONTHLY_PROJECT_TOKENS',0,0,10**12),
            'global_tokens':integer('ORBIT_MONTHLY_GLOBAL_TOKENS',0,0,10**12),
            'agent_tokens':integer('ORBIT_MONTHLY_AGENT_TOKENS',0,0,10**12),
            'run_calls':integer('ORBIT_MAX_RUN_CALLS',64,1,1024),
            'failure_threshold':integer('ORBIT_BREAKER_FAILURES',3,1,20),
            'cooldown_seconds':integer('ORBIT_BREAKER_COOLDOWN',60,1,3600)}

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS inference_control(
        id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, stopped INTEGER NOT NULL,
        actor TEXT NOT NULL, updated_at INTEGER NOT NULL)""")
    c.execute("INSERT OR IGNORE INTO inference_control VALUES(1,0,0,'system',0)")
    c.execute("""CREATE TABLE IF NOT EXISTS inference_breakers(
        provider TEXT NOT NULL, endpoint_id TEXT NOT NULL, model TEXT NOT NULL,
        state TEXT NOT NULL, failures INTEGER NOT NULL, epoch INTEGER NOT NULL,
        open_until INTEGER NOT NULL, probe_id TEXT, updated_at INTEGER NOT NULL,
        PRIMARY KEY(provider,endpoint_id,model))""")
    c.execute("""CREATE TABLE IF NOT EXISTS inference_reservations(
        usage_id TEXT PRIMARY KEY REFERENCES ai_usage(id), endpoint_id TEXT NOT NULL,
        reserved_tokens INTEGER NOT NULL, reserved_picos INTEGER,
        breaker_epoch INTEGER NOT NULL, is_probe INTEGER NOT NULL, warning TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS inference_denials(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, agent_id TEXT NOT NULL,
        run_id TEXT, reason TEXT NOT NULL, created_at INTEGER NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS inference_denials_project ON inference_denials(project_id,seq DESC)")
    c.execute("CREATE INDEX IF NOT EXISTS inference_usage_run ON ai_usage(project_id,run_id)")
    c.execute("CREATE INDEX IF NOT EXISTS inference_usage_agent ON ai_usage(agent_id,started_at)")

def month_start(now):
    return int(datetime.fromtimestamp(now,timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp())

def control(c):
    r=c.execute('SELECT revision,stopped,actor,updated_at FROM inference_control WHERE id=1').fetchone()
    return {'revision':r[0],'stopped':bool(r[1]),'actor':r[2],'updated_at':r[3]}

def set_stop(c,actor,body,env):
    if not ps.is_admin(actor,env):raise PermissionError('Operator required')
    if set(body)!={'revision','stopped','confirmation'} or type(body['revision']) is not int or type(body['stopped']) is not bool or body['confirmation']!=('STOP NEW INFERENCE' if body['stopped'] else 'RESUME INFERENCE'):
        raise ValueError('Explicit stop/resume confirmation and revision required')
    n=c.execute('UPDATE inference_control SET revision=revision+1,stopped=?,actor=?,updated_at=? WHERE id=1 AND revision=?',
                (int(body['stopped']),actor,int(time.time()),body['revision'])).rowcount
    if n!=1:raise ValueError('Control changed; reload')
    return control(c)

def key(lane):return (lane.provider,cost.endpoint_id(lane.provider,lane.base_url),lane.model)

def rate(c,lane):
    row=cost.current_rate(c,*key(lane))
    if row:return (row[1],row[2]) if row[3] and row[1] is not None and row[2] is not None else None
    if lane.provider=='ollama' and urlsplit(lane.base_url).hostname in ('localhost','127.0.0.1','::1') and not lane.api_key and 'cloud' not in lane.model.lower():return (0,0)
    return None

def totals(c,now,*,project=None,agent=None,scope='global'):
    where='u.started_at>=? AND u.started_at<=?';params=[month_start(now),now]
    if scope=='project':where+=' AND u.project_id=?';params.append(project)
    elif scope=='agent':where+=' AND u.agent_id=?';params.append(agent)
    result={'requests':0,'accounted_tokens':0,'accounted_picos':0,'unknown_tokens':0,'unknown_cost':0,
            'held_tokens':0,'held_picos':0,'held_calls':0,'reservation_overruns':0}
    for status,coverage,i,o,t,kind,ri,ro,rt,rp in c.execute("""SELECT u.status,u.coverage,u.input_tokens,u.output_tokens,u.total_tokens,b.kind,r.input_rate,r.output_rate,
             s.reserved_tokens,s.reserved_picos FROM ai_usage u LEFT JOIN ai_cost_basis b ON b.usage_id=u.id
             LEFT JOIN ai_rates r ON r.id=b.rate_id LEFT JOIN inference_reservations s ON s.usage_id=u.id WHERE """+where,params):
        result['requests']+=1
        complete=status!='pending' and coverage=='complete' and i is not None and o is not None and t==i+o
        actual_cost=0 if kind=='local_assumed_zero' else i*ri+o*ro if complete and kind=='rated' and ri is not None and ro is not None else None
        actual_tokens=t if complete else None
        held=False
        for actual,reserved,k,h,unknown in ((actual_tokens,rt,'accounted_tokens','held_tokens','unknown_tokens'),(actual_cost,rp,'accounted_picos','held_picos','unknown_cost')):
            if actual is not None:result[k]+=actual
            elif reserved is not None:result[k]+=reserved;result[h]+=reserved;held=True
            else:result[unknown]+=1
        if held:result['held_calls']+=1
        if (rt is not None and actual_tokens is not None and actual_tokens>rt) or (rp is not None and actual_cost is not None and actual_cost>rp):result['reservation_overruns']+=1
    return result

def public_totals(t):
    return {**{k:v for k,v in t.items() if not k.endswith('_picos')},'accounted_usd':cost.usd(t['accounted_picos']),'held_usd':cost.usd(t['held_picos'])}

class Guard:
    def __init__(self,env=None):self.policy=policy(os.environ if env is None else env)
    def check(self,c,lane,project,agent,run,output,now=None):
        now=int(time.time()) if now is None else now
        p=self.policy
        if control(c)['stopped']:raise mp.BudgetError('emergency_stop')
        if run and c.execute('SELECT count(*) FROM ai_usage WHERE project_id IS ? AND run_id=?',(project,run)).fetchone()[0]>=p['run_calls']:
            raise mp.BudgetError('run_call_limit')
        if type(output) is not int or not 1<=output<=8192:raise mp.BudgetError('invalid_output_bound')
        # Configured context + explicit output bound, NOT a provider billing guarantee.
        reserve_tokens=lane.context_window+output
        rates=rate(c,lane)
        reserve_picos=None if rates is None else lane.context_window*rates[0]+output*rates[1]
        issues=[]
        if rates is None:issues.append('unpriced_model')
        _,project_cap=cost.budget_row(c,project) if project is not None else (0,None)
        scopes=[('global',p['global_cost_picos'],p['global_tokens']),('agent',p['agent_cost_picos'],p['agent_tokens'])]
        if project is not None:scopes.append(('project',None if project_cap is None else project_cap*10**6,p['project_tokens']))
        for scope,cap,tcap in scopes:
            if cap is None and not tcap:continue
            t=totals(c,now,project=project,agent=agent,scope=scope)
            if cap is not None:
                if t['unknown_cost'] or reserve_picos is None:issues.append(scope+'_cost_unknown')
                elif t['accounted_picos']+reserve_picos>cap:issues.append(scope+'_cost_limit')
            if tcap:
                if t['unknown_tokens']:issues.append(scope+'_tokens_unknown')
                elif t['accounted_tokens']+reserve_tokens>tcap:issues.append(scope+'_token_limit')
        if issues and p['mode']=='enforce':raise mp.BudgetError(issues[0])
        state=c.execute('SELECT state,epoch,open_until FROM inference_breakers WHERE provider=? AND endpoint_id=? AND model=?',key(lane)).fetchone()
        epoch=state[1] if state else 0;probe=False
        if state:
            if state[0]=='half_open':raise mp.BudgetError('circuit_half_open_busy')
            if state[0]=='open':
                if now<state[2]:raise mp.BudgetError('circuit_open')
                probe=True
        return {'tokens':reserve_tokens,'picos':reserve_picos,'epoch':epoch,'probe':probe,'warning':','.join(issues),'now':now}
    def reserve(self,c,identifier,lane,plan):
        k=key(lane);now=plan['now']
        c.execute("INSERT OR IGNORE INTO inference_breakers VALUES(?,?,?,'closed',0,0,0,NULL,?)",(*k,now))
        if plan['probe']:
            n=c.execute("""UPDATE inference_breakers SET state='half_open',probe_id=?,updated_at=?
                WHERE provider=? AND endpoint_id=? AND model=? AND state='open' AND epoch=?""",
                (identifier,now,*k,plan['epoch'])).rowcount
            if n!=1:raise RuntimeError('Circuit admission conflict')
        c.execute('INSERT INTO inference_reservations VALUES(?,?,?,?,?,?,?)',
                  (identifier,k[1],plan['tokens'],plan['picos'],plan['epoch'],int(plan['probe']),plan['warning']))
    def finish(self,c,identifier,lane,event,now=None):
        now=int(time.time()) if now is None else now
        k=key(lane)
        reservation=c.execute('SELECT breaker_epoch,is_probe FROM inference_reservations WHERE usage_id=?',(identifier,)).fetchone()
        row=c.execute('SELECT state,failures,epoch,probe_id FROM inference_breakers WHERE provider=? AND endpoint_id=? AND model=?',k).fetchone()
        if not reservation or not row:raise RuntimeError('Missing circuit reservation')
        if reservation[0]!=row[2]:return # stale completion cannot reopen/close newer generation
        if row[0]=='half_open' and row[3]!=identifier:return
        if row[0]=='open':return
        failed=event['status'] in ('provider_error','internal_error')
        failures=row[1]+1 if failed else 0
        opened=failed and (row[0]=='half_open' or failures>=self.policy['failure_threshold'])
        state='open' if opened else 'closed'
        epoch=row[2]+int(opened or row[0]=='half_open')
        until=now+self.policy['cooldown_seconds'] if opened else 0
        c.execute("""UPDATE inference_breakers SET state=?,failures=?,epoch=?,open_until=?,probe_id=NULL,updated_at=?
                     WHERE provider=? AND endpoint_id=? AND model=?""",(state,failures,epoch,until,now,*k))
    def recover(self,c,now=None):
        now=int(time.time()) if now is None else now
        # An interrupted half-open request has uncertain outcome. Never auto replay it.
        c.execute("""UPDATE inference_breakers SET state='open',epoch=epoch+1,probe_id=NULL,open_until=?,updated_at=?
                     WHERE state='half_open'""",(now+self.policy['cooldown_seconds'],now))
    def view(self,c,project=None,*,all_projects=False,now=None):
        now=int(time.time()) if now is None else now
        where='' if all_projects else ' WHERE project_id=?';params=() if all_projects else (project,)
        denied=[dict(zip(('project_id','agent_id','run_id','reason','created_at'),r)) for r in c.execute('SELECT project_id,agent_id,run_id,reason,created_at FROM inference_denials'+where+' ORDER BY seq DESC LIMIT 100',params)]
        p={k:v for k,v in self.policy.items() if not k.endswith('_picos')}
        p.update(global_cost_usd=cost.usd(self.policy['global_cost_picos']),agent_cost_usd=cost.usd(self.policy['agent_cost_picos']))
        t=totals(c,now,project=project,scope='global' if all_projects else 'project')
        limit=None if all_projects else cost.budget_row(c,project)[1]
        data={'schema':'orbit.inference-protection.v1','policy':p,'month_utc':datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m'),
              'totals':public_totals(t),'project_limit_usd':cost.usd(None if limit is None else limit*10**6),'denials':denied,
              'stopped':control(c)['stopped'],'note':'Reservation uses configured context + output bound; provider billing may differ. Unknown usage holds reservation.'}
        if all_projects:
            data['control']=control(c)
            data['breakers']=[dict(zip(('provider','endpoint_id','model','state','failures','open_until','updated_at'),r)) for r in c.execute('SELECT provider,endpoint_id,model,state,failures,open_until,updated_at FROM inference_breakers ORDER BY updated_at DESC LIMIT 100')]
        return data

def deny(c,project,agent,run,reason):
    c.execute('INSERT INTO inference_denials(project_id,agent_id,run_id,reason,created_at) VALUES(?,?,?,?,?)',(project,agent,run,reason,int(time.time())))
