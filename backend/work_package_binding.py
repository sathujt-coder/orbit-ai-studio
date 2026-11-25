"""Immutable, explicit work package selection. No execution or queue authority."""
import json
import product_requirements as pr
import project_planning as pp
import work_breakdown as wbs

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS studio_work_packages(
        project_id TEXT NOT NULL REFERENCES projects(id),
        adoption_version INTEGER NOT NULL, package_id TEXT NOT NULL,
        snapshot TEXT NOT NULL, digest TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,adoption_version,package_id),
        FOREIGN KEY(project_id,adoption_version) REFERENCES planning_adoptions(project_id,version))""")

def source(c,pid,package_id,w=None):
    w=w if w is not None else wbs.view(c,pid)
    a=w['adoption'];row=a['current']
    if a['status']!='adopted' or a['stale'] or not row:
        raise ValueError('Current adopted planning bundle required')
    snap=row['snapshot'];bundle=snap['bundle']
    if pp.digest(snap)!=row['digest'] or pp.digest(bundle)!=row['bundle_digest']:
        raise ValueError('Adoption digest mismatch')
    prd=bundle['prd']
    pp.require_input(c,pid,prd['version'],prd['digest'])
    doc=bundle['wbs']['document']
    if pp.digest(doc)!=bundle['wbs']['digest']:
        raise ValueError('WBS digest mismatch')
    matches=[(d,p) for d in doc['deliverables'] for p in d['packages'] if p['id']==package_id]
    if len(matches)!=1:raise ValueError('Unique adopted work package required')
    d,p=matches[0]
    criteria=[x for x in d['acceptance'] if x['id'] in p['criteria']]
    if not criteria or {x['id'] for x in criteria}!=set(p['criteria']):
        raise ValueError('Missing acceptance traceability')
    return dict(schema='orbit.work-package-binding.v1',project_id=pid,
        adoption_version=row['version'],adoption_digest=row['digest'],bundle_digest=row['bundle_digest'],
        review_id=row['review_id'],evidence_digest=row['evidence_digest'],
        requirements_version=prd['version'],requirements_digest=prd['digest'],
        wbs_version=bundle['wbs']['version'],wbs_digest=bundle['wbs']['digest'],
        deliverable_id=d['id'],requirement=d['requirement'],outcome=d['outcome'],
        package=p,acceptance=criteria,execution_authorized=False)

def bind(c,pid,actor,body,stamp):
    pp.check_role(c,pid,actor,'write')
    pr.fields(body,('adoption_version','bundle_digest','package_id','confirmation'))
    if body['confirmation']!='BIND ADOPTED WORK PACKAGE':raise ValueError('Explicit work package binding required')
    if not isinstance(body['package_id'],str) or not 1<=len(body['package_id'])<=200:raise ValueError('Invalid package ID')
    snap=source(c,pid,body['package_id'])
    if type(body['adoption_version']) is not int or body['adoption_version']!=snap['adoption_version'] or body['bundle_digest']!=snap['bundle_digest']:
        raise ValueError('Current adoption version and digest required')
    if c.execute('SELECT 1 FROM studio_work_packages WHERE project_id=? AND adoption_version=? AND package_id=?',(pid,snap['adoption_version'],body['package_id'])).fetchone():
        raise ValueError('Work package already bound')
    c.execute('INSERT INTO studio_work_packages VALUES(?,?,?,?,?,?,?)',(pid,snap['adoption_version'],body['package_id'],pr.canonical(snap),pp.digest(snap),actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'studio_work_package_bind','allowed'))
    return dict(snapshot=snap,digest=pp.digest(snap),execution_authorized=False)

def view(c,pid,w=None):
    rows=c.execute('SELECT * FROM studio_work_packages WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,)).fetchall()
    result=[]
    for row in rows:
        item=dict(package_id=row['package_id'],adoption_version=row['adoption_version'],digest=row['digest'],actor=row['actor'],created_at=row['created_at'],state='STALE',execution_authorized=False)
        try:
            snap=json.loads(row['snapshot'])
            if pp.digest(snap)!=row['digest'] or snap['project_id']!=pid or snap['adoption_version']!=row['adoption_version'] or snap['package']['id']!=row['package_id']:
                item['state']='INVALID'
            elif snap==source(c,pid,row['package_id'],w):item['state']='BOUND'
        except (ValueError,TypeError,KeyError,AttributeError):pass
        result.append(item)
    available=[]
    if w and w['adoption']['status']=='adopted' and not w['adoption']['stale']:
        row=w['adoption']['current']
        for d in row['snapshot']['bundle']['wbs']['document']['deliverables']:
            for p in d['packages']:
                available.append(dict(id=p['id'],kind=p['kind'],deliverable_id=d['id']))
    return dict(bindings=result,available=available,execution_authorized=False)
