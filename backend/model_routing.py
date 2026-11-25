"""P5.6: deterministic, deployment-approved pair routing; never replay inference."""
import hashlib,json,re,time
from urllib.parse import urlsplit
import model_provider as mp
import provider_settings as ps
import cost_store

DEPARTMENTS=('po','research','ba','pm','design','techlead','dev','qa','qc','security','devops','marketing')
SPECIALTY={'po':'reasoning','research':'research','ba':'reasoning','pm':'reasoning','design':'design','techlead':'coding','dev':'coding','qa':'coding','qc':'coding','security':'security','devops':'coding','marketing':'marketing'}
CAPABILITIES={'general','coding','reasoning','research','design','security','marketing','structured'}
KINDS=('stage','coding','chat','requirements','planning')
MIB=1024**2

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def integer(x,low,high):
    return type(x) is int and low<=x<=high

def local(lane):
    return lane.provider=='ollama' and urlsplit(lane.base_url).hostname in ('localhost','127.0.0.1','::1') and not lane.api_key and 'cloud' not in lane.model.lower()

def load(env,initial):
    mode=env.get('ORBIT_ROUTING_MODE','fixed')
    if mode not in ('fixed','smart'):raise ValueError('Invalid routing mode')
    allow_remote=env.get('ORBIT_ROUTING_ALLOW_REMOTE','0')
    if allow_remote not in ('0','1'):raise ValueError('Invalid routing remote opt-in')
    cap=cost_store.money(env.get('ORBIT_ROUTING_MAX_RATE_USD_PER_MILLION','0'),10000)
    if mode=='fixed':
        return {'mode':mode,'allow_remote':False,'max_rate':0,'registry':{'A':[],'B':[]},'fingerprint':None}
    raw=env.get('ORBIT_ROUTING_REGISTRY','')
    if not raw or len(raw)>65536:raise ValueError('Smart routing requires bounded registry JSON')
    data=json.loads(raw)
    if not isinstance(data,dict) or set(data)!={'A','B'}:raise ValueError('Registry must contain A and B pools')
    allow=ps.endpoints(env,initial);registry={};ids=set();models={'A':set(),'B':set()}
    for name,items in data.items():
        if not isinstance(items,list) or not 1<=len(items)<=16:raise ValueError('Each lane requires 1–16 candidates')
        registry[name]=[]
        for item in items:
            if not isinstance(item,dict) or set(item)!={'id','settings','capabilities','quality','min_ram_mib','min_vram_mib','min_cpu_cores'}:raise ValueError('Invalid registry candidate fields')
            ident=item['id'];caps=item['capabilities'];quality=item['quality'];ram=item['min_ram_mib'];vram=item['min_vram_mib'];cpu=item['min_cpu_cores']
            if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',ident) or ident in ids:raise ValueError('Invalid or duplicate candidate ID')
            if not isinstance(caps,list) or not caps or any(not isinstance(x,str) or x not in CAPABILITIES for x in caps) or len(set(caps))!=len(caps):raise ValueError('Invalid capabilities')
            if not integer(quality,0,100) or not integer(ram,0,1048576) or not integer(vram,0,1048576) or not integer(cpu,0,128):raise ValueError('Invalid candidate resource/quality fields')
            lane=ps.validate_lane(name,item['settings'],allow)
            if lane.provider=='demo':raise ValueError('Demo cannot be a smart candidate')
            if not local(lane) and (ram or vram or cpu):raise ValueError('Remote hardware requirements cannot be evaluated by this backend')
            # Disjoint model IDs across pools prevent A/B sharing an explicit model ID.
            ids.add(ident);models[name].add(lane.model.casefold())
            registry[name].append({'id':ident,'lane':lane,'capabilities':tuple(sorted(caps)),'quality':quality,'min_ram_mib':ram,'min_vram_mib':vram,'min_cpu_cores':cpu})
    if models['A'] & models['B']:raise ValueError('A/B candidate model IDs must be disjoint')
    result={'mode':mode,'allow_remote':allow_remote=='1','max_rate':cap,'registry':registry}
    result['fingerprint']=digest(public(result))
    return result

def public(config):
    return {'mode':config['mode'],'allow_remote':config['allow_remote'],'max_rate_usd_per_million':cost_store.usd(config['max_rate']*10**6),
            'registry':{k:[{**{x:v for x,v in r.items() if x!='lane'},'settings':ps.lane_form(r['lane']),
                             'key_configured':bool(r['lane'].api_key),'local_candidate':local(r['lane'])} for r in rows] for k,rows in config['registry'].items()},
            'quality_source':'operator_declared_not_benchmark','resource_scope':'backend_visible_only'}

def classify(department,kind,chars):
    if department not in DEPARTMENTS or kind not in KINDS or not integer(chars,0,1000000):raise ValueError('Invalid routing task metadata')
    high=kind=='coding' or department in ('techlead','security','devops') or chars>=4000
    return {'department':department,'kind':kind,'complexity':'high' if high else 'standard',
            'specialty':SPECIALTY[department],'structured':kind in ('coding','requirements','planning'),'min_context':8192 if high or kind in ('requirements','planning') else 4096}

