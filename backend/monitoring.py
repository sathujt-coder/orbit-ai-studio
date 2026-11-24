"""P5.8 bounded, periodic operational telemetry. No prompts, secrets or outbound calls."""
import json,os,time,threading,uuid
import cost_store,usage_store,inference_guard,model_routing

QUEUE_STATES=('queued','running','paused','waiting_approval','succeeded','dead','interrupted','cancelled')
def policy(env):
    def integer(key,default,lo,hi):
        try:n=int(env.get(key,str(default)))
        except (ValueError,TypeError):raise ValueError('Invalid '+key) from None
        if not lo<=n<=hi:raise ValueError('Invalid '+key)
        return n
    return {'interval_seconds':integer('ORBIT_MONITOR_INTERVAL',30,5,300),
            'retention_hours':integer('ORBIT_MONITOR_RETENTION_HOURS',24,1,168),
            'max_samples':integer('ORBIT_MONITOR_MAX_SAMPLES',2880,60,10080),
            'queue_warn_age_seconds':integer('ORBIT_MONITOR_QUEUE_WARN_SECONDS',300,10,86400),
            'pending_warn_age_seconds':integer('ORBIT_MONITOR_PENDING_WARN_SECONDS',600,10,86400)}
def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS monitoring_samples(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, sampled_at INTEGER NOT NULL,
        boot_id TEXT NOT NULL, snapshot TEXT NOT NULL)""")
    c.execute('CREATE INDEX IF NOT EXISTS monitoring_sample_time ON monitoring_samples(sampled_at)')
    c.execute("""CREATE TABLE IF NOT EXISTS monitoring_alert_events(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL,
        code TEXT NOT NULL, transition TEXT NOT NULL, severity TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS monitoring_active_alerts(
        code TEXT PRIMARY KEY, severity TEXT NOT NULL)""")
    c.execute('CREATE INDEX IF NOT EXISTS monitoring_alert_time ON monitoring_alert_events(created_at)')
def query(c,sql,params=()):
    cur=c.execute(sql,params);keys=[x[0] for x in cur.description]
    return [dict(zip(keys,r)) for r in cur.fetchall()]
def counts(c,table,states):
    out={s:0 for s in states}
    for status,n in c.execute('SELECT status,count(*) FROM '+table+' GROUP BY status'):out[status]=n
    return out
def alert(code,severity,message):return {'code':code,'severity':severity,'message':message}
def alerts(data,p):
    a=[];r=data['resources'];q=data['queue'];cc=data['concurrency'];b=data['protection'];w=data['workers']
    if w['failed'] or w['alive']<w['configured']:a.append(alert('worker_unavailable','critical','One or more queue workers unavailable'))
    if b['stopped']:a.append(alert('emergency_stop','warning','New inference admissions stopped'))
    if r['pressure_reason']:a.append(alert('resource_pressure','warning',r['pressure_reason']))
    if r['gpu']['status']!='available':a.append(alert('gpu_unknown','info','GPU telemetry unavailable, not zero'))
    if q['eligible_oldest_age_seconds'] is not None and q['eligible_oldest_age_seconds']>=p['queue_warn_age_seconds']:a.append(alert('queue_wait','warning','Eligible queued task age exceeds threshold'))
    if cc['waiting'] and cc['active']>=cc['policy']['global_limit']:a.append(alert('inference_saturated','warning','Inference slots saturated with waiters'))
    if data['pending_oldest_age_seconds'] is not None and data['pending_oldest_age_seconds']>=p['pending_warn_age_seconds']:a.append(alert('pending_usage_old','warning','Old pending ledger entry; outcome uncertain'))
    if data['breaker_counts']['open'] or data['breaker_counts']['half_open']:a.append(alert('circuit_not_closed','warning','At least one circuit open or half-open'))
    t=b['totals'];cap=b['policy']['global_cost_usd']
    if t['unknown_cost'] or t['unknown_tokens']:a.append(alert('unknown_usage','warning','Monthly usage/cost coverage incomplete'))
    if t['reservation_overruns']:a.append(alert('reservation_overrun','warning','Actual usage exceeded reservation estimate'))
    if cap is not None:
        from decimal import Decimal
        limit=Decimal(cap);spent=Decimal(t['accounted_usd'])
        if spent>limit or (limit>0 and spent>=limit):a.append(alert('budget_reached','critical','Accounted global budget reached or exceeded'))
        elif limit>0 and spent>=limit*Decimal('0.8'):a.append(alert('budget_near','warning','Accounted global budget at least 80%'))
    if b['policy']['global_tokens'] and t['accounted_tokens']>=b['policy']['global_tokens']:a.append(alert('token_limit_reached','warning','Accounted global token limit reached'))
    if data['recent_denials']:a.append(alert('recent_denials','warning','Inference admissions denied in the last 15 minutes'))
    return a
def collect(c,*,now,resources,concurrency,workers,guard,roster,base,routing_mode,boot_id,p):
    usage=usage_store.summary(c,None,1,all_projects=True,now=now)
    costs=cost_store.summary(c,None,1,all_projects=True,now=now)
    protection=guard.view(c,all_projects=True,now=now)
    queue=counts(c,'agent_queue',QUEUE_STATES)
    oldest=c.execute("""SELECT min(q.created_at) FROM agent_queue q LEFT JOIN agent_queue d ON d.id=q.dependency_id
        WHERE q.status='queued' AND q.available_at<=? AND (q.dependency_id IS NULL OR d.status='succeeded')
        AND NOT EXISTS(SELECT 1 FROM agent_queue r WHERE r.project_id=q.project_id AND r.status='running')""",(now,)).fetchone()[0]
    pending=c.execute("SELECT min(started_at) FROM ai_usage WHERE status='pending'").fetchone()[0]
    # Exact roster and ledger aggregation. Pending is not proof of executing.
    agents=query(c,"SELECT agent_id,count(*) AS requests,sum(status='pending') AS pending,sum(status='ok') AS successful,sum(status IN ('provider_error','output_error','internal_error')) AS failed,sum(total_tokens) AS known_tokens,max(started_at) AS last_request_at FROM ai_usage WHERE started_at>=? AND started_at<=? GROUP BY agent_id",(now-86400,now))
    by_id={x['agent_id']:x for x in agents}
    roster_rows=[dict(id=a['id'],department=a['dept'],lane=a['lane'],**{k:v for k,v in by_id.get(a['id'],{'requests':0,'pending':0,'successful':0,'failed':0,'known_tokens':None,'last_request_at':None}).items() if k!='agent_id'}) for a in roster]
    # Pending counts include unresolved entries older than 24h.
    all_pending=dict(c.execute("SELECT agent_id,count(*) FROM ai_usage WHERE status='pending' GROUP BY agent_id").fetchall())
    for a in roster_rows:a['pending_ledger']=all_pending.get(a['id'],0)
    models=query(c,"SELECT provider,model,count(*) AS requests,sum(status='pending') AS pending,sum(total_tokens) AS known_tokens FROM ai_usage WHERE started_at>=? AND started_at<=? GROUP BY provider,model ORDER BY requests DESC,provider,model LIMIT 101",(now-86400,now))
    breaker_counts={s:0 for s in ('closed','open','half_open')}
    for state,n in c.execute('SELECT state,count(*) FROM inference_breakers GROUP BY state'):breaker_counts[state]=n
    data={'schema':'orbit.monitoring.v1','sampled_at':now,'boot_id':boot_id,'resources':resources,'concurrency':concurrency,'workers':workers,
          'queue':dict(counts=queue,eligible_oldest_age_seconds=None if oldest is None else max(0,now-oldest)),
          'projects':c.execute('SELECT count(*) FROM projects').fetchone()[0],
          'stage_counts':counts(c,'tasks',('queued','drafting','reviewing','synthesizing','awaiting_approval','needs_revision','done','approved')),
          'agents':roster_rows,'usage_24h':usage['totals'],'cost_24h':costs['totals'],'daily_usage':usage['daily'],'daily_cost':costs['daily'],
          'models_24h':models[:100],'models_truncated':len(models)>100,
          'configured_models':{k:v.public() for k,v in base.items()},'routing_mode':routing_mode,
          'latest_routes':model_routing.history(c,all_projects=True)[:10],
          'protection':{'policy':protection['policy'],'totals':protection['totals'],'month_utc':protection['month_utc'],'stopped':protection['stopped'],'breakers':protection['breakers']},
          'breaker_counts':breaker_counts,'pending_ledger':sum(all_pending.values()),'pending_oldest_age_seconds':None if pending is None else max(0,now-pending),
          'recent_denials':c.execute('SELECT count(*) FROM inference_denials WHERE created_at>=? AND created_at<=?',(now-900,now)).fetchone()[0]}
    data['alerts']=alerts(data,p)
    data['health']='degraded' if any(a['severity']=='critical' for a in data['alerts']) else 'attention' if any(a['severity']=='warning' for a in data['alerts']) else 'nominal'
    return data

def history_point(data):
    r=data['resources']['metrics'];cg=r['cgroup'];u=data['usage_24h'];b=data['protection']['totals']
    return {'sampled_at':data['sampled_at'],'boot_id':data['boot_id'],'cpu_percent':r['process_cpu_percent'],
            'rss_bytes':r['process_rss_bytes'],'available_bytes':r['effective_memory_available_bytes'],
            'cgroup_used_bytes':cg['memory_current_bytes'],'cgroup_limit_bytes':cg['memory_limit_bytes'],
            'gpu_max_utilization_percent':max((x['utilization_percent'] for x in data['resources']['gpu']['devices']),default=None),
            'active':data['concurrency']['active'],'waiting':data['concurrency']['waiting'],
            'queued':data['queue']['counts']['queued'],'running':data['queue']['counts']['running'],
            'tokens_24h':u['total_tokens'],'cost_24h_usd':data['cost_24h']['total_usd'],
            'held_tokens':b['held_tokens'],'alert_count':len(data['alerts'])}
def persist(c,data,p):
    now=data['sampled_at'];active={a['code']:a['severity'] for a in data['alerts']}
    old=dict(c.execute('SELECT code,severity FROM monitoring_active_alerts').fetchall())
    for code,severity in active.items():
        if old.get(code)!=severity:
            c.execute('INSERT INTO monitoring_alert_events(created_at,code,transition,severity) VALUES(?,?,?,?)',(now,code,'raised',severity))
    for code,severity in old.items():
        if code not in active:c.execute('INSERT INTO monitoring_alert_events(created_at,code,transition,severity) VALUES(?,?,?,?)',(now,code,'resolved',severity))
    c.execute('DELETE FROM monitoring_active_alerts')
    c.executemany('INSERT INTO monitoring_active_alerts VALUES(?,?)',active.items())
    # Only compact numeric history persisted, not full project/model snapshots.
    c.execute('INSERT INTO monitoring_samples(sampled_at,boot_id,snapshot) VALUES(?,?,?)',(now,data['boot_id'],json.dumps(history_point(data),allow_nan=False)))
    cutoff=now-p['retention_hours']*3600
    for table,limit in (('monitoring_samples',p['max_samples']),('monitoring_alert_events',2000)):
        column='sampled_at' if table=='monitoring_samples' else 'created_at'
        c.execute('DELETE FROM '+table+' WHERE '+column+'<?',(cutoff,))
        c.execute('DELETE FROM '+table+' WHERE seq IN (SELECT seq FROM '+table+' ORDER BY seq DESC LIMIT -1 OFFSET ?)',(limit,))
def history(c,now,hours,limit):
    if type(hours) is not int or hours not in (1,6,24,168) or type(limit) is not int or not 2<=limit<=500:raise ValueError('Invalid monitor history range')
    raw=c.execute('SELECT snapshot FROM monitoring_samples WHERE sampled_at>=? AND sampled_at<=? ORDER BY seq DESC LIMIT 10080',(now-hours*3600,now)).fetchall()
    values=[json.loads(r[0]) for r in reversed(raw)]
    n=len(values)
    # Even index sampling; preserve endpoints. Not min/max aggregation.
    if n>limit:values=[values[i*(n-1)//(limit-1)] for i in range(limit)]
    return {'points':values,'stored_points':n,'downsampled':n>limit,'hours':hours,
            'events':query(c,'SELECT created_at,code,transition,severity FROM monitoring_alert_events WHERE created_at>=? AND created_at<=? ORDER BY seq DESC LIMIT 100',(now-hours*3600,now))}
class Monitor:
    def __init__(self,env=None):
        self.policy=policy(os.environ if env is None else env);self.boot_id=uuid.uuid4().hex
        self.lock=threading.Lock();self.latest=None;self.failure_count=0;self.last_error_at=None;self.stop=threading.Event();self.thread=None
    def sample(self,conn_factory,db_lock,resources,concurrency,workers,guard,roster,base,routing_mode):
        now=int(time.time())
        # Resource measurement (including optional fixed nvidia-smi) outside DB lock.
        r=resources.snapshot(include_gpu=True);cc=concurrency.snapshot();w=workers()
        with db_lock,conn_factory() as c:
            data=collect(c,now=now,resources=r,concurrency=cc,workers=w,guard=guard,roster=roster,base=base(c),routing_mode=routing_mode,boot_id=self.boot_id,p=self.policy)
            persist(c,data,self.policy)
        with self.lock:self.latest=data;self.last_error_at=None
        return data
    def start(self,*args):
        if self.thread is not None:raise RuntimeError('Monitor already started')
        def loop():
            while not self.stop.is_set():
                try:self.sample(*args)
                except Exception:
                    with self.lock:self.failure_count+=1;self.last_error_at=int(time.time())
                self.stop.wait(self.policy['interval_seconds'])
        self.thread=threading.Thread(target=loop,name='orbit-monitor',daemon=True);self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join()
    def view(self,now=None):
        now=int(time.time()) if now is None else now
        with self.lock:
            latest=self.latest;err=self.last_error_at;failures=self.failure_count
        age=None if latest is None else max(0,now-latest['sampled_at'])
        stale=latest is None or err is not None or age>self.policy['interval_seconds']*3
        return {'policy':dict(self.policy),'snapshot':latest,'sampler':{'status':'stale' if stale else 'fresh','age_seconds':age,
                  'failures':failures,'last_error_at':err,'running':bool(self.thread and self.thread.is_alive())},
                'note':'Periodic samples, not real-time tracing. Pending ledger is not proof of running inference. No remote GPU metrics.'}
