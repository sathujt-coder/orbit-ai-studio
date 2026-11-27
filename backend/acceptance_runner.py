"""P6.4c.2: trusted local operator, one networkless Docker per assertion.

No HTTP execution endpoint, no persisted results yet. Candidate code never
executes on the host. A report is development evidence, not an authorization.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time
import uuid

import acceptance_assertion as ac
import engineering_test_plan as tp
import engineering_sandbox as sb
import project_planning as pp
import verification_factory as vf

FLAGS=sb.FLAGS
TIMEOUT=25
TOTAL_TIMEOUT=120
MAX_OUTPUT=16384
HEX=set('0123456789abcdef')

# Fixed trusted wrapper, not generated from the plan. It runs only in Docker.
# The candidate's stdout/stderr are discarded; observed value/exception is
# compared by the host, not by the candidate or its unit test runner.
HARNESS=r"""
import hashlib,json,os,sys,types
from pathlib import Path
spec=json.loads(sys.argv[1])
fd=os.dup(1)
write=os.write
null=os.open('/dev/null',os.O_WRONLY)
os.dup2(null,1);os.dup2(null,2);os.close(null)
dumps=json.dumps
allowed={x:getattr(__import__('builtins'),x) for x in
 ('ValueError','TypeError','ZeroDivisionError','IndexError','KeyError','OverflowError','AssertionError')}
