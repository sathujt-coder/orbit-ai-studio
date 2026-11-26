"""Additive human-reviewed dependency overlay; never modifies adopted planning.

Original dual AI cross-review applies only to the original bundle. The overlay
has a separate explicit human approval and deterministic schedule/graph checks.
It is advisory until the downstream execution integration is accepted.
"""
import copy
import json
import product_requirements as pr
import project_planning as pp
import work_breakdown as wbs
import resource_estimates as re
import sprint_schedule as ss

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS wbs_dependency_extensions(
        project_id TEXT NOT NULL, adoption_version INTEGER NOT NULL,
        version INTEGER NOT NULL, snapshot TEXT NOT NULL, digest TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,adoption_version,version),
        FOREIGN KEY(project_id,adoption_version) REFERENCES planning_adoptions(project_id,version))""")

def base(c,pid,w=None):
    w=w if w is not None else wbs.view(c,pid)
    a=w['adoption'];row=a['current']
    if a['status']!='adopted' or a['stale'] or not row:
        raise ValueError('Current reviewed adopted planning required')
    snap=row['snapshot'];bundle=snap['bundle']
    if pp.digest(snap)!=row['digest'] or pp.digest(bundle)!=row['bundle_digest']:
        raise ValueError('Adoption digest mismatch')
    if snap['review_id']!=row['review_id'] or snap['evidence_digest']!=row['evidence_digest']:
        raise ValueError('Review binding mismatch')
    pp.require_input(c,pid,bundle['prd']['version'],bundle['prd']['digest'])
    for name in ('wbs','estimates','schedule'):
        if pp.digest(bundle[name]['document'])!=bundle[name]['digest']:
            raise ValueError('Adopted revision digest mismatch')
    return row,bundle

def build(pid,row,bundle,edges):
    if not isinstance(edges,list) or not 1<=len(edges)<=128:
        raise ValueError('Expected 1–128 additive implementation edges')
    effective=copy.deepcopy(bundle['wbs'])
    packages=re.packages(effective)
    seen=set();normalized=[]
    for edge in edges:
        pr.fields(edge,('source','target','rationale'))
        a,b=edge['source'],edge['target']
        if not isinstance(a,str) or not isinstance(b,str) or a not in packages or b not in packages or a==b:
            raise ValueError('Unknown or self dependency')
        if packages[a]['kind']!='implement' or packages[b]['kind']!='implement':
            raise ValueError('Only implementation-to-implementation additions supported')
        if (a,b) in seen or a in packages[b]['depends_on']:
            raise ValueError('Duplicate or existing dependency')
        rationale=edge['rationale']
        if not isinstance(rationale,str) or not 20<=len(rationale.strip())<=1200:
            raise ValueError('Explicit dependency rationale required')
        seen.add((a,b))
        normalized.append(dict(source=a,target=b,rationale=rationale.strip()))
        packages[b]['depends_on'].append(a)
    for p in packages.values():p['depends_on'].sort()
    # Existing estimate validation and DAG analysis, then existing schedule checks.
    analysis=re.analyze(bundle['estimates']['document'],effective)
    if not analysis['ready'] or not analysis['dependency_graph']['timing_ready']:
        raise ValueError('Complete estimates and valid dependency graph required')
    schedule_input=dict(stale=False,current=effective,decomposition_ready=True,
        resource_estimates=dict(stale=False,current=bundle['estimates'],analysis=analysis))
    _,schedule=ss.analyze(bundle['schedule']['document'],schedule_input)
    if not schedule['ready']:raise ValueError('Extended dependencies conflict with adopted schedule')
    graph=analysis['dependency_graph']
    return dict(schema='orbit.wbs-dependency-extension.v1',project_id=pid,
        adoption_version=row['version'],adoption_digest=row['digest'],bundle_digest=row['bundle_digest'],
        review_id=row['review_id'],evidence_digest=row['evidence_digest'],
        wbs_digest=bundle['wbs']['digest'],estimate_digest=bundle['estimates']['digest'],
        schedule_digest=bundle['schedule']['digest'],base_graph_digest=pp.digest(bundle['dependency_graph']),
        edges=sorted(normalized,key=lambda x:(x['source'],x['target'])),
        effective_graph=graph,effective_graph_digest=pp.digest(graph),
        review_scope='original_bundle_only',extension_review='explicit_human_approval',
        execution_authorized=False,automatic_dispatch=False,production_release_authorized=False)

def latest(c,pid,v):
    return c.execute('SELECT * FROM wbs_dependency_extensions WHERE project_id=? AND adoption_version=? ORDER BY version DESC LIMIT 1',(pid,v)).fetchone()

def approve(c,pid,actor,body,stamp):
    pp.check_role(c,pid,actor,'approve')
    pr.fields(body,('adoption_version','adoption_digest','expected_version','edges','confirmation'))
    if body['confirmation']!='APPROVE WBS DEPENDENCY EXTENSION':raise ValueError('Explicit extension approval required')
    row,bundle=base(c,pid)
    if type(body['adoption_version']) is not int or body['adoption_version']!=row['version'] or body['adoption_digest']!=row['digest']:
        raise ValueError('Current adoption identity required')
    old=latest(c,pid,row['version']);v=old['version'] if old else 0
    if type(body['expected_version']) is not int or body['expected_version']!=v:
        raise ValueError('Stale extension version')
    snap=build(pid,row,bundle,body['edges'])
    digest=pp.digest(snap)
    if old:
        prior=json.loads(old['snapshot'])
        if pp.digest(prior)!=old['digest']:raise ValueError('Invalid prior extension')
        if not {(x['source'],x['target']) for x in prior['edges']}<={(x['source'],x['target']) for x in snap['edges']}:
            raise ValueError('Extension may not remove previously approved edges')
        if old['digest']==digest:raise ValueError('Duplicate extension')
    c.execute('INSERT INTO wbs_dependency_extensions VALUES(?,?,?,?,?,?,?)',
        (pid,row['version'],v+1,pr.canonical(snap),digest,actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'wbs_dependency_extension_approve','allowed'))
    return dict(version=v+1,digest=digest,snapshot=snap,execution_authorized=False)

def view(c,pid):
    out=dict(project_id=pid,state='NOT_RECORDED',current=None,execution_authorized=False,automatic_dispatch=False)
    row=c.execute('SELECT * FROM wbs_dependency_extensions WHERE project_id=? ORDER BY adoption_version DESC,version DESC LIMIT 1',(pid,)).fetchone()
    if not row:return out
    out['state']='STALE'
    out['current']={k:row[k] for k in ('adoption_version','version','digest','actor','created_at')}
    try:
        snap=json.loads(row['snapshot'])
        if pp.digest(snap)!=row['digest'] or snap['project_id']!=pid or snap['adoption_version']!=row['adoption_version']:
            out['state']='INVALID';return out
        current,bundle=base(c,pid)
        if current['version']==row['adoption_version'] and build(pid,current,bundle,snap['edges'])==snap:
            out['state']='APPROVED_ADVISORY'
            out['current']['snapshot']=snap
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError):pass
    return out
