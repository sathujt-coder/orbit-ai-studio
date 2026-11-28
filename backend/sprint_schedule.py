"""P6.2g: explicit sprint capacity and milestone drafts, never dispatch work."""
import json
from datetime import date
import product_requirements as pr
import project_planning as pp
import resource_estimates as re

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS wbs_schedules(
        project_id TEXT NOT NULL, version INTEGER NOT NULL,
        wbs_version INTEGER NOT NULL, wbs_digest TEXT NOT NULL,
        estimate_version INTEGER NOT NULL, estimate_digest TEXT NOT NULL,
        document TEXT NOT NULL, digest TEXT NOT NULL, author TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(project_id,version),
        FOREIGN KEY(project_id,wbs_version) REFERENCES work_breakdowns(project_id,version),
        FOREIGN KEY(project_id,estimate_version) REFERENCES wbs_resource_estimates(project_id,version))""")

def latest(c,pid):
    return c.execute('SELECT * FROM wbs_schedules WHERE project_id=? ORDER BY version DESC LIMIT 1',(pid,)).fetchone()

def source(w):
    est=w['resource_estimates']
    if w['stale'] or not w['current'] or est['stale'] or not est['analysis'] or not est['analysis']['ready']:
        return None
    return dict(wbs_version=w['current']['version'],wbs_digest=w['current']['digest'],
        estimate_version=est['current']['version'],estimate_digest=est['current']['digest'])

def draft(w):
    return dict(sprints=[],assignments=[dict(id=x['id'],sprint=None)
        for x in w['resource_estimates']['current']['document']['packages']],milestones=[])

def label(value):
    if not isinstance(value,str) or not value.strip() or len(value)>80 or any(ord(ch)<32 for ch in value):
        raise ValueError('Invalid schedule label')
    return value.strip()

def day(value):
    if not isinstance(value,str):raise ValueError('Invalid ISO date')
    result=date.fromisoformat(value)
    if result.isoformat()!=value:raise ValueError('Use YYYY-MM-DD')
    return result

def analyze(document,w):
    if source(w) is None:raise ValueError('Current complete resource estimates required')
    pr.fields(document,('sprints','assignments','milestones'))
    estimates={x['id']:x for x in w['resource_estimates']['current']['document']['packages']}
    roles={x['role'] for x in estimates.values()}
    packages=re.packages(w['current'])
    raw=document['sprints']
    if not isinstance(raw,list) or len(raw)>64:raise ValueError('At most 64 sprints')
    sprints=[];ids=set();previous=None
    for item in raw:
        pr.fields(item,('id','start','end','capacity'))
        sid=label(item['id']);start=day(item['start']);end=day(item['end'])
        if sid in ids or start>end or (previous is not None and start<=previous):
            raise ValueError('Sprints must be unique, chronological and non-overlapping')
        ids.add(sid);previous=end
        cap=item['capacity']
        if not isinstance(cap,dict) or set(cap)!=roles or any(type(v) is not int or not 0<=v<=10000000 for v in cap.values()):
            raise ValueError('Explicit nonnegative capacity minutes for every estimated role required')
        sprints.append(dict(id=sid,start=start.isoformat(),end=end.isoformat(),capacity=cap))
    order={s['id']:i for i,s in enumerate(sprints)}
    raw=document['assignments']
    if not isinstance(raw,list) or len(raw)!=len(packages):raise ValueError('Exact package assignment coverage required')
    assigned={}
    for item in raw:
        pr.fields(item,('id','sprint'))
        tid=item['id'];sid=item['sprint']
        if not isinstance(tid,str) or tid not in packages or tid in assigned or (sid is not None and (not isinstance(sid,str) or sid not in ids)):
            raise ValueError('Invalid package assignment')
        assigned[tid]=sid
    issues=[];loads={s['id']:{role:0 for role in sorted(roles)} for s in sprints}
    for tid,sid in sorted(assigned.items()):
        if sid is None:
            issues.append(dict(code='unassigned',package=tid));continue
        est=estimates[tid];loads[sid][est['role']]+=est['effort_minutes']
        for dep in packages[tid]['depends_on']:
            before=assigned[dep]
            if before is None or order[before]>order[sid]:
                issues.append(dict(code='dependency_order',package=tid,predecessor=dep))
    for s in sprints:
        for role,minutes in loads[s['id']].items():
            if minutes>s['capacity'][role]:
                issues.append(dict(code='capacity_exceeded',sprint=s['id'],role=role,excess_minutes=minutes-s['capacity'][role]))
    raw=document['milestones']
    if not isinstance(raw,list) or len(raw)>64:raise ValueError('At most 64 milestones')
    milestones=[];seen=set();covered=set()
    for item in raw:
        pr.fields(item,('id','title','sprint','packages'))
        mid=label(item['id']);title=label(item['title']);sid=item['sprint'];refs=item['packages']
        if mid in seen or not isinstance(sid,str) or sid not in ids or not isinstance(refs,list) or not refs or any(not isinstance(t,str) or t not in packages for t in refs) or len(set(refs))!=len(refs):
            raise ValueError('Invalid milestone')
        seen.add(mid);covered.update(refs)
        for tid in sorted(refs):
            if assigned[tid] is None or order[assigned[tid]]>order[sid]:
                issues.append(dict(code='milestone_dependency',milestone=mid,package=tid))
        milestones.append(dict(id=mid,title=title,sprint=sid,packages=sorted(refs)))
    for tid in sorted(set(packages)-covered):issues.append(dict(code='milestone_uncovered',package=tid))
    doc=dict(sprints=sprints,assignments=[dict(id=tid,sprint=assigned[tid]) for tid in sorted(assigned)],milestones=milestones)
    if len(pr.canonical(doc).encode())>48000:raise ValueError('Schedule exceeds 48 KB')
    return doc,dict(ready=not issues,issues=issues,loads=loads,
        detail_ready=w['decomposition_ready'],schedule_committed=False,execution_authorized=False,
        assumptions='aggregate_role_capacity_only_same_sprint_dependencies_require_internal_order')

def view(c,pid,w):
    src=source(w);row=latest(c,pid);current=None;analysis=None;stale=False
    if row:
        current=dict(row);stale=src is None or any(row[k]!=v for k,v in src.items())
        try:
            current['document']=json.loads(row['document'])
            if pp.digest(current['document'])!=row['digest']:stale=True
            if not stale:_,analysis=analyze(current['document'],w)
        except (ValueError,KeyError,TypeError):stale=True
    return dict(current=current,source=src,stale=stale,analysis=analysis,
        draft=draft(w) if src else None,
        history=[dict(x) for x in c.execute("""SELECT version,wbs_version,wbs_digest,estimate_version,estimate_digest,digest,author,created_at
            FROM wbs_schedules WHERE project_id=? ORDER BY version DESC LIMIT 50""",(pid,))])

def save(c,pid,actor,body,stamp,w):
    pp.check_role(c,pid,actor,'write')
    pr.fields(body,('expected_version','wbs_version','wbs_digest','estimate_version','estimate_digest','document','confirmation'))
    src=source(w)
    if body['confirmation']!='SAVE SPRINT SCHEDULE' or src is None or any(body[k]!=v for k,v in src.items()) or any(type(body[k]) is not int for k in ('wbs_version','estimate_version')):
        raise ValueError('Explicit save and current WBS/estimate binding required')
    row=latest(c,pid);v=body['expected_version']
    if type(v) is not int or v!=(row['version'] if row else 0):raise ValueError('Stale schedule version')
    doc,_=analyze(body['document'],w)
    c.execute("""INSERT INTO wbs_schedules(project_id,version,wbs_version,wbs_digest,estimate_version,estimate_digest,document,digest,author,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",(pid,v+1,src['wbs_version'],src['wbs_digest'],src['estimate_version'],src['estimate_digest'],pr.canonical(doc),pp.digest(doc),actor,stamp))
    return view(c,pid,w)
