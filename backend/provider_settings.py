"""Global operator-only AI settings. Persist metadata, never credential values.

Trusted deployment allowlist is the outbound trust boundary. Browser users cannot
add endpoints or select arbitrary environment variables. DNS and egress policy
remain deployment responsibilities.
"""
import json
import os
import re
import threading
import time
from dataclasses import replace
import model_provider as mp

NETWORK_LOCK=threading.Lock()
_LAST_NETWORK=0.0

def is_admin(user,env=None):
    env=os.environ if env is None else env
    return user in {x.strip() for x in env.get('ORBIT_PROVIDER_ADMINS','').split(',') if x.strip()}

def ensure_schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS provider_settings(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, config TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at INTEGER NOT NULL)')

def endpoints(env,initial):
    # Exact provider + URL keys; endpoints configured by deployment only.
    result={('ollama',mp.DEFAULT_URL):''}
    raw=json.loads(env.get('ORBIT_PROVIDER_ENDPOINTS','[]'))
    if not isinstance(raw,list) or len(raw)>32:raise ValueError('Invalid deployment endpoint allowlist')
    for item in raw:
        if not isinstance(item,dict) or set(item)-{'provider','url','key_env'}:raise ValueError('Invalid trusted endpoint')
        kind=item.get('provider');url=mp.checked_url(item.get('url',''))
        name=item.get('key_env','')
        if kind not in ('ollama','openai-compatible') or not isinstance(name,str) or (name and not re.fullmatch(r'ORBIT_PROVIDER_KEY_[A-Z0-9_]{1,80}',name)):
            raise ValueError('Invalid trusted endpoint configuration')
        key=(kind,url)
        if key in result and result[key] and result[key]!=env.get(name,''):raise ValueError('Conflicting endpoint credentials')
        result[key]=env.get(name,'') if name else ''
    for lane in initial.values():
        if lane.provider=='demo':continue
        key=(lane.provider,lane.base_url)
        if key in result and result[key] and lane.api_key and result[key]!=lane.api_key:
            raise ValueError('Conflicting startup and endpoint credentials')
        result[key]=result.get(key) or lane.api_key
    return result

def lane_form(lane):
    return {'provider':lane.provider,'url':lane.base_url,'model':lane.model,'timeout':lane.timeout,
            'temperature':lane.temperature,'context_window':lane.context_window,'max_tokens':lane.max_tokens}

def validate(config,env,initial):
    if not isinstance(config,dict) or set(config)!={'A','B'}:raise ValueError('Both lanes are required')
    allow=endpoints(env,initial);lanes={}
    for name,item in config.items():
        if not isinstance(item,dict) or set(item)!={'provider','url','model','timeout','temperature','context_window','max_tokens'}:
            raise ValueError('Invalid lane settings')
        kind=item['provider'];url=item['url'];model=item['model']
        if kind not in mp.KINDS or not isinstance(url,str) or not isinstance(model,str):raise ValueError('Invalid provider settings')
        if not model.strip() or len(model)>200 or any(ord(x)<32 or ord(x)==127 for x in model):
            raise ValueError('Invalid model identifier')
        if kind=='demo':
            url='';key=''
        else:
            url=mp.checked_url(url)
            if (kind,url) not in allow:raise PermissionError('Endpoint not approved by deployment operator')
            key=allow[(kind,url)]
            if kind=='ollama' and 'cloud' in model.lower():raise ValueError('Cloud-tagged Ollama models are not allowed')
        timeout,temp,ctx,tokens=(item[k] for k in ('timeout','temperature','context_window','max_tokens'))
        if type(timeout) is not int or not 1<=timeout<=600:raise ValueError('Timeout must be 1–600 seconds')
        if type(temp) not in (float,int) or not 0<=temp<=1:raise ValueError('Temperature must be 0–1')
        if type(ctx) is not int or not 1024<=ctx<=32768:raise ValueError('Context must be 1024–32768')
        if type(tokens) is not int or not 64<=tokens<=8192 or tokens>=ctx:raise ValueError('Output tokens must be 64–8192 and below context')
        if len(key)>4096 or any(ord(ch)<33 or ord(ch)>126 for ch in key):raise ValueError('Invalid deployment credential')
        lanes[name]=mp.Lane(name,kind,url,model.strip(),key,timeout,temp,ctx,tokens)
    if any(x.provider=='demo' for x in lanes.values()):
        if not all(x.provider=='demo' for x in lanes.values()):raise ValueError('Demo cannot be mixed with real providers')
    else:mp.require_distinct_real(lanes)
    return lanes

def load(c,env,initial):
    ensure_schema(c)
    row=c.execute('SELECT revision,config FROM provider_settings WHERE id=1').fetchone()
    if not row:return 0,dict(initial)
    # Invalid persisted settings fail closed; never silently switch to demo.
    return row[0],validate(json.loads(row[1]),env,initial)

def view(c,env,initial):
    revision,lanes=load(c,env,initial)
    return {'revision':revision,'mode':mp.mode(lanes),'lanes':{k:dict(lane_form(v),key_configured=bool(v.api_key)) for k,v in lanes.items()},
            'allowed_endpoints':[{'provider':k[0],'url':k[1],'key_configured':bool(v)} for k,v in endpoints(env,initial).items()],
            'credential_storage':'deployment_environment_only','live_verified':False}

def save(c,actor,body,env,initial):
    if not is_admin(actor,env):raise PermissionError('Operator required')
    if set(body)!={'revision','lanes','confirmation'} or body['confirmation']!='APPLY AI SETTINGS' or type(body['revision']) is not int:
        raise ValueError('Explicit APPLY AI SETTINGS and revision required')
    lanes=validate(body['lanes'],env,initial)
    ensure_schema(c)
    c.execute('INSERT OR IGNORE INTO provider_settings VALUES(1,0,?,?,?)',
              (json.dumps({k:lane_form(v) for k,v in initial.items()}),actor,int(time.time())))
    cursor=c.execute('UPDATE provider_settings SET revision=revision+1,config=?,updated_by=?,updated_at=? WHERE id=1 AND revision=?',
                     (json.dumps({k:lane_form(v) for k,v in lanes.items()}),actor,int(time.time()),body['revision']))
    if cursor.rowcount!=1:raise ValueError('Settings changed; reload before applying')
    return view(c,env,initial)

def network_action(body,env,initial,action):
    global _LAST_NETWORK
    if action not in ('probe','models'):raise ValueError('Unknown network action')
    if set(body)!={'lanes','confirmation'} or body['confirmation']!='TEST AI CONNECTION':
        raise ValueError('Explicit TEST AI CONNECTION required')
    lanes=validate(body['lanes'],env,initial)
    mp.require_distinct_real(lanes)
    # Bound operator-triggered outbound calls globally, never hold DB lock.
    if not NETWORK_LOCK.acquire(blocking=False):raise ValueError('Another provider check is running')
    try:
        if time.monotonic()-_LAST_NETWORK<3:raise ValueError('Provider checks are rate limited')
        _LAST_NETWORK=time.monotonic()
        lanes={k:replace(v,timeout=min(v.timeout,15)) for k,v in lanes.items()}
        if action=='probe':return mp.probe(lanes)
        result={}
        for k,v in lanes.items():
            try:result[k]={'status':'responded','models':mp.list_models(v)}
            except mp.ProviderError:result[k]={'status':'failed','models':[]}
        return {'lanes':result}
    finally:NETWORK_LOCK.release()
