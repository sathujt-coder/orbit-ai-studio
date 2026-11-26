"""P6.3a: versioned engineering evidence, never execution authorization."""
import json
import product_requirements as pr
import project_planning as pp
import work_breakdown as wbs
import work_package_binding as wb
import studio_coding as sc
import dependency_graph as dg

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_contracts(
        project_id TEXT NOT NULL, adoption_version INTEGER NOT NULL,
        package_id TEXT NOT NULL, version INTEGER NOT NULL,
        snapshot TEXT NOT NULL, digest TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,adoption_version,package_id,version),
        FOREIGN KEY(project_id,adoption_version,package_id)
        REFERENCES studio_work_packages(project_id,adoption_version,package_id))""")

def source(c,pid,package_id,w=None):
    w=w if w is not None else wbs.view(c,pid)
    snap=wb.source(c,pid,package_id,w)
    version=snap['adoption_version']
    row=c.execute('SELECT snapshot,digest FROM studio_work_packages WHERE project_id=? AND adoption_version=? AND package_id=?',(pid,version,package_id)).fetchone()
    if not row or row['digest']!=pp.digest(snap) or json.loads(row['snapshot'])!=snap:
        raise ValueError('Current exact work package binding required')
    bundle=w['adoption']['current']['snapshot']['bundle']
    graph=bundle['dependency_graph']
    # Bind the full adopted graph, independently check topology against WBS.
    nodes=[dict(id=p['id'],depends_on=p['depends_on'],effort_minutes=None) for d in bundle['wbs']['document']['deliverables'] for p in d['packages']]
    topology=dg.analyze(nodes)
    for key in ('node_count','edge_count','execution_order','layers','roots','sinks','edges'):
        if graph[key]!=topology[key]:raise ValueError('Adopted dependency graph mismatch')
    package=snap['package']
    reasons=[]
    if package['kind']!='implement':reasons.append('IMPLEMENTATION_KIND_REQUIRED')
    if package['depends_on']:reasons.append('PREREQUISITE_EVIDENCE_REQUIRED')
    spec_digest=None
    if package['kind']=='implement':
        try:spec_digest=pp.digest(sc.spec_for(snap))
        except ValueError:reasons.append('SPECIFICATION_LIMIT')
    return dict(schema='orbit.engineering-execution-contract.v1',project_id=pid,adoption_version=version,
        package_id=package_id,binding_digest=row['digest'],adoption_digest=snap['adoption_digest'],
        bundle_digest=snap['bundle_digest'],requirements_digest=snap['requirements_digest'],
        wbs_digest=snap['wbs_digest'],graph_digest=pp.digest(graph),topology_digest=pp.digest(topology),
        predecessors=sorted(package['depends_on']),kind=package['kind'],spec_digest=spec_digest,
        structural_eligibility='BLOCK' if reasons else 'ROOT_IMPLEMENTATION',
        reasons=reasons,execution_authorized=False,automatic_dispatch=False,production_release_authorized=False)

def latest(c,pid,version,package_id):
    return c.execute('SELECT * FROM engineering_contracts WHERE project_id=? AND adoption_version=? AND package_id=? ORDER BY version DESC LIMIT 1',(pid,version,package_id)).fetchone()

def confirm(c,pid,actor,body,stamp):
    pp.check_role(c,pid,actor,'approve')
    pr.fields(body,('adoption_version','package_id','expected_version','source_digest','confirmation'))
    if body['confirmation']!='CONFIRM ENGINEERING CONTRACT':raise ValueError('Explicit engineering contract confirmation required')
    if type(body['adoption_version']) is not int or type(body['expected_version']) is not int or not isinstance(body['package_id'],str) or not 1<=len(body['package_id'])<=200:
        raise ValueError('Invalid engineering contract identity')
    src=source(c,pid,body['package_id'])
    digest=pp.digest(src)
    if src['adoption_version']!=body['adoption_version'] or digest!=body['source_digest']:
        raise ValueError('Current engineering source required')
    if src['structural_eligibility']!='ROOT_IMPLEMENTATION':raise ValueError('Engineering structural eligibility blocked')
    row=latest(c,pid,src['adoption_version'],src['package_id'])
    version=row['version'] if row else 0
    if version!=body['expected_version']:raise ValueError('Stale engineering contract version')
    if row and row['digest']==digest:raise ValueError('Engineering contract already confirmed')
    c.execute('INSERT INTO engineering_contracts VALUES(?,?,?,?,?,?,?,?)',
        (pid,src['adoption_version'],src['package_id'],version+1,pr.canonical(src),digest,actor,stamp))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",(actor,pid,'engineering_contract_confirm','allowed'))
    return dict(version=version+1,digest=digest,execution_authorized=False,automatic_dispatch=False,production_release_authorized=False)

def view(c,pid,w=None):
    w=w if w is not None else wbs.view(c,pid)
    out=dict(project_id=pid,contracts=[],execution_authorized=False,automatic_dispatch=False,production_release_authorized=False)
    # Include historical bound packages, not only recent queue jobs.
    rows=c.execute('SELECT adoption_version,package_id FROM studio_work_packages WHERE project_id=? ORDER BY rowid DESC LIMIT 100',(pid,)).fetchall()
    for bound in rows:
        v,p=bound['adoption_version'],bound['package_id']
        row=latest(c,pid,v,p)
        item=dict(adoption_version=v,package_id=p,state='STALE',source=None,source_digest=None,latest_version=row['version'] if row else 0,receipt=None)
        try:
            if row:
                item['receipt']={k:row[k] for k in ('version','digest','actor','created_at')}
                if pp.digest(json.loads(row['snapshot']))!=row['digest']:
                    item['state']='INVALID';out['contracts'].append(item);continue
            src=source(c,pid,p,w)
            if src['adoption_version']==v:
                digest=pp.digest(src)
                item.update(source=src,source_digest=digest,state='BLOCK' if src['reasons'] else 'AWAITING_CONFIRMATION')
                if row:item['state']='CONFIRMED' if row['digest']==digest and json.loads(row['snapshot'])==src and not src['reasons'] else 'STALE'
        except (ValueError,KeyError,TypeError,AttributeError,PermissionError):pass
        out['contracts'].append(item)
    return out
