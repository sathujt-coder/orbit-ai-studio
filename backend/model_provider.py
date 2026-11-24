"""Server-side, lane-specific OpenAI-compatible transport. No demo fallback."""
from dataclasses import dataclass, field
import json
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

KINDS={'demo','ollama','openai-compatible'}
DEFAULT_URL='http://127.0.0.1:11434/v1'
MAX_RESPONSE=4_000_000

class ProviderError(RuntimeError):
    pass

class BudgetError(ProviderError):
    """Local budget or circuit refusal, before outbound inference."""
    pass

class RoutingError(ProviderError):
    """No eligible pre-dispatch pair; no provider request has been sent."""
    pass

class ConcurrencyError(ProviderError):
    """A bounded local inference slot could not be acquired; no request was sent."""
    pass

class ResourceError(ProviderError):
    """Local admission refused before a provider request."""
    pass

class OutputError(ProviderError):
    """A response was incomplete or unusable; a bounded format retry is allowed."""
    def __init__(self,message,code="invalid_output"):
        super().__init__(message)
        self.code=code

@dataclass(frozen=True)
class Lane:
    lane:str
    provider:str
    base_url:str
    model:str
    api_key:str=field(repr=False)
    timeout:int=150
    temperature:float=0.45
    context_window:int=8192
    max_tokens:int=4096

    def public(self):
        return {'provider':self.provider,'model':self.model if self.provider!='demo' else 'Demo mode',
                'configured':self.provider!='demo'}

def checked_url(value):
    try:
        u=urlsplit(value)
        port=u.port
        if not u.hostname or u.username is not None or u.password is not None or u.query or u.fragment:
            raise ValueError()
        if any(ord(ch)<33 or ord(ch)==127 for ch in value) or '\\' in value:
            raise ValueError()
        if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('localhost','127.0.0.1','::1')):
            raise ValueError()
        if not u.path.rstrip('/').endswith('/v1'):
            raise ValueError()
        return value.rstrip('/')
    except (ValueError,TypeError):
        raise ValueError('Provider URL must be HTTPS or loopback HTTP, with a /v1 API path and no credentials/query') from None

def load_config(env):
    common=env.get('AI_PROVIDER','demo').strip().lower()
    if common not in KINDS:raise ValueError('Unknown AI_PROVIDER')
    shared_url=env.get('AI_BASE_URL',DEFAULT_URL)
    shared_model=env.get('AI_MODEL','qwen3:8b')
    model_a=env.get('AI_MODEL_A',shared_model)
    lanes={}
    for name in ('A','B'):
        kind=env.get('AI_PROVIDER_'+name,common).strip().lower()
        if kind not in KINDS:raise ValueError('Unknown provider for lane '+name)
        model=env.get('AI_MODEL_'+name,model_a).strip()
        if not model or len(model)>200 or any(ord(ch)<32 or ord(ch)==127 for ch in model):
            raise ValueError('Invalid model ID for lane '+name)
        raw_url=env.get('AI_BASE_URL_'+name,shared_url)
        url=checked_url(raw_url) if kind!='demo' else ''
        # A shared key may only be inherited by the same configured endpoint.
        fallback=env.get('AI_API_KEY','') if raw_url.rstrip('/')==shared_url.rstrip('/') else ''
        key=env.get('AI_API_KEY_'+name,fallback) if kind!='demo' else ''
        if len(key)>4096 or any(ord(ch)<33 or ord(ch)>126 for ch in key):
            raise ValueError('Invalid API key format for lane '+name)
        try:timeout=int(env.get('AI_TIMEOUT_'+name,env.get('AI_TIMEOUT','150')))
        except (ValueError,TypeError):raise ValueError('Invalid AI timeout') from None
        if not 1<=timeout<=600:raise ValueError('AI timeout must be 1–600 seconds')
        lanes[name]=Lane(name,kind,url,model,key,timeout)
    if (lanes['A'].provider=='demo')!=(lanes['B'].provider=='demo'):
        raise ValueError('Mixing demo and real lanes is not supported')
    return lanes

def mode(lanes):
    a,b=lanes['A'],lanes['B']
    return a.provider if a.provider==b.provider else 'split'

def public_config(lanes):
    return {'mode':mode(lanes),'modelA':lanes['A'].public()['model'],'modelB':lanes['B'].public()['model'],
            'lanes':{k:v.public() for k,v in lanes.items()},'live_verified':False}

def require_distinct_real(lanes):
    if any(v.provider=='demo' for v in lanes.values()) or lanes['A'].model==lanes['B'].model:
        raise ValueError('Two distinct explicit real model IDs required')
    return lanes

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None

def token_usage(data,native):
    def count(value):return value if type(value) is int and 0<=value<=1_000_000_000 else None
    data=data if isinstance(data,dict) else {}
    raw=data if native else data.get('usage')
    raw=raw if isinstance(raw,dict) else {}
    i=count(raw.get('prompt_eval_count' if native else 'prompt_tokens'))
    o=count(raw.get('eval_count' if native else 'completion_tokens'))
    t=None if native else count(raw.get('total_tokens'))
    coverage='unknown'
    if i is not None and o is not None:
        if t is not None and t!=i+o:
            coverage='inconsistent';t=None
        else:coverage='complete';t=i+o
    elif any(x is not None for x in (i,o,t)):coverage='partial'
    return {'input_tokens':i,'output_tokens':o,'total_tokens':t,'coverage':coverage,
            'source':('ollama_native' if native else 'openai_usage') if coverage!='unknown' else 'none'}

