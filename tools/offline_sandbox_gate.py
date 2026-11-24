#!/usr/bin/env python3
"""P4.6: narrow arithmetic acceptance for actual offline-model candidates.

Never import candidate code on the host. This is a fixed synthetic benchmark,
not a general Python security sandbox or production approval.
"""
import argparse
import ast
import hashlib
import json
import re
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
class NarrowError(ValueError):
    def __init__(self,message,line=None):
        super().__init__(message)
        self.line=line

def narrow_check(source,is_test):
    """Restrict generated code to a tiny arithmetic/unittest subset before Docker."""
    tree=ast.parse(source)
    for n in ast.walk(tree):
        if type(n) not in COMMON|(TEST_EXTRA if is_test else set()):
            raise NarrowError('unsupported syntax: '+type(n).__name__,getattr(n,'lineno',None))
        if isinstance(n,ast.Name) and n.id.startswith('_') and not (is_test and n.id=='__name__'):
            raise NarrowError('private name forbidden',getattr(n,'lineno',None))
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)):
            if n.name.startswith('_') or n.decorator_list:raise NarrowError('private or decorated definition',getattr(n,'lineno',None))
        if isinstance(n,ast.Constant):
            if type(n.value) is int and n.value.bit_length()>128:raise NarrowError('integer too large',getattr(n,'lineno',None))
            if isinstance(n.value,str) and len(n.value)>1000:raise NarrowError('string too large',getattr(n,'lineno',None))
        if isinstance(n,ast.Import) and any(a.name!='unittest' or a.asname for a in n.names):
            raise NarrowError('only unittest import allowed',getattr(n,'lineno',None))
        if isinstance(n,ast.ImportFrom) and (n.level or n.module not in ('main','unittest') or any(a.asname or a.name not in ({'add'} if n.module=='main' else {'TestCase','main'}) for a in n.names)):
            raise NarrowError('unexpected from import',getattr(n,'lineno',None))
        if isinstance(n,ast.Attribute) and n.attr not in TEST_ATTR:raise NarrowError('unexpected attribute',getattr(n,'lineno',None))
        if isinstance(n,ast.Call):
            fn=n.func
            if isinstance(fn,ast.Name):
                if fn.id not in TEST_CALL|{'main'}:raise NarrowError('unexpected function call',getattr(n,'lineno',None))
            elif not (isinstance(fn,ast.Attribute) and isinstance(fn.value,ast.Name) and
                      ((fn.value.id=='self' and fn.attr.startswith('assert')) or
                       (fn.value.id=='unittest' and fn.attr=='main'))):
                raise NarrowError('unexpected method call',getattr(n,'lineno',None))
    if not is_test:
        defs=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
        if len(defs)!=1 or defs[0].name!='add' or any(not isinstance(n,ast.FunctionDef) and not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)) for n in tree.body):
            raise NarrowError('only add function and optional docstring allowed',1)
        args=defs[0].args
        if len(args.args)!=2 or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults:
            raise NarrowError('add must take two positional arguments',defs[0].lineno)

EXPECTED_FILES=('main.py','test_main.py')
STATIC_GUIDANCE={
    'PYTHON_SYNTAX':'Return valid Python syntax with real newlines and indentation.',
    'POSSIBLE_SECRET':'Remove credential-like content; write fresh minimal source.',
    'DANGEROUS_IMPORT':'Remove forbidden imports. main.py must have no imports; tests only unittest and from main import add.',
    'DYNAMIC_EXECUTION':'Remove dynamic execution calls.',
    'HOST_COMMAND':'Remove host command calls.',
    'UNSUPPORTED_FORMAT':'Return only the two requested Python files.',
}
def preflight(proposal):
    plan=vf.plan_lane(proposal)
    files={f['path']:f['content'] for f in proposal['files']}
    findings=[]
    for path in EXPECTED_FILES:
        if path not in files:findings.append({'path':path,'code':'MISSING_FILE','line':None,'message':'Generate the missing required file.'})
    if set(files)-set(EXPECTED_FILES):
        findings.append({'path':None,'code':'EXTRA_FILES','line':None,'message':'Return only main.py and test_main.py.'})
    for finding in plan['findings']:
        code=finding['code']
        findings.append({'path':finding['path'] if finding['path'] in EXPECTED_FILES else None,
                         'code':code,'line':finding.get('line'),'message':STATIC_GUIDANCE.get(code,'Remove the prohibited construct.')})
    for reason in plan['blocking_reasons']:
        if reason!='STATIC_SCAN_BLOCK':
            findings.append({'path':None,'code':reason,'line':None,'message':'Provide the required Python implementation and tests.'})
    for path in EXPECTED_FILES:
        if path not in files:continue
        try:narrow_check(files[path],path=='test_main.py')
        except SyntaxError as exc:
            if not any(f['path']==path and f['code']=='PYTHON_SYNTAX' for f in findings):
                findings.append({'path':path,'code':'PYTHON_SYNTAX','line':exc.lineno,'message':STATIC_GUIDANCE['PYTHON_SYNTAX']})
        except NarrowError as exc:
            findings.append({'path':path,'code':'NARROW_POLICY','line':exc.line,'message':str(exc)})
    return findings

