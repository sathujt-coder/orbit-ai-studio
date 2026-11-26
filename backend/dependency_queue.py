"""P6.3c: explicit dependency-aware submission with pinned prerequisite receipts.

Implementation prerequisites are recursively validated through their pinned
queue sources and current completion receipts. Verification packages stay blocked.
"""
import json
from contextvars import ContextVar
import product_requirements as pr
import project_planning as pp
import engineering_contract as ec
import dependency_completion as dc
import work_package_binding as wb
import studio_coding as sc

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_queue_sources(
        job_id TEXT PRIMARY KEY REFERENCES studio_coding_bindings(job_id),
        project_id TEXT NOT NULL REFERENCES projects(id),
        snapshot TEXT NOT NULL,digest TEXT NOT NULL)""")

# Scope memoization to ONE synchronous validation, never across requests/transactions.
_validation=ContextVar('dependency_validation',default=None)

def source(c,pid,v,p,digest):
    context=_validation.get()
    token=None
    if context is None:
        context=dict(active=set(),cache={})
        token=_validation.set(context)
    key=(c,pid,v,p,digest)
    try:
        if key in context['active']:raise ValueError('Cyclic completion evidence')
        if key in context['cache']:return context['cache'][key]
        context['active'].add(key)
        try:
            result=_source(c,pid,v,p,digest)
            context['cache'][key]=result
            return result
        finally:context['active'].remove(key)
    finally:
        if token is not None:_validation.reset(token)

def _source(c,pid,v,p,digest):
    src=ec.source(c,pid,p)
    if src['adoption_version']!=v or src['binding_digest']!=digest:
        raise ValueError('Current package source required')
    if src['kind']!='implement' or not src['predecessors'] or src['reasons']!=['PREREQUISITE_EVIDENCE_REQUIRED']:
        raise ValueError('Dependent implementation required')
    target_contract=ec.require_confirmed(c,pid,src)
    evidence=[]
    for dep in src['predecessors']:
        parent=ec.source(c,pid,dep)
        if parent['adoption_version']!=v or parent['graph_digest']!=src['graph_digest'] or not ec.confirmable(parent):
            raise ValueError('Current implementation prerequisite required')
        row=dc.latest(c,pid,v,dep)
        if not row:raise ValueError('Missing prerequisite completion receipt')
        snap=json.loads(row['snapshot'])
        if pp.digest(snap)!=row['digest']:raise ValueError('Invalid prerequisite receipt')
        current=dc.source(c,pid,row['job_id'])
        if current!=snap['source'] or current['project_id']!=pid or current['job_id']!=row['job_id'] or current['package_id']!=dep or current['adoption_version']!=v or current['graph_digest']!=src['graph_digest']:
            raise ValueError('Stale prerequisite receipt')
        decision=snap['decision']
        checked=dc.selection(c,pid,current,row['actor'],decision['selected'],decision['rationale'])
        if {k:x for k,x in checked.items() if k!='decided_at'}!={k:x for k,x in decision.items() if k!='decided_at'}:
            raise ValueError('Invalid prerequisite selection')
        evidence.append(dict(package_id=dep,job_id=row['job_id'],version=row['version'],digest=row['digest'],selected_digest=decision['selected_digest']))
    return dict(schema='orbit.dependency-queue-source.v1',project_id=pid,adoption_version=v,package_id=p,
        binding_digest=digest,contract_source_digest=pp.digest(src),contract_version=target_contract['version'],graph_digest=src['graph_digest'],
        spec_digest=src['spec_digest'],prerequisites=evidence,production_release_authorized=False,**({k:src[k] for k in ('extension_version','extension_digest')} if 'extension_version' in src else {}))

def request(c,pid,actor,body):
    pp.check_role(c,pid,actor,'write')
    pr.fields(body,('adoption_version','package_id','binding_digest','source_digest','confirmation'))
    if body['confirmation']!='QUEUE DEPENDENT WORK PACKAGE':raise ValueError('Explicit dependent submission required')
    if type(body['adoption_version']) is not int or not isinstance(body['package_id'],str) or not isinstance(body['binding_digest'],str):
        raise ValueError('Invalid dependency source identity')
    src=source(c,pid,body['adoption_version'],body['package_id'],body['binding_digest'])
    if pp.digest(src)!=body['source_digest']:raise ValueError('Current prerequisite source digest required')
    if c.execute('SELECT 1 FROM studio_coding_bindings WHERE project_id=? AND adoption_version=? AND package_id=?',(pid,body['adoption_version'],body['package_id'])).fetchone():
        raise ValueError('Work package already submitted')
    snap=wb.source(c,pid,body['package_id'])
    spec=sc.spec_for(snap)
    if pp.digest(spec)!=src['spec_digest']:raise ValueError('Specification mismatch')
    return src,spec

def record(c,pid,actor,body,jid,qid,spec,stamp):
    src,expected=request(c,pid,actor,body)
    if expected!=spec:raise ValueError('Changed specification')
    c.execute('INSERT INTO studio_coding_bindings VALUES(?,?,?,?,?,?,?,?,?)',(jid,pid,qid,src['adoption_version'],src['package_id'],src['binding_digest'],src['spec_digest'],actor,stamp))
    c.execute('INSERT INTO engineering_queue_sources VALUES(?,?,?,?)',(jid,pid,pr.canonical(src),pp.digest(src)))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'engineering_dependency_queue','allowed'))

def checked_package(c,pid,row):
    stored=c.execute('SELECT * FROM engineering_queue_sources WHERE job_id=? AND project_id=?',(row['job_id'],pid)).fetchone()
    if not stored:raise ValueError('Missing pinned prerequisite evidence')
    snap=json.loads(stored['snapshot'])
    current=source(c,pid,row['adoption_version'],row['package_id'],row['binding_digest'])
    if pp.digest(snap)!=stored['digest'] or snap!=current or row['spec_digest']!=current['spec_digest']:
        raise ValueError('Stale pinned prerequisite evidence')
    return wb.source(c,pid,row['package_id'])

def view(c,pid):
    out=dict(project_id=pid,items=[],automatic_dispatch=False,production_release_authorized=False)
    for b in c.execute('SELECT adoption_version,package_id,digest FROM studio_work_packages WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,)).fetchall():
        item=dict(adoption_version=b['adoption_version'],package_id=b['package_id'],state='BLOCK',source=None,source_digest=None)
        try:
            src=source(c,pid,b['adoption_version'],b['package_id'],b['digest'])
            item.update(state='READY_FOR_EXPLICIT_SUBMISSION',source=src,source_digest=pp.digest(src))
            if c.execute('SELECT 1 FROM studio_coding_bindings WHERE project_id=? AND adoption_version=? AND package_id=?',(pid,b['adoption_version'],b['package_id'])).fetchone():item['state']='SUBMITTED'
        except (ValueError,KeyError,TypeError,AttributeError,PermissionError):pass
        out['items'].append(item)
    return out
