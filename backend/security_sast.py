"""P6.5c: bounded deterministic Python AST scan. No imports/execution of candidates."""
import ast
import hashlib
import json
from pathlib import PurePosixPath
import coding_factory as cf
import security_threat_model as threat
pp=threat.pp
security=threat.security
FLAGS=dict(threat.FLAGS,scan_waiver_authorized=False)
# Rule identifiers are stable; matched operations are review candidates, not proof of exploit.
RULES={
 'SAST01':('HIGH','SR06','Dynamic code execution'),
 'SAST02':('HIGH','SR06','Host command execution'),
 'SAST03':('HIGH','SR06','Unsafe deserialization'),
 'SAST04':('HIGH','SR11','Nonliteral SQL statement'),
 'SAST05':('HIGH','SR12','TLS verification disabled'),
 'SAST06':('HIGH','SR09','Dynamic import or unresolved wildcard import'),
 'SAST07':('HIGH','SR06','Native code loading'),
 'SAST08':('HIGH','SR11','Unsafe template rendering'),
 'SAST09':('HIGH','SR07','Direct environment credential access'),
 'SAST10':('HIGH','SR09','Unverified outbound network access'),
 'SAST90':('HIGH','SR06','Python parse or complexity failure'),
 'SAST91':('HIGH','SR11','Unsupported file format'),
}
POLICY=dict(version='orbit-python-ast-baseline-v1',rules={k:dict(severity=v[0],requirement_id=v[1],description=v[2]) for k,v in RULES.items()},
    max_files=cf.MAX_FILES,max_file_bytes=cf.MAX_FILE_BYTES,max_total_bytes=cf.MAX_TOTAL_BYTES,
    max_ast_nodes=12000,languages=['python'],passive_extensions=['.md','.txt'],
    dataflow='NOT_ASSESSED',dependency_scan='NOT_ASSESSED',secret_scan='NOT_ASSESSED')