def feedback_text(findings):
    return '; '.join(f"{f['path'] or 'proposal'}:{f['line'] or '?'} [{f['code']}] {f['message']}" for f in findings)[:2000]


def contract_command():
    # The trusted harness imports only main.py inside a fresh container. The
    # generated tests are absent; the host independently checks exact values.
    return ['python','-I','-B','-c',
            'import sys,json;sys.path.insert(0,"/work");from main import add;'
            +'print(json.dumps([add(a,b) for a,b in '+repr(CASES)+']))']
def sanitized(step):
    result={k:step.get(k) for k in ('step','image','executed','passed','exit_code','test_count')}
    if step['passed']:return result
    if not step['executed'] or step['exit_code'] in (125,126,127):
        result['diagnostic']='sandbox_infrastructure_failure'
    elif step['step']=='independent_add_contract':
        result['diagnostic']='independent_contract_failed'
    else:
        # Fixed labels only: no raw output, paths, prompts, test inputs or secrets.
        output=step.get('output','')
        labels=('ModuleNotFoundError','ImportError','NameError','TypeError','AttributeError','SyntaxError','IndentationError','AssertionError','ValueError')
        found=[label for label in labels if re.search(r'(?m)^'+label+r':',output)]
        result['diagnostic']=','.join(found) if found else ('no_tests_discovered' if not step.get('test_count') else 'unit_test_failed')
        counts=re.search(r'FAILED \(([^)]+)\)',output)
        if counts:
            result['failure_counts']={k:int(v) for k,v in re.findall(r'\b(failures|errors)=(\d{1,6})\b',counts[1])}
    return result

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
        findings=preflight(p)
        item['static_findings']=findings
        if findings:
            item['reason']=feedback_text(findings)
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

def repair_plan(j,report):
    """Trusted operator's next-round plan, tied to the exact reviewed source."""
    proposals=vf.safe_job(j)
    if (report.get('profile')!=PROFILE or report.get('job_id')!=j['id'] or
        report.get('project_id')!=j['project_id'] or report.get('gate')!='BLOCK' or
        set(report.get('lanes',{}))!={'A','B'}):
        raise ValueError('Previous blocked sandbox report required')
    result={}
    for lane,p in proposals.items():
        item=report['lanes'][lane]
        if item.get('sha256')!=vf.plan_lane(p)['sha256']:
            raise ValueError('Repair evidence source hash mismatch')
        status=item.get('status')
        if status not in ('passed','blocked','failed'):raise ValueError('Unexpected lane status')
        steps=item.get('steps',[])
        if any(s.get('diagnostic')=='sandbox_infrastructure_failure' or not s.get('executed') or s.get('exit_code') in (125,126,127) for s in steps):
            raise ValueError('Fix sandbox infrastructure instead of regenerating code')
        if status=='passed':
            if len(steps)!=2 or {s.get('step') for s in steps}!={'python_tests','independent_add_contract'} or not all(s.get('passed') is True for s in steps):
                raise ValueError('Missing passing evidence')
            result[lane]={'proposal':p,'reuse':True,'feedback':''}
        else:
            reasons=[]
            if status=='blocked':
                # Static scanner reason is authored by the trusted gate, not model output.
                current_findings=preflight(p)
                reasons.append('Static gate: '+(feedback_text(current_findings) if current_findings else str(item.get('reason','unsupported syntax'))[:160]))
            for s in steps:
                if not s.get('passed'):
                    reasons.append(str(s.get('step'))+': '+str(s.get('diagnostic','failed'))[:100])
            result[lane]={'proposal':p,'reuse':False,'feedback':'; '.join(reasons) or 'Sandbox gate failed',
                          'static_findings':preflight(p) if status=='blocked' else []}
    if all(x['reuse'] for x in result.values()):raise ValueError('No failed lane to repair')
    return result


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
