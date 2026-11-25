"""P6.2f: human estimates bound to immutable saved WBS; no inference."""
import json
import product_requirements as pr
import project_planning as pp
import dependency_graph

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS wbs_resource_estimates(
        project_id TEXT NOT NULL, version INTEGER NOT NULL,
        wbs_version INTEGER NOT NULL, wbs_digest TEXT NOT NULL,
        document TEXT NOT NULL, digest TEXT NOT NULL, author TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(project_id,version),
        FOREIGN KEY(project_id,wbs_version) REFERENCES work_breakdowns(project_id,version))""")

def latest(c,pid):
    return c.execute('SELECT * FROM wbs_resource_estimates WHERE project_id=? ORDER BY version DESC LIMIT 1',(pid,)).fetchone()

def packages(wbs):
    return {p['id']:p for d in wbs['document']['deliverables'] for p in d['packages']}

def validate(document,wbs):
    pr.fields(document,('packages',))
    entries=document['packages']; expected=packages(wbs)
    if not isinstance(entries,list) or len(entries)!=len(expected):
        raise ValueError('Exact package estimate coverage required')
    by_id={}
    for item in entries:
        pr.fields(item,('id','effort_minutes','role'))
        tid=item['id']; effort=item['effort_minutes']; role=item['role']
        if not isinstance(tid,str) or tid not in expected or tid in by_id:
            raise ValueError('Invalid or duplicate estimate package')
        if effort is not None and (type(effort) is not int or not 1<=effort<=60000):
            raise ValueError('Effort must be null or integer 1–60000')
        if role is not None and (not isinstance(role,str) or not role.strip() or len(role)>80 or any(ord(ch)<32 for ch in role)):
            raise ValueError('Role must be null or a nonempty label up to 80 characters')
        by_id[tid]=dict(id=tid,effort_minutes=effort,role=role.strip() if role is not None else None)
    return dict(packages=[by_id[tid] for tid in sorted(expected)])

def draft(wbs):
    return dict(packages=[dict(id=tid,effort_minutes=None,role=None) for tid in sorted(packages(wbs))])

def analyze(document,wbs):
    doc=validate(document,wbs); ps=packages(wbs); totals={}
    missing_effort=[]; missing_role=[]
    for item in doc['packages']:
        tid=item['id']; minutes=item['effort_minutes']; role=item['role']
        if minutes is None:missing_effort.append(tid)
        if role is None:missing_role.append(tid)
        if minutes is not None and role is not None:totals[role]=totals.get(role,0)+minutes
    graph=dependency_graph.analyze([dict(id=i['id'],depends_on=ps[i['id']]['depends_on'],
        effort_minutes=i['effort_minutes']) for i in doc['packages']])
    return dict(ready=not missing_effort and not missing_role,missing_effort=missing_effort,
        missing_role=missing_role,known_effort_minutes=sum(i['effort_minutes'] or 0 for i in doc['packages']),
        total_effort_minutes=None if missing_effort else sum(i['effort_minutes'] for i in doc['packages']),
        known_effort_by_role=totals,dependency_graph=graph,schedule_committed=False)

def view(c,pid,wbs,stale):
    row=latest(c,pid); current=None; analysis=None; invalid=False
    if row:
        invalid=not wbs or stale or (row['wbs_version'],row['wbs_digest'])!=(wbs['version'],wbs['digest'])
        current=dict(row)
        try:
            current['document']=json.loads(row['document'])
            if pp.digest(current['document'])!=row['digest']:invalid=True
            if not invalid:analysis=analyze(current['document'],wbs)
        except (ValueError,TypeError,KeyError):invalid=True
    return dict(current=current,stale=bool(invalid),analysis=analysis,
        draft=draft(wbs) if wbs and not stale else None,
        history=[dict(r) for r in c.execute("""SELECT version,wbs_version,wbs_digest,digest,author,created_at
            FROM wbs_resource_estimates WHERE project_id=? ORDER BY version DESC LIMIT 50""",(pid,))])

def save(c,pid,actor,body,stamp,wbs_view):
    pp.check_role(c,pid,actor,'write')
    pr.fields(body,('expected_version','wbs_version','wbs_digest','document','confirmation'))
    if body['confirmation']!='SAVE RESOURCE ESTIMATES':raise ValueError('Explicit SAVE RESOURCE ESTIMATES required')
    wbs=wbs_view['current']
    if not wbs or wbs_view['stale'] or type(body['wbs_version']) is not int or (body['wbs_version'],body['wbs_digest'])!=(wbs['version'],wbs['digest']):
        raise ValueError('Current WBS version and digest required')
    row=latest(c,pid); expected=body['expected_version']
    if type(expected) is not int or expected!=(row['version'] if row else 0):raise ValueError('Stale estimate version')
    doc=validate(body['document'],wbs)
    c.execute("""INSERT INTO wbs_resource_estimates(project_id,version,wbs_version,wbs_digest,document,digest,author,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",(pid,expected+1,wbs['version'],wbs['digest'],pr.canonical(doc),pp.digest(doc),actor,stamp))
    return view(c,pid,wbs,False)