def manifest(proposal):
    validated=cf.validate_proposal(proposal)
    if proposal['files']!=validated['files']:raise ValueError('Exact candidate bytes required')
    items=[dict(path=f['path'],sha256=f['sha256']) for f in validated['files']]
    # Same ordered file manifest algorithm as verification_factory.plan_lane.
    return validated['files'],hashlib.sha256(json.dumps(items,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def scan_file(file):
    path=file['path'];content=file['content'];extension=PurePosixPath(path).suffix.lower()
    findings=set()
    def add(rule,line=1):findings.add((rule,max(1,line or 1)))
    def finish(status):
        return dict(path=path,sha256=file['sha256'],status=status),[
            dict(path=path,file_sha256=file['sha256'],line=line,rule_id=rule,
                 severity=RULES[rule][0],requirement_id=RULES[rule][1])
            for rule,line in sorted(findings,key=lambda x:(x[1],x[0]))]
    if extension in POLICY['passive_extensions']:return finish('PASSIVE_NOT_SCANNED')
    if extension!='.py':
        add('SAST91');return finish('UNSUPPORTED')
    try:
        tree=ast.parse(content,filename='<candidate>',mode='exec')
        nodes=list(ast.walk(tree))
        if len(nodes)>POLICY['max_ast_nodes']:raise ValueError('AST limit')
    except (SyntaxError,ValueError,RecursionError,MemoryError) as e:
        add('SAST90',getattr(e,'lineno',1));return finish('ERROR')
    # Conservative alias resolution: keep all import alternatives across scopes.
    aliases={}
    def alias(local,qualified):aliases.setdefault(local,set()).add(qualified)
    for n in nodes:
        if isinstance(n,ast.Import):
            for a in n.names:alias(a.asname or a.name.split('.')[0],a.name if a.asname else a.name.split('.')[0])
        elif isinstance(n,ast.ImportFrom):
            if n.level or not n.module:continue
            for a in n.names:
                if a.name=='*':add('SAST06',n.lineno)
                else:alias(a.asname or a.name,n.module+'.'+a.name)
    def qualified(n):
        # Bound iterative attribute resolution, no candidate evaluation.
        parts=[]
        while isinstance(n,ast.Attribute):
            parts.append(n.attr);n=n.value
        if not isinstance(n,ast.Name):return set()
        return {'.'.join([x,*reversed(parts)]) for x in aliases.get(n.id,set())|{n.id}}
    for n in nodes:
        if not isinstance(n,ast.Call):continue
        names=qualified(n.func);line=n.lineno
        for name in names:
            if name in {'eval','exec','compile','builtins.eval','builtins.exec','builtins.compile'}:add('SAST01',line)
            if name in {'os.system','os.popen','os.execl','os.execv','os.spawnl'} or name.startswith('subprocess.'):add('SAST02',line)
            if name in {'pickle.load','pickle.loads','dill.load','dill.loads','marshal.load','marshal.loads','yaml.unsafe_load'}:add('SAST03',line)
            if name=='yaml.load' and not any(k.arg=='Loader' and qualified(k.value)&{'yaml.SafeLoader','yaml.CSafeLoader'} for k in n.keywords):add('SAST03',line)
            if name in {'__import__','builtins.__import__','importlib.import_module'}:add('SAST06',line)
            if name.startswith('ctypes.'):add('SAST07',line)
            if name in {'flask.render_template_string','jinja2.Template'}:add('SAST08',line)
            if name in {'os.getenv','os.environ.get','os.environ.__getitem__'}:add('SAST09',line)
            if name.startswith(('requests.','httpx.','urllib.request.','socket.')):add('SAST10',line)
            if name=='ssl._create_unverified_context' or (name.startswith(('requests.','httpx.','urllib3.')) and any(k.arg=='verify' and isinstance(k.value,ast.Constant) and k.value.value is False for k in n.keywords)):add('SAST05',line)
        if isinstance(n.func,ast.Attribute) and n.func.attr in ('execute','executemany','executescript'):
            if not n.args or not isinstance(n.args[0],ast.Constant) or not isinstance(n.args[0].value,str):add('SAST04',line)
    for n in nodes:
        if isinstance(n,ast.Subscript) and 'os.environ' in qualified(n.value):add('SAST09',n.lineno)
    return finish('SCANNED')
def evaluate(pid,jid,model,proposal):
    out=dict(schema='orbit.security-sast.v1',project_id=pid,job_id=jid,state='BLOCK',security_gate='BLOCK',
        scope='selected_candidate_python_ast_baseline',scan_verdict='NOT_ASSESSED',source=None,
        policy_digest=pp.digest(POLICY),files=[],findings=[],**FLAGS)
    try:
        if (model['schema']!='orbit.security-threat-model.v1' or (model['project_id'],model['job_id'])!=(pid,jid)
            or model['evidence_digest']!=pp.digest({k:v for k,v in model.items() if k!='evidence_digest'})
            or model['security_gate']!='BLOCK' or any(model.get(k) is not False for k in threat.FLAGS)
            or model['candidate_analysis']!='NOT_ASSESSED' or model['state'] not in ('BLOCK','THREAT_MODEL_READY')):
            raise ValueError('Invalid threat evidence')
        catalog=threat.catalog()
        if model['catalog_digest']!=pp.digest(catalog) or any(model[k]!=catalog[k] for k in ('assets','boundaries','threats','requirements')):
            raise ValueError('Invalid threat catalog')
        src=model['source']
        if not src:raise ValueError('No exact source')
        files,digest=manifest(proposal)
        if digest!=src['candidate_digest'] or not all(security.registry.hex_digest(src[k]) for k in (*security.DIGESTS,'execution_digest','retest_digest','security_evidence_digest','policy_digest')):
            raise ValueError('Source mismatch')
        result=[scan_file(file) for file in files]
        out['files']=[x[0] for x in result];out['findings']=[y for x in result for y in x[1]]
        out['source']=dict(candidate_digest=digest,threat_model_digest=model['evidence_digest'],catalog_digest=model['catalog_digest'],
            security_evidence_digest=src['security_evidence_digest'],execution_digest=src['execution_digest'],retest_digest=src['retest_digest'])
        complete=any(x['status']=='SCANNED' for x in out['files']) and all(x['status'] in ('SCANNED','PASSIVE_NOT_SCANNED') for x in out['files'])
        out['scan_verdict']='NO_RULE_MATCHES' if complete and not out['findings'] else 'BLOCK'
        if model['state']=='THREAT_MODEL_READY' and out['scan_verdict']=='NO_RULE_MATCHES':out['state']='SAST_BASELINE_READY'
    except security.ERRORS:
        pass
    out['evidence_digest']=pp.digest(out)
    return out
def view(c,db,pid,jid):
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    try:
        source,_,proposal,_=security.runner.current(c,db,pid,jid)
        model=threat.view(c,db,pid,jid)
        if not model['source'] or any(model['source'][k]!=source[k] for k in security.DIGESTS):
            raise ValueError('Current source mismatch')
        return evaluate(pid,jid,model,proposal)
    except security.ERRORS:
        return evaluate(pid,jid,{}, {})
