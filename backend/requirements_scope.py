"""Human-confirmed scope contract. Literal coverage checks, not a semantic oracle."""
import copy
import hashlib
import re
import unicodedata
import product_requirements as pr

def digest(value):
    return hashlib.sha256(pr.canonical(value).encode()).hexdigest()

def norm(value):
    return ' '.join(re.findall(r'\w+',unicodedata.normalize('NFKC',value).casefold()))

def contains(text,phrase):
    return (' '+norm(phrase)+' ') in (' '+norm(text)+' ')

def phrases(value,minimum,maximum):
    result=pr.strings(value,minimum,maximum)
    if any(len(x)>160 or not norm(x) for x in result):raise ValueError('Invalid scope phrase')
    if len({norm(x) for x in result})!=len(result):raise ValueError('Duplicate scope phrase')
    return result

def validate(idea,contract):
    if contract is None:raise ValueError('Explicit scope contract required')
    pr.fields(contract,('rules','forbidden','nonblocking_questions'))
    rules=contract['rules']
    if not isinstance(rules,list) or not 2<=len(rules)<=8:raise ValueError('Expected 2–8 scope rules')
    out=[];ids=set();kinds=set()
    for rule in rules:
        pr.fields(rule,('id','kind','evidence','required','matches'))
        rid=rule['id']
        if not isinstance(rid,str) or not re.fullmatch(r'SC-[0-9]{1,3}',rid) or rid in ids:
            raise ValueError('Invalid or duplicate scope rule ID')
        if rule['kind'] not in ('functional','nonfunctional') or type(rule['required']) is not bool:
            raise ValueError('Invalid scope rule kind or required flag')
        quote=pr.string(rule['evidence'],500)
        if quote not in idea:raise ValueError('Scope evidence must be an exact quote from the project idea')
        groups=rule['matches']
        if not isinstance(groups,list) or not 1<=len(groups)<=4:raise ValueError('Invalid scope match groups')
        groups=[phrases(g,1,8) for g in groups]
        ids.add(rid)
        if rule['required']:kinds.add(rule['kind'])
        out.append(dict(id=rid,kind=rule['kind'],evidence=quote,required=rule['required'],matches=groups))
    if kinds!={'functional','nonfunctional'}:raise ValueError('Required scope must cover both requirement kinds')
    result=dict(rules=out,forbidden=phrases(contract['forbidden'],0,30),
        nonblocking_questions=phrases(contract['nonblocking_questions'],0,20))
    if len(pr.canonical(result).encode())>12000:raise ValueError('Scope contract too large')
    return result

def assess(document,contract):
    """Recompute from content, never accept a model's claimed IDs or verdict."""
    doc=pr.validate(document)
    coverage={r['id']:[] for r in contract['rules']};mapping={};issues=[]
    unsupported=[]
    for req in doc['requirements']:
        rid=req['id'];text=' '.join([req['description'],*req['acceptance']])
        story_text=' '.join(' '.join([s['actor'],s['goal'],s['benefit']]) for s in doc['stories'] if rid in s['requirements'])
        hits=[r['id'] for r in contract['rules'] if r['kind']==req['kind'] and
            all(any(contains(text,p) for p in group) for group in r['matches'])]
        denied=[p for p in contract['forbidden'] if contains(text+' '+story_text,p)]
        mapping[rid]=hits
        if denied or not hits:
            unsupported.append(rid)
            issues.append(dict(code='forbidden_requirement' if denied else 'unmapped_requirement',requirement_id=rid,phrases=denied))
        else:
            for h in hits:coverage[h].append(rid)
    for rule in contract['rules']:
        if rule['required'] and not coverage[rule['id']]:
            issues.append(dict(code='missing_required_scope',scope_id=rule['id']))
    # Exclusions and assumptions may legitimately name forbidden capabilities.
    for field in ('problem','goals','scope'):
        value=doc[field];text=value if isinstance(value,str) else ' '.join(value)
        for phrase in contract['forbidden']:
            if contains(text,phrase):issues.append(dict(code='forbidden_metadata',field=field,phrase=phrase))
    for question in doc['open_questions']:
        issues.append(dict(code='open_question',question=question))
    return dict(passed=not issues,issues=issues,mapping=mapping,coverage=coverage,
        unsupported=unsupported,contract_digest=digest(contract))

def targeted_repair(document,contract):
    """Only remove unauthorized items and explicitly deferred questions, retaining evidence."""
    original=pr.validate(document);candidate=copy.deepcopy(original)
    before=assess(original,contract);denied=set(before['unsupported'])
    deferred=[q for q in original['open_questions'] if norm(q) in {norm(x) for x in contract['nonblocking_questions']}]
    if denied:
        candidate['requirements']=[r for r in candidate['requirements'] if r['id'] not in denied]
        stories=[]
        for story in candidate['stories']:
            story['requirements']=[r for r in story['requirements'] if r not in denied]
            if story['requirements']:stories.append(story)
        candidate['stories']=stories
    candidate['open_questions']=[q for q in candidate['open_questions'] if q not in deferred]
    # Never commit a structurally invalid projection or one that loses required coverage.
    try:
        candidate=pr.validate(candidate);after=assess(candidate,contract)
        if any(x['code']=='missing_required_scope' for x in after['issues']):
            raise ValueError('Required scope not covered')
    except ValueError:
        candidate=original;after=before;denied=set();deferred=[]
    return candidate,dict(changed=digest(original)!=digest(candidate),removed_requirement_ids=sorted(denied),
        deferred_questions=deferred,before=before,after=after)
