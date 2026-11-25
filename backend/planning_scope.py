"""P6.2b.2: literal PRD-bound scope and acceptance evidence, not a semantic oracle."""
import copy
import product_requirements as pr
import project_planning as pp
import requirements_scope as rs

def contract(document,extra=None):
    doc=pr.validate(document);reqs={r['id']:r for r in doc['requirements']}
    if extra is None:extra=dict(forbidden=[],rules=[])
    pr.fields(extra,('forbidden','rules'))
    additional=rs.phrases(extra['forbidden'],0,30)
    excluded=doc['out_of_scope']
    # Never infer a list of new features from a prose exclusion. Match the exact
    # approved exclusion, normalized; no silent truncation or omission.
    if any(not rs.norm(x) for x in excluded):raise ValueError('Invalid PRD exclusion')
    forbidden=[];seen=set()
    for x in excluded+additional:
        n=rs.norm(x)
        if n not in seen:forbidden.append(x);seen.add(n)
    raw=extra['rules']
    if not isinstance(raw,list) or len(raw)>32:raise ValueError('Expected at most 32 planning scope rules')
    rules=[];seen=set()
    for rule in raw:
        pr.fields(rule,('requirement','kind','evidence','matches'))
        rid=rule['requirement'];kind=rule['kind']
        if not isinstance(rid,str) or rid not in reqs or kind not in ('implement','verify'):
            raise ValueError('Unknown requirement or task kind')
        evidence=pr.string(rule['evidence'],500)
        req=reqs[rid]
        if evidence not in ([req['description']]+req['acceptance']):
            raise ValueError('Planning scope evidence must equal approved requirement description or acceptance criterion')
        key=(rid,kind,evidence)
        if key in seen:raise ValueError('Duplicate planning scope rule')
        seen.add(key)
        groups=rule['matches']
        if not isinstance(groups,list) or not 1<=len(groups)<=4:raise ValueError('Invalid planning match groups')
        rules.append(dict(requirement=rid,kind=kind,evidence=evidence,matches=[rs.phrases(g,1,8) for g in groups]))
    result=dict(forbidden=forbidden,rules=rules)
    if len(pr.canonical(result).encode())>10000:raise ValueError('Planning scope exceeds 10 KB')
    return result

def assess(plan,document,policy):
    doc=pp.validate(plan,document)
    issues=[]
    def forbidden(target,text):
        for phrase in policy['forbidden']:
            if rs.contains(text,phrase):issues.append(dict(target=target,code='forbidden_scope',phrase=phrase))
        if rs.review_text(text):issues.append(dict(target=target,code='review_contamination'))
    forbidden('objective',doc['objective'])
    for task in doc['tasks']:
        tid=task['id'];title=task['title'];forbidden(tid,title)
        for rule in policy['rules']:
            if rule['requirement'] in task['requirements'] and rule['kind']==task['kind']:
                missing=[group for group in rule['matches'] if not any(rs.contains(title,phrase) for phrase in group)]
                if missing:issues.append(dict(target=tid,code='missing_acceptance_evidence',
                    requirement=rule['requirement'],evidence=rule['evidence'],missing=missing))
    return dict(passed=not issues,issues=issues,contract_digest=pp.digest(policy))

def targets(findings):
    return sorted({i['target'] for i in findings['issues']})

def patch(plan,changes,findings,document):
    wanted=set(targets(findings))
    if not isinstance(changes,list) or not wanted or len(changes)!=len(wanted):
        raise ValueError('Exactly one replacement per flagged field required')
    replacements={}
    for item in changes:
        pr.fields(item,('target','title'))
        target=item['target']
        if not isinstance(target,str) or target not in wanted or target in replacements:
            raise ValueError('Unexpected or duplicate repair target')
        replacements[target]=pr.string(item['title'],160)
    revised=copy.deepcopy(plan)
    if 'objective' in replacements:revised['objective']=replacements['objective']
    for task in revised['tasks']:
        if task['id'] in replacements:task['title']=replacements[task['id']]
    return pp.validate(revised,document)

def convergence(before,after,document,policy):
    a=assess(before,document,policy);b=assess(after,document,policy)
    allowed=set(targets(a));old={t['id']:t for t in before['tasks']};new={t['id']:t for t in after['tasks']}
    unchanged=set(old)==set(new) and (before['objective']==after['objective'] or 'objective' in allowed)
    for tid in set(old)&set(new):
        unchanged=unchanged and ({k:v for k,v in old[tid].items() if k!='title'}=={k:v for k,v in new[tid].items() if k!='title'})
        unchanged=unchanged and (old[tid]['title']==new[tid]['title'] or tid in allowed)
    before_text={k:rs.norm(t['title']) for k,t in old.items()};after_text={k:rs.norm(t['title']) for k,t in new.items()}
    no_op=(before_text==after_text and rs.norm(before['objective'])==rs.norm(after['objective']))
    old_issues={pr.canonical(i) for i in a['issues']}
    new_issues=[i for i in b['issues'] if pr.canonical(i) not in old_issues]
    passed=bool(a['issues'] and b['passed'] and unchanged and not no_op and not new_issues)
    return dict(passed=passed,before_issues=len(a['issues']),after_issues=len(b['issues']),
        unchanged_unflagged=bool(unchanged),no_op=no_op,new_issues=new_issues,
        before_digest=pp.digest(before),after_digest=pp.digest(after))