def evaluate(c,candidate,task,config,metrics,gpu):
    lane=candidate['lane'];is_local=local(lane);caps=candidate['capabilities']
    rate=cost_store.current_rate(c,lane.provider,cost_store.endpoint_id(lane.provider,lane.base_url),lane.model)
    # Local assumption matches P5.2; an explicit disabled or nonzero rate overrides it.
    zero=bool(is_local and (rate is None or (rate[3] and rate[1]==0 and rate[2]==0)))
    if not is_local and not config['allow_remote']:return None,'remote_not_opted_in'
    if not zero:
        if not config['allow_remote']:return None,'nonzero_or_unknown_cost'
        if not rate or not rate[3] or rate[1] is None or rate[2] is None:return None,'rate_unknown'
        if max(rate[1],rate[2])>config['max_rate']:return None,'rate_above_ceiling'
    if task['structured'] and 'structured' not in caps:return None,'structured_not_declared'
    if task['specialty'] not in caps and 'general' not in caps:return None,'capability_mismatch'
    if lane.context_window<task['min_context']:return None,'context_too_small'
    ram=metrics.get('effective_memory_available_bytes');cpu=metrics.get('effective_cpu_cores')
    if candidate['min_ram_mib'] and (ram is None or ram<candidate['min_ram_mib']*MIB):return None,'ram_unavailable_or_low'
    if candidate['min_cpu_cores'] and (cpu is None or cpu<candidate['min_cpu_cores']):return None,'cpu_unavailable_or_low'
    if candidate['min_vram_mib']:
        free=[x['vram_total_bytes']-x['vram_used_bytes'] for x in (gpu or {}).get('devices',[])]
        if not free or max(free)<candidate['min_vram_mib']*MIB:return None,'vram_unavailable_or_low'
    price=0 if zero else rate[1]+rate[2]
    specialty=int(task['specialty'] in caps)
    # Lexicographic score: prefer offline candidates, then declared specialty;
    # high complexity prefers declared quality, standard prefers lower rate/RAM.
    common=(int(is_local),int(zero),specialty)
    score=common+((candidate['quality'],-price,-candidate['min_ram_mib']) if task['complexity']=='high' else (-price,-candidate['min_ram_mib'],candidate['quality']))
    return {'score':score,'id':candidate['id'],'provider':lane.provider,'model':lane.model,'local_candidate':is_local,
            'rate_id':rate[0] if rate else None,'cost_basis':'local_assumed_zero' if zero and rate is None else 'rated',
            'quality':candidate['quality'],'specialty_match':bool(specialty)},None

def select(c,config,base,task,metrics=None,gpu=None):
    decision={'schema':'orbit.model-routing.v1','mode':config['mode'],'task':task,'policy_fingerprint':config['fingerprint'],
              'selected':{},'excluded':{},'status':'selected','reason':'configured_pair'}
    if mp.mode(base)=='demo' or config['mode']=='fixed':
        decision['reason']='demo_no_inference' if mp.mode(base)=='demo' else 'fixed_explicit_configuration'
        decision['selected']={k:{'model':v.model,'provider':v.provider,'id':'configured-'+k} for k,v in base.items()}
        return dict(base),decision
    metrics=metrics or {};chosen={}
    for name in 'AB':
        eligible=[];excluded=[]
        for candidate in config['registry'][name]:
            info,why=evaluate(c,candidate,task,config,metrics,gpu)
            if info:eligible.append((info,candidate))
            else:excluded.append({'id':candidate['id'],'reason':why})
        decision['excluded'][name]=excluded
        if eligible:
            info,candidate=sorted(eligible,key=lambda x:(tuple(-v for v in x[0]['score']),x[0]['id']))[0]
            decision['selected'][name]=info;chosen[name]=candidate['lane']
    if set(chosen)!={'A','B'}:
        decision.update(status='blocked',reason='no_eligible_distinct_pair',selected={})
        return None,decision
    mp.require_distinct_real(chosen)
    decision['reason']='offline_first_ranked_pair'
    return chosen,decision

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS routing_decisions(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, run_id TEXT,
        department TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
        decision TEXT NOT NULL, created_at INTEGER NOT NULL)""")
    c.execute('CREATE INDEX IF NOT EXISTS routing_project ON routing_decisions(project_id,seq DESC)')

def record(c,pid,run_id,decision):
    task=decision['task']
    c.execute('INSERT INTO routing_decisions(project_id,run_id,department,kind,status,decision,created_at) VALUES(?,?,?,?,?,?,?)',
              (pid,run_id,task['department'],task['kind'],decision['status'],json.dumps(decision,ensure_ascii=False),int(time.time())))

def history(c,pid=None,*,all_projects=False):
    where='' if all_projects else ' WHERE project_id=?'
    rows=c.execute('SELECT seq,project_id,run_id,decision,created_at FROM routing_decisions'+where+' ORDER BY seq DESC LIMIT 100',() if all_projects else (pid,)).fetchall()
    return [{'id':r[0],'project_id':r[1],'run_id':r[2],'decision':json.loads(r[3]),'created_at':r[4]} for r in rows]