def chat(lane,system,user,*,max_tokens=None,schema=None,repair_temperature=None,runtime_settings=False,usage_observer=None):
    if lane.provider=='demo':raise ProviderError('Demo lane cannot call a real provider')
    if runtime_settings and max_tokens is None:max_tokens=lane.max_tokens
    payload={'model':lane.model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
             'temperature':lane.temperature,'stream':False}
    native=schema is not None and lane.provider=='ollama'
    endpoint=lane.base_url+'/chat/completions'
    if repair_temperature is not None and (not native or type(repair_temperature) not in (int,float) or not 0<=repair_temperature<=0.5):
        raise ValueError('Repair temperature must be 0–0.5 for native structured Ollama')
    if native:
        endpoint=lane.base_url[:-3]+'/api/chat'
        payload.pop('temperature')
        payload['format']=schema
        payload['options']={'temperature':0 if repair_temperature is None else repair_temperature,'num_predict':max_tokens or 4096}
    elif max_tokens is not None:payload['max_tokens']=max_tokens
    if runtime_settings and lane.provider=='ollama':
        # Use native Ollama transport for configured context, even for free text.
        native=True
        endpoint=lane.base_url[:-3]+'/api/chat'
        payload.pop('temperature',None);payload.pop('max_tokens',None)
        payload.setdefault('options',{'temperature':lane.temperature,'num_predict':max_tokens or lane.max_tokens})
        payload['options']['num_ctx']=lane.context_window
    headers={'Content-Type':'application/json','Accept':'application/json'}
    if lane.api_key:headers['Authorization']='Bearer '+lane.api_key
    request=urllib.request.Request(endpoint,
        data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),headers=headers,method='POST')
    # Prevent automatic redirect or proxy environment from forwarding lane credentials.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    started=time.monotonic();usage=token_usage(None,native);status='provider_error'
    try:
        with opener.open(request,timeout=lane.timeout) as response:
            raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:raise ProviderError('Provider response too large')
        data=json.loads(raw)
        usage=token_usage(data,native)
        if native:
            if data.get('done') is not True or data.get('done_reason')=='length':
                raise OutputError('Incomplete structured output','truncated_or_incomplete')
            content=data['message']['content']
        else:
            choice=data['choices'][0]
            if schema is not None and choice.get('finish_reason')=='length':raise OutputError('Incomplete structured output','truncated_or_incomplete')
            content=choice['message']['content']
        if not isinstance(content,str):raise OutputError('Invalid model content','non_string_content')
        content=re.sub(r'<think>[\s\S]*?</think>','',content,flags=re.I).strip()
        if not content or len(content)>100_000:raise OutputError('Empty or oversized model content','empty_or_oversized_content')
        status='ok'
        return content
    except OutputError:
        status='output_error';raise
    except urllib.error.HTTPError as exc:
        code=exc.code
        exc.close()
        raise ProviderError('Lane '+lane.lane+' provider HTTP '+str(code)) from None
    except (OSError,ValueError,KeyError,IndexError,TypeError,urllib.error.URLError):
        raise ProviderError('Lane '+lane.lane+' provider connection or response failed') from None
    finally:
        if usage_observer is not None:
            usage_observer(dict(usage,status=status,elapsed_ms=round((time.monotonic()-started)*1000)))

def probe(lanes,chat_fn=None):
    """Explicit caller opt-in required. Sends no project data; does not return raw output."""
    require_distinct_real(lanes)
    results={}
    for name,lane in lanes.items():
        started=time.monotonic()
        try:
            reply=(chat_fn or chat)(lane,'Reply with exactly ORBIT_READY and nothing else.','ORBIT connection check',max_tokens=64)
            results[name]={'status':'responded','instruction_match':reply=='ORBIT_READY'}
        except ProviderError as exc:
            results[name]={'status':'failed','error':str(exc)}
        results[name]['elapsed_ms']=round((time.monotonic()-started)*1000)
    return {'mode':'live_probe','lanes':results,'both_responded':all(r['status']=='responded' for r in results.values()),
            'note':'Connectivity only, not model independence, quality or sandbox verification.'}


def list_models(lane):
    if lane.provider=='demo':raise ProviderError('Demo has no real model list')
    endpoint=lane.base_url+'/models'
    headers={'Accept':'application/json'}
    if lane.api_key:headers['Authorization']='Bearer '+lane.api_key
    request=urllib.request.Request(endpoint,headers=headers,method='GET')
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect()).open(request,timeout=lane.timeout) as response:
            raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:raise ValueError('Oversized model list')
        data=json.loads(raw)['data']
        if not isinstance(data,list):raise ValueError('Invalid model list')
        return sorted({x['id'] for x in data[:1000] if isinstance(x,dict) and isinstance(x.get('id'),str)
                       and 0<len(x['id'])<=200 and all(ord(c)>=32 and ord(c)!=127 for c in x['id']) and
                       (lane.provider!='ollama' or 'cloud' not in x['id'].lower())})[:200]
    except (OSError,ValueError,KeyError,TypeError,urllib.error.URLError):
        raise ProviderError('Model listing failed') from None
