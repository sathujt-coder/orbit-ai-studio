"""P6.2c: immutable hierarchical WBS drafts; no adoption or execution."""
import copy,json,re
import product_requirements as pr
import project_planning as pp
import planning_jobs as pj
import planning_discovery as pd
import planning_scope as ps
import requirements_scope as rs
import planning_constraints as pc

POLICY='orbit.wbs.v1'
MAX_BYTES=24000
MAX_PACKAGES=64
DETAIL_FIELDS=('action','output','evidence')

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS work_breakdowns(
        project_id TEXT NOT NULL REFERENCES projects(id),version INTEGER NOT NULL,
        requirements_version INTEGER NOT NULL,requirements_digest TEXT NOT NULL,
        queue_id TEXT NOT NULL REFERENCES planning_runs(queue_id),lane TEXT NOT NULL CHECK(lane IN ('A','B')),
        proposal_digest TEXT NOT NULL,document TEXT NOT NULL,digest TEXT NOT NULL,
        author TEXT NOT NULL,created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,version),
        FOREIGN KEY(project_id,requirements_version) REFERENCES product_requirements(project_id,version))""")

def latest(c,pid):
    return c.execute('SELECT * FROM work_breakdowns WHERE project_id=? ORDER BY version DESC LIMIT 1',(pid,)).fetchone()

def current_source(c,pid,lane,discovery=None):
    if lane not in ('A','B'):raise ValueError('Choose PM lane A or B')
    run=discovery if discovery is not None else pj.latest(c,pid)
    if not run or not run['ready'] or run['stale']:raise ValueError('Current quality-gated PM proposals required')
    src=pp.require_input(c,pid,run['requirements_version'],run['requirements_digest'])
    saved=json.loads(pj.input_for(c,pid,run['queue_id'])['snapshot'])
    if 'scope_contract' in saved:src['scope_contract']=saved['scope_contract']
    if pr.canonical(src)!=pr.canonical(saved):raise ValueError('Planning snapshot mismatch')
    evidence=run['evidence']
    if not pd.quality_gate(evidence,src)['scope_ready']:raise ValueError('PM quality gate blocked')
    proposal=pp.validate(evidence['proposals'][lane],src['document'])
    # Bind the entire evidence and source, not just the model-generated title.
    return dict(requirements_version=src['version'],requirements_digest=src['digest'],
        queue_id=run['queue_id'],lane=lane,proposal_digest=pp.digest(dict(evidence=evidence,snapshot=saved,lane=lane)),
        document=src['document'],proposal=proposal,policy=pd.packet(src)['planning_scope'])

def skeleton(source):
    doc=pr.validate(source['document']);plan=pp.validate(source['proposal'],doc)
    tasks={(t['requirements'][0],t['kind']):t for t in plan['tasks']}
    deliverables=[];count=0
    for i,req in enumerate(doc['requirements'],1):
        rid=req['id'];did='D-'+str(i);build=did+'.1'
        criteria=[dict(id=rid+'/AC-'+str(j),text=text) for j,text in enumerate(req['acceptance'],1)]
        impl=tasks[rid,'implement'];verify=tasks[rid,'verify']
        def package(identifier,kind,parent,refs,deps):
            return dict(id=identifier,kind=kind,source_task=parent['id'],source_title=parent['title'],
                criteria=refs,depends_on=deps,action=None,output=None,evidence=None)
        packages=[package(build,'implement',impl,[x['id'] for x in criteria],[])]
        packages.extend(package(did+'.'+str(j+1),'verify',verify,[ac['id']],[build]) for j,ac in enumerate(criteria,1))
        count+=len(packages)
        deliverables.append(dict(id=did,requirement=rid,outcome=req['description'],priority=req['priority'],
            acceptance=criteria,packages=packages))
    if count>MAX_PACKAGES:raise ValueError('WBS exceeds 64 work packages; split approved scope')
    result=dict(policy=POLICY,objective=plan['objective'],deliverables=deliverables)
    if len(pr.canonical(result).encode())>MAX_BYTES:raise ValueError('WBS exceeds 24 KB')
    return result

def validate(document,source):
    """Preserve exact generated hierarchy, source tasks, criteria and edges."""
    expected=skeleton(source)
    pr.fields(document,('policy','objective','deliverables'))
    if document['policy']!=POLICY or document['objective']!=expected['objective']:
        raise ValueError('WBS source objective or policy mismatch')
    raw=document['deliverables']
    if not isinstance(raw,list) or len(raw)!=len(expected['deliverables']):raise ValueError('Deliverable coverage mismatch')
    out=copy.deepcopy(expected)
    for actual,wanted in zip(raw,out['deliverables']):
        pr.fields(actual,('id','requirement','outcome','priority','acceptance','packages'))
        if any(actual[k]!=wanted[k] for k in wanted if k!='packages'):raise ValueError('Deliverable or exact acceptance criteria mismatch')
        if not isinstance(actual['packages'],list) or len(actual['packages'])!=len(wanted['packages']):raise ValueError('Work package coverage mismatch')
        for item,pkg in zip(actual['packages'],wanted['packages']):
            pr.fields(item,tuple(pkg))
            if any(item[k]!=pkg[k] for k in pkg if k not in DETAIL_FIELDS):raise ValueError('Work package source, mapping or dependency mismatch')
            for field in DETAIL_FIELDS:
                value=item[field]
                pkg[field]=None if value is None else pr.string(value,159)
    if len(pr.canonical(out).encode())>MAX_BYTES:raise ValueError('WBS exceeds 24 KB')
    return out

def match_rules(deliverable,package,policy):
    relevant={ac['text'] for ac in deliverable['acceptance'] if ac['id'] in package['criteria']}|{deliverable['outcome']}
    return pc.rules_for(policy,[deliverable['requirement']],package['kind'],relevant)

def missing_groups(text,rule):
    return pc.missing_groups(text,rule['matches'])

def technical_codes(field,value):
    # Conservative, language-neutral minimum plus a narrow English generic-verb
    # heuristic. This is not proof of technical feasibility or actual execution.
    words=rs.norm(value).split()
    if field=='action':
        result=[]
        if len(words)<5:result.append('action_lacks_specificity')
        generic={'implement','develop','create','build','add','make','ensure'}
        anchors={'handler','endpoint','function','query','table','database','input','form','button','route',
            'middleware','guard','validation','check','checks','filter','using','by','via','with','component',
            'schema','service','request','response','test','assertion','policy','constraint','index','repository',
            'transaction','storage','interface','model','module','script','configuration','document','record'}
        if words and words[0] in generic and not anchors.intersection(words[1:]):
            result.append('action_missing_technical_anchor')
        return result
    if field=='evidence' and len(words)<4:return ['evidence_lacks_specificity']
    if field=='output' and words:
        # A narrow additional check for action/assertion text in the artifact
        # slot. Do not require English artifact nouns for other languages.
        if words[0] in ('verify','assert','simulate','inspect','compare') or words[-1] in ('assertion','assertions'):
            return ['output_role_confusion']
    return []

def assess(document,source):
    doc=validate(document,source);issues=[];trace={};seen={}
    for d in doc['deliverables']:
        exact={rs.norm(d['outcome']),*(rs.norm(x['text']) for x in d['acceptance'])}
        for ac in d['acceptance']:
            trace[ac['id']]=dict(requirement=d['requirement'],criterion=ac['text'],implement=[],verify=[])
        for p in d['packages']:
            for cid in p['criteria']:trace[cid][p['kind']].append(p['id'])
            forbidden=source['policy']['forbidden']
            for field in DETAIL_FIELDS:
                value=p[field]
                def issue(code):issues.append(dict(package=p['id'],field=field,code=code))
                if value is None:issue('missing_detail');continue
                normalized=rs.norm(value)
                if normalized in exact or normalized==rs.norm(p['source_title']):
                    issue('requirement_or_proposal_restatement')
                if len(normalized.split())<3 or normalized in ('to be determined','not yet decided','not applicable','test the requirement','implement the requirement','verify the requirement','write some code','test the feature'):
                    issue('generic_detail')
                for code in ps.content_codes(value):issue(code)
                for code in technical_codes(field,value):issue(code)
                if rs.review_text(value):issue('review_contamination')
                if any(rs.contains(value,x) for x in forbidden):issue('forbidden_scope')
                if normalized in seen:
                    other_id,other_field=seen[normalized]
                    issues.append(dict(package=p['id'],field=field,code='duplicate_detail',
                        conflicts_with=dict(package=other_id,field=other_field)))
                else:seen[normalized]=(p['id'],field)
            # All additional human-confirmed literal rules still apply. For
            # verification, require the rule for this criterion (or description).
            text=' '.join(p[k] or '' for k in DETAIL_FIELDS)
            for rule in match_rules(d,p,source['policy']):
                missing=missing_groups(text,rule)
                if missing:
                    issues.append(dict(package=p['id'],field='details',code='missing_scope_evidence',
                        requirement=d['requirement'],criterion=rule['evidence'],missing_groups=missing))
            if p['kind']=='implement' and p['action'] is not None and re.match(
                    r'^(verify|test|assert|simulate|inspect|compare|kiểm tra|kiểm thử|xác minh|đối chiếu)\b',rs.norm(p['action'])):
                issues.append(dict(package=p['id'],field='action',code='implementation_action_required'))
            if p['kind']=='verify' and p['action'] is not None:
                # Verification is an explicit check, not an implementation instruction.
                action=rs.norm(p['action'])
                if not re.match(r'^(test|verify|check|assert|simulate|attempt|inspect|compare|run|kiểm tra|kiểm thử|xác minh|đối chiếu|thử)\b',action):
                    issues.append(dict(package=p['id'],field='action',code='verification_action_required'))
    count=sum(len(d['packages']) for d in doc['deliverables'])
    return dict(policy=POLICY,deliverable_count=len(doc['deliverables']),package_count=count,
        criterion_count=len(trace),traceability=trace,issues=issues,structure_ready=True,
        detail_ready=not issues,semantic_reviewed=False)

def bindings(source):
    return {k:source[k] for k in ('requirements_version','requirements_digest','queue_id','lane','proposal_digest')}

def view(c,pid,discovery=None):
    row=latest(c,pid);sources={};current=None;analysis=None;stale=False
    # Project-scoped discovery must still pass the P6.2b gates.
    run=discovery if discovery is not None else pj.latest(c,pid)
    if run and run['ready']:
        for lane in ('A','B'):
            try:sources[lane]=bindings(current_source(c,pid,lane,run))
            except (KeyError,ValueError,TypeError):pass
    if row:
        current=dict(row);current['document']=json.loads(row['document'])
        stale=True
        try:
            source=current_source(c,pid,row['lane'],run)
            stale=any(row[k]!=v for k,v in bindings(source).items()) or pp.digest(current['document'])!=row['digest']
            if not stale:analysis=assess(current['document'],source)
        except (KeyError,ValueError,TypeError):stale=True
    return dict(current=current,sources=sources,stale=stale,analysis=analysis,
        decomposition_ready=bool(analysis and analysis['detail_ready'] and not stale),
        history=[dict(x) for x in c.execute("""SELECT version,requirements_version,requirements_digest,queue_id,lane,proposal_digest,digest,author,created_at
            FROM work_breakdowns WHERE project_id=? ORDER BY version DESC LIMIT 50""",(pid,))])

def save(c,pid,actor,body,stamp,*,seed=False):
    pp.check_role(c,pid,actor,'write')
    keys=('expected_version','requirements_version','requirements_digest','queue_id','lane','proposal_digest')
    pr.fields(body,keys+('confirmation',) if seed else keys+('document',))
    if seed and body['confirmation']!='CREATE WBS DRAFT':raise ValueError('Explicit CREATE WBS DRAFT required')
    source=current_source(c,pid,body['lane'])
    if type(body['requirements_version']) is not int or any(body[k]!=v for k,v in bindings(source).items()):
        raise ValueError('Current approved PRD and proposal digest required')
    row=latest(c,pid);expected=body['expected_version']
    if type(expected) is not int or expected!=(row['version'] if row else 0):raise ValueError('Stale WBS version')
    if not seed and (not row or any(row[k]!=v for k,v in bindings(source).items())):
        raise ValueError('Create a fresh WBS draft for this proposal first')
    doc=skeleton(source) if seed else validate(body['document'],source)
    assess(doc,source)
    c.execute("""INSERT INTO work_breakdowns(project_id,version,requirements_version,requirements_digest,queue_id,lane,proposal_digest,document,digest,author,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(pid,expected+1,source['requirements_version'],source['requirements_digest'],
        source['queue_id'],source['lane'],source['proposal_digest'],pr.canonical(doc),pp.digest(doc),actor,stamp))
    return view(c,pid)
