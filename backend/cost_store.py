"""P5.2: immutable rate versions, exact USD estimates, advisory monthly budgets."""
import hashlib
import re
import time
from datetime import datetime,timezone
from urllib.parse import urlsplit
import provider_settings as ps

SCALE=10**12 # USD picounits; rate in micro-USD per million tokens
def usd(picos):
    if picos is None:return None
    sign='-' if picos<0 else ''
    n=abs(picos)
    return sign+str(n//SCALE)+'.'+str(n%SCALE).zfill(12)

def money(value,limit):
    if not isinstance(value,str) or not re.fullmatch(r'(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,6})?',value):
        raise ValueError('USD must be a decimal string with up to six decimal places')
    a,_,b=value.partition('.')
    n=int(a)*10**6+int(b.ljust(6,'0') or '0')
    if n>limit*10**6:raise ValueError('USD amount exceeds allowed limit')
    return n

def endpoint_id(provider,url):
    return hashlib.sha256((provider+'\n'+url.rstrip('/')).encode()).hexdigest()

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS ai_rates(
       id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, endpoint_id TEXT NOT NULL,
       model TEXT NOT NULL, input_rate INTEGER, output_rate INTEGER, active INTEGER NOT NULL,
       created_at INTEGER NOT NULL, actor TEXT NOT NULL)""")
    c.execute('CREATE INDEX IF NOT EXISTS ai_rates_lookup ON ai_rates(provider,endpoint_id,model,id DESC)')
    c.execute("""CREATE TABLE IF NOT EXISTS ai_cost_basis(
       usage_id TEXT PRIMARY KEY REFERENCES ai_usage(id), kind TEXT NOT NULL,
       rate_id INTEGER REFERENCES ai_rates(id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS ai_budgets(
       project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, limit_microusd INTEGER,
       updated_at INTEGER NOT NULL, actor TEXT NOT NULL)""")

def current_rate(c,provider,eid,model):
    return c.execute('SELECT id,input_rate,output_rate,active FROM ai_rates WHERE provider=? AND endpoint_id=? AND model=? ORDER BY id DESC LIMIT 1',(provider,eid,model)).fetchone()

def save_rate(c,actor,body,env,initial):
    if not ps.is_admin(actor,env):raise PermissionError('Operator required')
    if set(body)!={'provider','url','model','input_usd_per_million','output_usd_per_million','active','expected_id','confirmation'} or body['confirmation']!='APPLY AI RATE':
        raise ValueError('Explicit APPLY AI RATE required')
    provider,url,model=body['provider'],body['url'],body['model']
    if not isinstance(provider,str) or not isinstance(url,str) or (provider,url) not in ps.endpoints(env,initial):
        raise PermissionError('Endpoint not approved')
    if not isinstance(model,str) or not model.strip() or model!=model.strip() or len(model)>200 or any(ord(x)<32 or ord(x)==127 for x in model):
        raise ValueError('Invalid model ID')
    if type(body['active']) is not bool or type(body['expected_id']) is not int:raise ValueError('Invalid rate revision')
    if body['active']:
        i=money(body['input_usd_per_million'],10000);o=money(body['output_usd_per_million'],10000)
    else:
        if body['input_usd_per_million'] is not None or body['output_usd_per_million'] is not None:raise ValueError('Disabled rates must omit prices')
        i=o=None
    eid=endpoint_id(provider,url);old=current_rate(c,provider,eid,model)
    if body['expected_id']!=(old[0] if old else 0):raise ValueError('Rate changed; reload before applying')
    cursor=c.execute('INSERT INTO ai_rates(provider,endpoint_id,model,input_rate,output_rate,active,created_at,actor) VALUES(?,?,?,?,?,?,?,?)',
                     (provider,eid,model,i,o,int(body['active']),int(time.time()),actor))
    return {'id':cursor.lastrowid,'effective':'future_calls_only'}

def rates_view(c,env,initial):
    approved=ps.endpoints(env,initial)
    urls={(k[0],endpoint_id(*k)):k[1] for k in approved}
    rows=c.execute("""SELECT r.id,r.provider,r.endpoint_id,r.model,r.input_rate,r.output_rate,r.active,r.created_at
                      FROM ai_rates r WHERE r.id=(SELECT MAX(s.id) FROM ai_rates s WHERE s.provider=r.provider AND s.endpoint_id=r.endpoint_id AND s.model=r.model)
                      ORDER BY r.id DESC LIMIT 201""").fetchall()
    return {'currency':'USD','allowed_endpoints':[{'provider':k[0],'url':k[1]} for k in approved],
            'rates':[{'id':r[0],'provider':r[1],'url':urls.get((r[1],r[2])),'model':r[3],
                      'input_usd_per_million':usd(r[4]*10**6) if r[4] is not None else None,
                      'output_usd_per_million':usd(r[5]*10**6) if r[5] is not None else None,
                      'active':bool(r[6]),'created_at':r[7]} for r in rows[:200]],'truncated':len(rows)>200}

def snapshot(c,identifier,lane):
    # Operator's explicit exact endpoint/model rate overrides default policy.
    rate=current_rate(c,lane.provider,endpoint_id(lane.provider,lane.base_url),lane.model)
    if rate:
        kind='rated' if rate[3] else 'unpriced';rid=rate[0]
    elif (lane.provider=='ollama' and urlsplit(lane.base_url).hostname in ('localhost','127.0.0.1','::1')
          and not lane.api_key and 'cloud' not in lane.model.lower()):
        kind='local_assumed_zero';rid=None
    else:kind='unpriced';rid=None
    c.execute('INSERT INTO ai_cost_basis VALUES(?,?,?)',(identifier,kind,rid))

def new_totals():
    return {'requests':0,'known_calls':0,'unknown_calls':0,'local_assumed_zero_calls':0,'rated_calls':0,'unpriced_calls':0,
            'legacy_calls':0,'pending_calls':0,'input_picos':0,'output_picos':0,'total_picos':0}

def add(t,row):
    status,coverage,i,o,kind,ri,ro=row
    t['requests']+=1
    if status=='pending':t['pending_calls']+=1
    if kind=='local_assumed_zero':
        t['local_assumed_zero_calls']+=1; t['known_calls']+=1
        return
    if kind=='rated':
        t['rated_calls']+=1
        if status!='pending' and coverage=='complete' and i is not None and o is not None and ri is not None and ro is not None:
            a=i*ri;b=o*ro
            t['input_picos']+=a;t['output_picos']+=b;t['total_picos']+=a+b;t['known_calls']+=1
            return
    elif kind=='unpriced':t['unpriced_calls']+=1
    else:t['legacy_calls']+=1
    t['unknown_calls']+=1

def public(t):
    result={k:v for k,v in t.items() if not k.endswith('_picos')}
    for k in ('input','output','total'):
        result[k+'_usd']=usd(t[k+'_picos']) if t['known_calls'] or not t['requests'] else None
    return result

def collect(c,project_id,start,end,all_projects=False,groups=True):
    where='u.started_at>=? AND u.started_at<?';params=[start,end]
    if not all_projects:where+=' AND u.project_id=?';params.append(project_id)
    cur=c.execute("""SELECT u.project_id,u.agent_id,u.provider,u.model,u.purpose,date(u.started_at,'unixepoch'),
                        u.status,u.coverage,u.input_tokens,u.output_tokens,b.kind,r.input_rate,r.output_rate
                      FROM ai_usage u LEFT JOIN ai_cost_basis b ON b.usage_id=u.id
                      LEFT JOIN ai_rates r ON r.id=b.rate_id WHERE """+where,params)
    total=new_totals();agents={};days={};projects={}
    truncated=False
    for row in cur:
        pid,agent,provider,model,purpose,day,*values=row
        add(total,values)
        if not groups:continue
        add(days.setdefault(day,new_totals()),values)
        for mapping,key in ((agents,(pid,agent,provider,model,purpose)),(projects,pid)):
            if key not in mapping and len(mapping)>=200:truncated=True;continue
            add(mapping.setdefault(key,new_totals()),values)
    return total,agents,days,projects,truncated

def budget_row(c,pid):
    row=c.execute('SELECT revision,limit_microusd FROM ai_budgets WHERE project_id=?',(pid,)).fetchone()
    return (row[0],row[1]) if row else (0,None)

def save_budget(c,pid,actor,body):
    if not c.execute("SELECT 1 FROM auth_memberships WHERE user_id=? AND project_id=? AND role='owner'",(actor,pid)).fetchone():
        raise PermissionError('Project owner required')
    if set(body)!={'revision','monthly_limit_usd','confirmation'} or body['confirmation']!='APPLY AI BUDGET' or type(body['revision']) is not int:
        raise ValueError('Explicit APPLY AI BUDGET and revision required')
    limit=None if body['monthly_limit_usd'] is None else money(body['monthly_limit_usd'],100000000)
    revision,_=budget_row(c,pid)
    if revision!=body['revision']:raise ValueError('Budget changed; reload before applying')
    c.execute("""INSERT INTO ai_budgets VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET
                 revision=excluded.revision,limit_microusd=excluded.limit_microusd,updated_at=excluded.updated_at,actor=excluded.actor""",
              (pid,revision+1,limit,int(time.time()),actor))
    return {'revision':revision+1,'enforcement':'advisory_only'}

def budget(c,pid,now):
    revision,limit=budget_row(c,pid)
    dt=datetime.fromtimestamp(now,timezone.utc);start=int(dt.replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp())
    t,*_=collect(c,pid,start,now+1,groups=False)
    cap=None if limit is None else limit*10**6
    known=t['total_picos'];unknown=t['unknown_calls']
    if cap is None:status='not_configured'
    elif known>=cap:status='limit_reached_known'
    elif unknown:status='incomplete_data'
    elif known*100>=cap*80:status='near_limit'
    else:status='within_known_estimate'
    return {'revision':revision,'month_utc':dt.strftime('%Y-%m'),'limit_usd':usd(cap),
            'known_spend_usd':public(t)['total_usd'],'known_remaining_usd':usd(cap-known) if cap is not None and (t['known_calls'] or not t['requests']) else None,
            'unknown_calls':unknown,'status':status,'enforcement':'advisory_only'}

def summary(c,project_id,days=7,*,all_projects=False,now=None):
    if type(days) is not int or days not in (1,7,30,90):raise ValueError('Days must be 1, 7, 30 or 90')
    if not all_projects and not project_id:raise ValueError('Project required')
    now=int(time.time()) if now is None else int(now)
    t,a,d,p,truncated=collect(c,project_id,now-days*86400,now+1,all_projects)
    return {'schema':'orbit.ai-cost.v1','currency':'USD','scope':'all' if all_projects else 'project','project_id':project_id,'days':days,
            'totals':public(t),'by_agent_model':[dict(project_id=k[0],agent_id=k[1],provider=k[2],model=k[3],purpose=k[4],**public(v)) for k,v in a.items()],
            'daily':[dict(day=k,**public(v)) for k,v in sorted(d.items())],
            'by_project':[dict(project_id=k,**public(v)) for k,v in p.items()] if all_projects else [],
            'groups_truncated':truncated,'budget':None if all_projects else budget(c,project_id,now),
            'note':'Estimated token charges only; not an invoice. Local loopback Ollama without credentials is assumed zero API fees unless an explicit rate overrides it. Compute, electricity, tax, discounts, cache pricing and non-token charges are excluded.'}
