"""Declarative Python call contract. Validation only: never import or execute targets."""
import json
import math
import re
import keyword

SCHEMA='orbit.acceptance-assertion.v1'
PUBLIC=re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z')
EXCEPTIONS=('ValueError','TypeError','ZeroDivisionError','IndexError','KeyError','OverflowError','AssertionError')
MAX_DEPTH=8
MAX_NODES=256
MAX_BYTES=8192

def exact(value,keys):
    if type(value) is not dict or set(value)!=set(keys):
        raise ValueError('Unexpected or missing assertion fields')

def identifier(value):
    if type(value) is not str or not PUBLIC.fullmatch(value) or keyword.iskeyword(value):
        raise ValueError('Only public Python identifiers supported')
    return value

def json_value(value):
    nodes=0
    def check(v,depth):
        nonlocal nodes
        nodes+=1
        if depth>MAX_DEPTH or nodes>MAX_NODES:raise ValueError('Assertion data limit exceeded')
        t=type(v)
        if v is None or t is bool:return
        if t is int:
            if not -(2**53-1)<=v<=2**53-1:raise ValueError('Integer outside interoperable JSON range')
        elif t is float:
            if not math.isfinite(v):raise ValueError('Non-finite assertion data')
        elif t is str:
            if '\x00' in v or len(v)>2048:raise ValueError('Invalid assertion string')
            try:v.encode('utf-8')
            except UnicodeError as exc:raise ValueError('Invalid Unicode data') from exc
        elif t is list:
            for item in v:check(item,depth+1)
        elif t is dict:
            for k,item in v.items():
                if type(k) is not str:raise ValueError('JSON object keys must be strings')
                check(k,depth+1);check(item,depth+1)
        else:raise ValueError('Only JSON literal data supported')
    check(value,0)
    raw=json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))
    if len(raw.encode('utf-8'))>MAX_BYTES:raise ValueError('Assertion data size exceeded')
    return json.loads(raw)

def validate(value):
    exact(value,('runtime','module','function','arguments','assertion'))
    if value['runtime']!='python':raise ValueError('Unsupported assertion runtime')
    module=identifier(value['module']);function=identifier(value['function'])
    # The future runner must resolve this module to the exact candidate-root
    # <module>.py blob and never fall back to stdlib or arbitrary import paths.
    args=value['arguments']
    if type(args) is not list or len(args)>16:raise ValueError('Invalid positional arguments')
    a=value['assertion']
    if type(a) is not dict:raise ValueError('Invalid assertion')
    op=a.get('operator')
    if op=='equals':
        exact(a,('operator','value'))
        assertion=dict(operator=op,value=json_value(a['value']))
    elif op=='raises':
        exact(a,('operator','exception'))
        if a['exception'] not in EXCEPTIONS:raise ValueError('Unsupported exception')
        assertion=dict(operator=op,exception=a['exception'])
    else:raise ValueError('Unsupported assertion operator')
    normalized=dict(runtime='python',module=module,function=function,arguments=json_value(args),assertion=assertion)
    # Combined bound, not just per-field bounds.
    if len(json.dumps(normalized,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8'))>MAX_BYTES:
        raise ValueError('Assertion contract size exceeded')
    return normalized