def emit(result):
    raw=dumps(result,ensure_ascii=True,allow_nan=False,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>12000:raise ValueError('Output too large')
    write(fd,raw+b'\n')
def checked(v,depth=0,count=None):
    if count is None:count=[0]
    count[0]+=1
    if depth>8 or count[0]>256:raise ValueError('Result limit')
    t=type(v)
    if t is dict:
        if any(type(k) is not str for k in v):raise ValueError('Non-JSON key')
        return {k:checked(x,depth+1,count) for k,x in v.items()}
    if t is list:return [checked(x,depth+1,count) for x in v]
    if v is None or t in (bool,int,float,str):return v
    raise ValueError('Non-JSON result')
x=spec['execution']
path=Path('/work')/(x['module']+'.py')
try:
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=spec['module_sha256']:raise ValueError('Module digest mismatch')
    module=types.ModuleType('_orbit_exact_candidate')
    module.__file__=str(path)
    sys.path.insert(0,'/work')
    exec(compile(raw,str(path),'exec'),module.__dict__)
    fn=module.__dict__.get(x['function'])
    if (type(fn) is not types.FunctionType or fn.__code__.co_filename!=str(path)
        or fn.__name__!=x['function'] or fn.__module__!=module.__name__):
        raise ValueError('Exact function required')
except BaseException:
    emit({'observation':'error','reason':'MODULE_OR_TARGET_ERROR'})
    raise SystemExit(0)
try:
    result=fn(*x['arguments'])
except Exception as exc:
    name=next((k for k,v in allowed.items() if type(exc) is v),'OTHER')
    emit({'observation':'raised','exception':name})
except BaseException:
    emit({'observation':'error','reason':'ABNORMAL_EXIT'})
else:
    try:emit({'observation':'returned','value':checked(result)})
    except BaseException:emit({'observation':'error','reason':'INVALID_RESULT'})
"""

def sha(raw):return hashlib.sha256(raw).hexdigest()

def target(proposal,execution):
    x=ac.validate(execution)
    path=x['module']+'.py'
    files=[f for f in proposal['files'] if f['path']==path]
    if len(files)!=1:raise ValueError('Exact candidate-root module missing')
    f=files[0]
    raw=f['content'].encode('utf-8')
    if sha(raw)!=f['sha256']:raise ValueError('Module digest mismatch')
    tree=ast.parse(raw,filename=path)
    defs=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==x['function']]
    if len(defs)!=1 or type(defs[0]) is not ast.FunctionDef or defs[0].decorator_list:
        raise ValueError('One undecorated top-level synchronous function required')
    return dict(path=path,module_sha256=f['sha256'])

def transport(image,root,execution,module_sha256,timeout):
    """Bounded stdout/stderr, cleanup even on timeout or protocol overflow."""
    name='orbit-assertion-'+uuid.uuid4().hex
    payload=json.dumps(dict(execution=execution,module_sha256=module_sha256),ensure_ascii=True,allow_nan=False)
    argv=vf._docker_cmd(vf.pinned_image(image),root,['python','-I','-B','-c',HARNESS,payload],name)
    deadline=time.monotonic()+timeout
    proc=None
    complete=False
    try:
        proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        data=bytearray()
        with selectors.DefaultSelector() as sel:
            sel.register(proc.stdout,selectors.EVENT_READ)
            while True:
                left=deadline-time.monotonic()
                if left<=0 or not sel.select(left):return None,'TIMEOUT'
                chunk=os.read(proc.stdout.fileno(),4096)
                if not chunk:break
                data.extend(chunk)
                if len(data)>MAX_OUTPUT:return None,'OUTPUT_LIMIT'
        rc=proc.wait(timeout=max(0.01,deadline-time.monotonic()))
        complete=True
        if rc!=0:return None,'DOCKER_OR_PROCESS_ERROR'
        return bytes(data),None
    except subprocess.TimeoutExpired:return None,'TIMEOUT'
    except OSError:return None,'DOCKER_UNAVAILABLE'
    finally:
        if proc is not None:
            if not complete:
                if proc.poll() is None:proc.kill()
                proc.wait()
                try:subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,check=False)
                except (OSError,subprocess.TimeoutExpired):pass
            if proc.stdout:proc.stdout.close()

def classify(raw,error,execution):
    """No exit-code-only PASS; exact typed JSON equality or exact exception."""
    x=ac.validate(execution)
    if error or raw is None:return dict(status='ERROR',executed=False,reason=error or 'MISSING_OBSERVATION')
    try:
        if len(raw)>MAX_OUTPUT:raise ValueError('Output limit')
        def unique(pairs):
            out={}
            for k,v in pairs:
                if k in out:raise ValueError('Duplicate key')
                out[k]=v
            return out
        obs=json.loads(raw,object_pairs_hook=unique)
        if obs.get('observation')=='error':
            ac.exact(obs,('observation','reason'))
            if obs['reason'] not in ('MODULE_OR_TARGET_ERROR','ABNORMAL_EXIT','INVALID_RESULT'):raise ValueError('Invalid reason')
            return dict(status='ERROR',executed=False,reason=obs['reason'])
        a=x['assertion']
        if obs.get('observation')=='returned':
            ac.exact(obs,('observation','value'))
            actual=ac.json_value(obs['value'])
            # Canonical JSON preserves bool vs integer, int vs float, nested types.
            passed=a['operator']=='equals' and json.dumps(actual,sort_keys=True,separators=(',',':'),allow_nan=False)==json.dumps(a['value'],sort_keys=True,separators=(',',':'),allow_nan=False)
            detail=dict(observation='returned',value_digest=pp.digest(actual))
        elif obs.get('observation')=='raised':
            ac.exact(obs,('observation','exception'))
            if obs['exception'] not in ac.EXCEPTIONS+('OTHER',):raise ValueError('Unexpected exception observation')
            passed=a['operator']=='raises' and obs['exception']==a['exception']
            detail=dict(observation='raised',exception=obs['exception'])
        else:raise ValueError('Missing observation')
        return dict(status='PASS' if passed else 'FAIL',executed=True,reason='ASSERTION_MATCH' if passed else 'ASSERTION_MISMATCH',**detail)
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,RecursionError):
        return dict(status='ERROR',executed=False,reason='INVALID_OBSERVATION')

def execute_case(root,image,case,meta,timeout=TIMEOUT):
    x=ac.validate(case['execution'])
    path=root/meta['path']
    if path.is_symlink() or not path.is_file() or sha(path.read_bytes())!=meta['module_sha256']:
        raise ValueError('Materialized target changed')
    raw,error=transport(image,root,x,meta['module_sha256'],timeout)
    return dict(case_id=case['id'],criterion_id=case['criterion_id'],kind=case['kind'],
                assertion_digest=pp.digest(x),**meta,**classify(raw,error,x))

def current(c,db,pid,jid):
    p=tp.view(c,pid,jid)
    if p['state']!='TEST_PLAN_COVERAGE_PASS' or p['assertion_status']!='ASSERTION_CONTRACT_READY':
        raise ValueError('Current executable test plan required')
    r=p['history'][-1];e=r['snapshot']
    context,job,_=sb.current(c,db,pid,jid)
    replay=sb.view(c,db,pid,jid)
    if replay['state']!='PASS' or context['source']['bound_evidence']!=e['source']:
        raise ValueError('Current selected Git sandbox evidence required')
    receipt=replay['receipt'];lane=context['selected']
    proposal=vf.safe_job(job)[lane]
    git,_=sb.git_objects(proposal,context['source']['base_commit'],jid,lane)
    if (receipt['git'][lane]!=git or receipt['selected']!=lane
        or receipt['selection_digest']!=context['selection_digest']
        or git['source_sha256']!=context['selected_digest']):
        raise ValueError('Selected Git candidate mismatch')
    targets=[target(proposal,x['execution']) for x in e['cases']]
    source=dict(project_id=pid,job_id=jid,plan_version=e['version'],plan_digest=r['digest'],
                source_digest=e['source_digest'],assertion_contract_digest=e['assertion_contract_digest'],
                selection_digest=context['selection_digest'],sandbox_digest=receipt['digest'],
                selected=lane,candidate_digest=git['source_sha256'],git=git)
    return source,e['cases'],proposal,targets

def run(c,db,pid,jid,actor,plan_digest,source_digest,assertion_digest,sandbox_digest,confirmation,*,image):
    if confirmation!='RUN ACCEPTANCE ASSERTIONS '+jid:raise PermissionError('Explicit local confirmation required')
    image=vf.pinned_image(image)
    if c.in_transaction:raise ValueError('Idle database connection required')
    c.execute('BEGIN')
    try:
        pp.check_role(c,pid,actor,'approve')
        source,cases,proposal,targets=current(c,db,pid,jid)
        if (source['plan_digest'],source['source_digest'],source['assertion_contract_digest'],source['sandbox_digest'])!=(plan_digest,source_digest,assertion_digest,sandbox_digest):
            raise ValueError('Stale execution authorization')
        c.commit()
    except Exception:
        c.rollback();raise
    results=[]
    deadline=time.monotonic()+TOTAL_TIMEOUT
    with tempfile.TemporaryDirectory(prefix='orbit-assertion-candidate-') as work:
        root,git=sb.materialize(db,pid,jid,source['selected'],proposal,source['git']['parent'],work)
        if git!=source['git']:raise ValueError('Materialized Git identity mismatch')
        for case,meta in zip(cases,targets):
            remaining=deadline-time.monotonic()
            if remaining<=0:
                result=dict(case_id=case['id'],criterion_id=case['criterion_id'],kind=case['kind'],
                    assertion_digest=pp.digest(case['execution']),**meta,status='NOT_EXECUTED',executed=False,reason='TOTAL_TIMEOUT')
            else:result=execute_case(root,image,case,meta,min(TIMEOUT,remaining))
            results.append(result)
    c.execute('BEGIN')
    try:
        pp.check_role(c,pid,actor,'approve')
        fresh=current(c,db,pid,jid)
        if fresh!=(source,cases,proposal,targets):raise ValueError('Execution source changed during run')
        c.commit()
    except Exception:
        c.rollback();raise
    expected=[x['id'] for x in cases]
    if [x['case_id'] for x in results]!=expected:raise ValueError('Incomplete execution coverage')
    passed=all(x['executed'] is True and x['status']=='PASS' for x in results)
    report=dict(schema='orbit.acceptance-runner-report.v1',source=source,actor=actor,image=image,
                runtime='docker',network='none',workspace='read-only',results=results,
                executed_count=sum(x['executed'] for x in results),case_count=len(cases),
                gate='PASS' if passed else 'BLOCK',persisted=False,**FLAGS)
    return dict(report=report,digest=pp.digest(report))
