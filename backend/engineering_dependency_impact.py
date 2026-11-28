"""P6.4d.2: deterministic, conservative file dependency impact evidence.

Static Python imports only, never execute candidate code. Compare both sides
of a change to retain deleted-module edges. Unknown/dynamic/non-Python
dependencies widen to all files. No test selection or exemption is authorized.
"""
import ast
import sqlite3
import sys
from collections import defaultdict,deque
from pathlib import PurePosixPath

import engineering_git_changes as changes
import engineering_sandbox as sb
import project_planning as pp
import verification_factory as vf

FLAGS=changes.FLAGS
PAIRS=(('baseline_to_A','baseline','A'),('baseline_to_B','baseline','B'),('A_to_B','A','B'))
MAX_AST_NODES=100000
STDLIB=frozenset(getattr(sys,'stdlib_module_names',()))

def module_name(path):
    parts=PurePosixPath(path).parts
    if not parts or not path.endswith('.py'):return None
    tail=parts[-1][:-3]
    names=parts[:-1]+(() if tail=='__init__' else (tail,))
    if not names or not all(x.isidentifier() for x in names):return None
    return '.'.join(names)

def graph(proposal):
    files=changes.file_map(proposal)
    modules=defaultdict(list);issues=set();edges=set()
    def issue(path,code):issues.add((path,code))
    for path in files:
        name=module_name(path)
        if name is None:issue(path,'UNSUPPORTED_FILE_OR_MODULE')
        else:modules[name].append(path)
    for name,paths in modules.items():
        if len(paths)>1:
            for path in paths:issue(path,'AMBIGUOUS_MODULE')
    def resolve(path,name,required=True):
        if not name:
            if required:issue(path,'UNRESOLVED_IMPORT')
            return False
        parts=name.split('.');found=False
        for i in range(1,len(parts)+1):
            prefix='.'.join(parts[:i]);targets=modules.get(prefix,[])
            if len(targets)>1:issue(path,'AMBIGUOUS_IMPORT')
            for target in targets:
                if target!=path:edges.add((path,target))
            if i==len(parts) and targets:found=True
        # Namespace package prefixes can be represented by child modules.
        namespace=any(m.startswith(name+'.') for m in modules)
        if required and not found and not namespace:
            if parts[0] in modules or any(m.startswith(parts[0]+'.') for m in modules):
                issue(path,'UNRESOLVED_LOCAL_IMPORT')
            elif parts[0] not in STDLIB:
                issue(path,'UNRESOLVED_EXTERNAL_IMPORT')
        if parts[0] in ('importlib','builtins','runpy','pkgutil'):
            issue(path,'DYNAMIC_IMPORT_POSSIBLE')
        return found or namespace
    for f in proposal['files']:
        path=f['path'];name=module_name(path)
        if name is None:continue
        package=name if path.endswith('/__init__.py') else name.rpartition('.')[0]
        # Importing package initialization can affect any submodule.
        if package:resolve(path,package,False)
        try:tree=ast.parse(f['content'],filename=path)
        except (SyntaxError,ValueError,RecursionError):
            issue(path,'PYTHON_PARSE_ERROR');continue
        for index,node in enumerate(ast.walk(tree)):
            if index>=MAX_AST_NODES:
                issue(path,'AST_LIMIT');break
            if isinstance(node,ast.Import):
                for alias in node.names:resolve(path,alias.name)
            elif isinstance(node,ast.ImportFrom):
                base=node.module or ''
                if node.level:
                    parts=package.split('.') if package else []
                    if node.level>len(parts):
                        issue(path,'UNRESOLVED_RELATIVE_IMPORT');continue
                    prefix='.'.join(parts[:len(parts)-node.level+1])
                    base=prefix+('.'+base if base else '')
                local=resolve(path,base)
                for alias in node.names:
                    if alias.name=='*':issue(path,'STAR_IMPORT')
                    elif local:resolve(path,base+'.'+alias.name,False)
            elif isinstance(node,ast.Call):
                fn=node.func
                if (isinstance(fn,ast.Name) and fn.id in ('__import__','eval','exec','compile','getattr','open')
                    or isinstance(fn,ast.Attribute) and fn.attr in ('import_module','__import__','exec_module','load_module','read_text','read_bytes','open')):
                    issue(path,'DYNAMIC_DEPENDENCY_POSSIBLE')
            elif isinstance(node,ast.Attribute) and node.attr in ('path','meta_path','path_hooks') and isinstance(node.value,ast.Name) and node.value.id=='sys':
                issue(path,'DYNAMIC_DEPENDENCY_POSSIBLE')
    return dict(files=[dict(path=p,**files[p]) for p in sorted(files)],
                edges=[dict(importer=a,dependency=b) for a,b in sorted(edges)],
                uncertainties=[dict(path=p,code=k) for p,k in sorted(issues)])

