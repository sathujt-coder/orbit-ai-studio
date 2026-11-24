#!/usr/bin/env python3
"""P4.6: narrow arithmetic acceptance for actual offline-model candidates.

Never import candidate code on the host. This is a fixed synthetic benchmark,
not a general Python security sandbox or production approval.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import coding_factory as cf
import verification_factory as vf

PROFILE='offline-add-v1'
# Independently authored fixed contract; not sent to either generating model.
CASES=[(0,0),(2,3),(-7,3),(7,-9),(-12,-5),(1000000,-999999),
       (2**40,2**40),(-2**40,1),(17,0),(0,-21)]
COMMON={ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.Assign,
        ast.AnnAssign,ast.Expr,ast.Constant,ast.Name,ast.Load,ast.Store,
        ast.BinOp,ast.Add,ast.Sub,ast.UnaryOp,ast.USub,ast.UAdd,ast.Tuple,
        ast.If,ast.Compare,ast.Eq,ast.NotEq,ast.Pass,ast.IfExp,ast.Lt,ast.LtE,ast.Gt,ast.GtE}
TEST_EXTRA={ast.Import,ast.ImportFrom,ast.alias,ast.ClassDef,ast.Attribute,ast.Call}
TEST_ATTR={'TestCase','main','assertEqual','assertNotEqual','assertIsInstance','assertTrue','assertFalse','assertRaises'}
TEST_CALL={'add','int'}
def narrow_check(source,is_test):
    """Restrict generated code to a tiny arithmetic/unittest subset before Docker."""
    tree=ast.parse(source)
    for n in ast.walk(tree):
        if type(n) not in COMMON|(TEST_EXTRA if is_test else set()):
            raise ValueError('unsupported syntax: '+type(n).__name__)
        if isinstance(n,ast.Name) and n.id.startswith('_') and not (is_test and n.id=='__name__'):
            raise ValueError('private name forbidden')
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)):
            if n.name.startswith('_') or n.decorator_list:raise ValueError('private or decorated definition')
        if isinstance(n,ast.Constant):
            if type(n.value) is int and n.value.bit_length()>128:raise ValueError('integer too large')
            if isinstance(n.value,str) and len(n.value)>1000:raise ValueError('string too large')
        if isinstance(n,ast.Import) and any(a.name!='unittest' or a.asname for a in n.names):
            raise ValueError('only unittest import allowed')
        if isinstance(n,ast.ImportFrom) and (n.level or n.module not in ('main','unittest') or any(a.asname or a.name not in ({'add'} if n.module=='main' else {'TestCase','main'}) for a in n.names)):
            raise ValueError('unexpected from import')
        if isinstance(n,ast.Attribute) and n.attr not in TEST_ATTR:raise ValueError('unexpected attribute')
        if isinstance(n,ast.Call):
            fn=n.func
            if isinstance(fn,ast.Name):
                if fn.id not in TEST_CALL|{'main'}:raise ValueError('unexpected function call')
            elif not (isinstance(fn,ast.Attribute) and isinstance(fn.value,ast.Name) and
                      ((fn.value.id=='self' and fn.attr.startswith('assert')) or
                       (fn.value.id=='unittest' and fn.attr=='main'))):
                raise ValueError('unexpected method call')
    if not is_test:
        defs=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
        if len(defs)!=1 or defs[0].name!='add' or any(not isinstance(n,ast.FunctionDef) and not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)) for n in tree.body):
            raise ValueError('only add function and optional docstring allowed')
        args=defs[0].args
        if len(args.args)!=2 or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults:
            raise ValueError('add must take two positional arguments')

def contract_command():
    # The trusted harness imports only main.py inside a fresh container. The
    # generated tests are absent; the host independently checks exact values.
    return ['python','-I','-B','-c',
            'import sys,json;sys.path.insert(0,"/work");from main import add;'
            +'print(json.dumps([add(a,b) for a,b in '+repr(CASES)+']))']
def sanitized(step):
    return {k:step.get(k) for k in ('step','image','executed','passed','exit_code','test_count')}

def verify(j,image,approval,runner=None):
    import subprocess
    runner=runner or subprocess.run
    if approval!='RUN OFFLINE SANDBOX '+j['id']:raise PermissionError('Explicit sandbox confirmation required')
    image=vf.pinned_image(image)
    proposals=vf.safe_job(j)
    if set(j['manifest'].get('candidate_files',{}))!={'A','B'}:raise ValueError('Both reviewed manifests required')
    report={'profile':PROFILE,'job_id':j['id'],'project_id':j['project_id'],
            'image':image,'sandbox':{'runtime':'docker','network':'none','workspace':'read-only','user':'65534:65534'},
            'contract_sha256':hashlib.sha256(json.dumps(CASES,separators=(',',':')).encode()).hexdigest(),
            'created_at':vf.utc_now(),'gate':'BLOCK','production_approved':False,'lanes':{}}
    for lane,p in proposals.items():
        plan=vf.plan_lane(p)
        item={'sha256':plan['sha256'],'status':'blocked','steps':[]}
        report['lanes'][lane]=item
        files={f['path']:f['content'] for f in p['files']}
        try:
            if set(files)!={'main.py','test_main.py'} or plan['blocking_reasons']:raise ValueError('unexpected file set or static scan blocker')
            narrow_check(files['main.py'],False)
            narrow_check(files['test_main.py'],True)
        except (ValueError,SyntaxError) as exc:
            item['reason']=str(exc) if isinstance(exc,ValueError) else 'Python syntax invalid'
            continue
        with tempfile.TemporaryDirectory(prefix='orbit-offline-tests-') as work:
            workspace=vf._materialize_proposal(p,work)
            step=vf._execute_docker(image,workspace,['python','-B','-m','unittest','discover','-s','/work','-p','test_main.py','-v'],runner,30,'python_tests')
            item['steps'].append(sanitized(step))
        # Independently test regardless of generated test failure.
        with tempfile.TemporaryDirectory(prefix='orbit-offline-contract-') as work:
            workspace=vf._materialize_proposal({'files':[f for f in p['files'] if f['path']=='main.py']},work)
            independent=vf._execute_docker(image,workspace,contract_command(),runner,30,'independent_add_contract')
            try:
                actual=json.loads(independent['output'].strip())
                expected=[a+b for a,b in CASES]
                passed=independent['passed'] and type(actual) is list and len(actual)==len(expected) and all(type(x) is int and x==y for x,y in zip(actual,expected))
            except (ValueError,TypeError):passed=False
            independent['passed']=passed
            independent['test_count']=len(CASES) if passed else 0
            item['steps'].append(sanitized(independent))
        item['status']='passed' if step['passed'] and independent['passed'] else 'failed'
    report['gate']='PASS' if all(v['status']=='passed' for v in report['lanes'].values()) else 'BLOCK'
    report['completed_at']=vf.utc_now()
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--inference-report',type=Path,required=True)
    p.add_argument('--image',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--confirm',required=True)
    a=p.parse_args()
    if not a.db.is_file() or a.output.exists():p.error('Existing private DB and new output required')
    try:
        evidence=json.loads(a.inference_report.read_text())
        if evidence.get('mode')!='local_ollama' or evidence.get('workflow',{}).get('review_gate_passed') is not True:
            raise ValueError('Offline inference and review gate must pass')
        jid=evidence['workflow']['job_id']
        with closing(sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            c.row_factory=sqlite3.Row
            j=cf.detail(c,jid)
        if j['manifest'].get('candidate_files')!=evidence['workflow']['candidate_files']:
            raise ValueError('Inference report does not match stored proposal hashes')
        result=verify(j,a.image,a.confirm)
        result['models']=evidence['models']
        result['inference_report_sha256']=hashlib.sha256(a.inference_report.read_bytes()).hexdigest()
        with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
        print(json.dumps(result,indent=2))
        return 0 if result['gate']=='PASS' else 2
    except (ValueError,PermissionError,OSError,sqlite3.Error,KeyError,TypeError) as exc:
        print('Offline sandbox blocked: '+type(exc).__name__,file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