def index(g):return {f['path']:{k:f[k] for k in ('blob','sha256')} for f in g['files']}

def impact(before,after,comparison):
    old=index(before);new=index(after)
    expected=changes.expected_changes(old,new)
    if comparison['changes']!=expected:raise ValueError('Change manifest mismatch')
    counts={s:sum(x['status']==s for x in expected) for s in ('ADDED','MODIFIED','DELETED')}
    if (comparison['counts']!=counts or comparison['unchanged_count']!=sum(old.get(p)==new[p] for p in new if p in old)):
        raise ValueError('Change summary mismatch')
    direct={x['path'] for x in expected}
    reverse=defaultdict(set)
    for edge in before['edges']+after['edges']:
        reverse[edge['dependency']].add(edge['importer'])
    seen=set(direct);queue=deque(sorted(direct))
    while queue:
        for path in sorted(reverse[queue.popleft()]):
            if path not in seen:seen.add(path);queue.append(path)
    uncertain=bool(before['uncertainties'] or after['uncertainties'])
    # Even no detected file changes is not authority to skip existing tests.
    fallback=bool(direct and uncertain)
    impacted=(set(old)|set(new)) if fallback else seen
    return dict(from_commit=comparison['from_commit'],to_commit=comparison['to_commit'],
                direct_paths=sorted(direct),transitive_paths=sorted(seen-direct),
                impacted_paths=sorted(impacted),current_impacted_paths=sorted(impacted & set(new)),
                removed_impacted_paths=sorted(impacted-set(new)),
                analysis_mode='CONSERVATIVE_ALL_FILES' if fallback else 'STATIC_IMPORT_REACHABILITY',
                uncertainties_present=uncertain,full_regression_required=True)

def derive(evidence,proposals):
    if evidence['state']!='GIT_CHANGE_EVIDENCE_READY' or set(proposals)!={'A','B'}:
        raise ValueError('Current Git evidence required')
    src=evidence['source']
    if evidence['evidence_digest']!=pp.digest({k:v for k,v in evidence.items() if k!='evidence_digest'}):
        raise ValueError('Git evidence digest mismatch')
    if any(evidence.get(k) is not False for k in FLAGS):raise ValueError('Unexpected authority')
    graphs={'baseline':graph(dict(files=[]))}
    for lane in ('A','B'):
        meta,_=sb.git_objects(proposals[lane],src['base_commit'],src['job_id'],lane)
        if meta!=src['git'][lane]:raise ValueError('Candidate graph source mismatch')
        graphs[lane]=graph(proposals[lane])
    commits={'baseline':src['base_commit'],**{k:src['git'][k]['commit'] for k in ('A','B')}}
    results={}
    for name,left,right in PAIRS:
        comparison=evidence['comparisons'][name]
        if (comparison['from_commit'],comparison['to_commit'])!=(commits[left],commits[right]):
            raise ValueError('Comparison commit mismatch')
        results[name]=impact(graphs[left],graphs[right],comparison)
    return graphs,results

def view(c,db,pid,jid):
    out=dict(schema='orbit.dependency-impact-evidence.v1',project_id=pid,job_id=jid,state='BLOCK',
             source=None,graphs={},comparisons={},selected_comparison=None,
             scope='development_evidence_only',analysis_scope='candidate_file_static_imports',
             full_regression_required=True,selective_execution_authorized=False,**FLAGS)
    try:
        evidence=changes.view(c,db,pid,jid)
        if evidence['state']!='GIT_CHANGE_EVIDENCE_READY':raise ValueError('Current change evidence required')
        context,job,_=sb.current(c,db,pid,jid)
        src=evidence['source']
        if (src['project_id']!=pid or src['job_id']!=jid or src['selection_digest']!=context['selection_digest']
            or src['selected']!=context['selected'] or src['sandbox_source_digest']!=pp.digest(context)):
            raise ValueError('Current source changed')
        graphs,comparisons=derive(evidence,vf.safe_job(job))
        out.update(state='DEPENDENCY_IMPACT_READY',source=dict(git_change_evidence_digest=evidence['evidence_digest'],
                   git_source=src),graphs=graphs,comparisons=comparisons,
                   selected_comparison=evidence['selected_comparison'])
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError,sqlite3.Error,OSError,UnicodeError,RecursionError):
        pass
    out['evidence_digest']=pp.digest(out)
    return out
