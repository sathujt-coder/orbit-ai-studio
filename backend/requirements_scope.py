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
    required={'rules','forbidden','nonblocking_questions'}
    optional={'deferred_metric_subjects','problem_source'}
    if not isinstance(contract,dict) or not required<=set(contract) or set(contract)-required-optional:
        raise ValueError('Unexpected or missing scope contract fields')
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
    if 'deferred_metric_subjects' in contract:
        subjects=phrases(contract['deferred_metric_subjects'],0,20)
        # Subjects are literal nouns, not regex or questions/decision clauses.
        if any(len(norm(x).split())>8 or any(contains(x,p) for p in
                ('maximum','minimum','limit','allowed','required','must','should','shall','may','can','will','permission','authorization','retention','access','quota','threshold','security','privacy','read','write','delete','approve','approval','latency','capacity')) for x in subjects):
            raise ValueError('Metric subjects must describe observations, not decisions')
        result['deferred_metric_subjects']=subjects
    if 'problem_source' in contract:
        quote=pr.string(contract['problem_source'],500)
        if quote not in idea or review_text(quote):raise ValueError('Problem source must be a non-review exact idea quote')
        result['problem_source']=quote
    if len(pr.canonical(result).encode())>12000:raise ValueError('Scope contract too large')
    return result

# Deliberately narrow classification. Unrecognized wording or policy/decision
# questions remain blocking. No model can authorize a deferred category.
def classify_question(question,contract):
    q=norm(question)
    if q in {norm(x) for x in contract['nonblocking_questions']}:
        return 'explicitly_deferred'
    match=re.fullmatch(r'(?:what is the (?:average|median|typical) number of|how many) (.+)',q)
    if match and match[1] in {norm(x) for x in contract.get('deferred_metric_subjects',[])}:
        return 'descriptive_metric'
    return 'unresolved_decision'

def review_text(value):
    return bool(re.search(r"\b(?:candidate s proposal|candidate proposal|the candidate (?:does not|fails to|lacks)|the (?:document|proposal|draft|prd|srs) (?:does not|fails to|lacks|is missing|should include)|reviewer (?:feedback|findings|comments)|define a clear definition)\b",norm(value)))

def semantic_digest(document):
    """Canonical content identity ignoring generated IDs, collection order and case.
    Not an embedding or a proof of paraphrase equivalence."""
    doc=pr.validate(document)
    def txt(s):return ' '.join(unicodedata.normalize('NFKC',s).casefold().split())
    reqs={r['id']:dict(kind=r['kind'],description=txt(r['description']),
        priority=r['priority'],acceptance=sorted(txt(x) for x in r['acceptance'])) for r in doc['requirements']}
    content={k:(sorted(txt(x) for x in v) if isinstance(v,list) else txt(v))
        for k,v in doc.items() if k not in ('requirements','stories')}
    content['requirements']=sorted(pr.canonical(r) for r in reqs.values())
    content['stories']=sorted(pr.canonical(dict(actor=txt(s['actor']),goal=txt(s['goal']),benefit=txt(s['benefit']),
        requirements=sorted(pr.canonical(reqs[r]) for r in s['requirements']))) for s in doc['stories'])
    return digest(content)

def issue_keys(document,findings):
    reqs={r['id']:r for r in document['requirements']}
    keys=[]
    for issue in findings['issues']:
        key=dict(issue)
        rid=key.pop('requirement_id',None)
        if rid is not None:
            r=reqs[rid]
            key['requirement_content']=norm(r['description'])+' '+norm(' '.join(sorted(r['acceptance'])))
        if 'question' in key:key['question']=norm(key['question'])
        keys.append(pr.canonical(key))
    return sorted(keys)

def convergence(before,after,contract,before_review,after_review):
    """Block cosmetic edits, unchanged defects, and regressions in required scope."""
    from collections import Counter
    b=assess(before,contract);a=assess(after,contract)
    bk=Counter(issue_keys(before,b));ak=Counter(issue_keys(after,a))
    unchanged=semantic_digest(before)==semantic_digest(after)
    remaining={norm(q) for q in after['open_questions']}
    unresolved_removed=[q for q in before['open_questions'] if classify_question(q,contract)=='unresolved_decision' and norm(q) not in remaining]
    lost=[r['id'] for r in contract['rules'] if r['required'] and b['coverage'][r['id']] and not a['coverage'][r['id']]]
    before_count=sum(bk.values())+len(before_review['blocking'])
    after_count=sum(ak.values())+len(after_review['blocking'])
    new=list((ak-bk).elements())
    # All hard defects must disappear for adoption, and repaired output must
    # reduce defects without introducing new deterministic failures.
    improved=not unchanged and not lost and not new and not unresolved_removed and after_count<before_count
    return dict(passed=improved,no_op=unchanged,before_issues=before_count,after_issues=after_count,
        lost_required_scope=lost,new_issues=new,unresolved_questions_removed=unresolved_removed,before_content_digest=semantic_digest(before),
        after_content_digest=semantic_digest(after))

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
    content_fields=('problem','goals','users','scope','assumptions','out_of_scope')
    for field in content_fields:
        values=[doc[field]] if isinstance(doc[field],str) else doc[field]
        for value in values:
            if review_text(value):issues.append(dict(code='review_contamination',field=field))
    for req in doc['requirements']:
        if any(review_text(v) for v in [req['description'],*req['acceptance']]):
            issues.append(dict(code='review_contamination',field='requirement',requirement_id=req['id']))
    for story in doc['stories']:
        if any(review_text(story[k]) for k in ('actor','goal','benefit')):
            for rid in story['requirements']:
                issues.append(dict(code='review_contamination',field='story',requirement_id=rid))
    questions=[dict(question=q,classification=classify_question(q,contract)) for q in doc['open_questions']]
    for item in questions:
        issues.append(dict(code='open_question',question=item['question']))

    return dict(passed=not issues,issues=issues,mapping=mapping,coverage=coverage,
        unsupported=unsupported,question_classifications=questions,contract_digest=digest(contract))

def hard_issues(findings):
    """Approved deferrals still require projection but are not reviewer defects."""
    deferred={q['question'] for q in findings.get('question_classifications',[])
        if q['classification']!='unresolved_decision'}
    return [i for i in findings['issues'] if i['code']!='open_question' or i['question'] not in deferred]

def targeted_repair(document,contract,*,alternatives=None):
    """Bounded projection from confirmed scope and existing A/B drafts; preserve provenance."""
    original=pr.validate(document);candidate=copy.deepcopy(original)
    before=assess(original,contract);denied=set(before['unsupported'])
    deferred=[q for q in original['open_questions'] if classify_question(q,contract)!='unresolved_decision']
    problem_replaced=False;restored=[];metadata_replaced=[]
    if contract.get('problem_source') and review_text(original['problem']):
        candidate['problem']=contract['problem_source'];problem_replaced=True
    # Replace review commentary in goal/scope only with exact confirmed required
    # source quotes. Keep all clean existing entries, never invent product claims.
    anchors=list(dict.fromkeys(r['evidence'] for r in contract['rules'] if r['required']
        and not review_text(r['evidence']) and not any(contains(r['evidence'],p) for p in contract['forbidden'])))
    for field in ('goals','scope'):
        if anchors and any(review_text(x) for x in original[field]):
            clean=[x for x in original[field] if not review_text(x)]
            candidate[field]=list(dict.fromkeys(clean+anchors))
            metadata_replaced.append(field)
    # Remove review-contaminated requirement/story records as well, but never
    # if doing so loses required coverage without a safe source-draft replacement.
    denied.update(i['requirement_id'] for i in before['issues'] if i['code']=='review_contamination' and 'requirement_id' in i)
    if denied:
        candidate['requirements']=[r for r in candidate['requirements'] if r['id'] not in denied]
        stories=[]
        for story in candidate['stories']:
            story['requirements']=[r for r in story['requirements'] if r not in denied]
            if story['requirements']:stories.append(story)
        candidate['stories']=stories
    candidate['open_questions']=[q for q in candidate['open_questions'] if q not in deferred]
    # Recover missing required coverage only from an already generated draft
    # with exact per-requirement story provenance. Do not invent content.
    def next_id(rows,prefix):
        prior=original['requirements'] if prefix=='REQ-' else original['stories']
        return prefix+str(max([int(x['id'].split('-')[1]) for x in rows+prior]+[0])+1)
    def covered(rule,req):
        text=' '.join([req['description'],*req['acceptance']])
        return req['kind']==rule['kind'] and all(any(contains(text,p) for p in group) for group in rule['matches'])
    for rule in contract['rules']:
        if not rule['required'] or any(covered(rule,r) for r in candidate['requirements']):continue
        if sum(r['kind']==rule['kind'] for r in candidate['requirements']) >= (4 if rule['kind']=='functional' else 3):continue
        found=False
        for lane,draft in sorted((alternatives or {}).items()):
            clean=pr.validate(draft)
            audit=assess(clean,contract)
            bad=set(audit['unsupported'])|{i['requirement_id'] for i in audit['issues'] if i['code']=='review_contamination' and 'requirement_id' in i}
            for req in clean['requirements']:
                rid=req['id']
                if rid in bad or rid not in audit['coverage'][rule['id']]:continue
                stories=[s for s in clean['stories'] if s['requirements']==[rid]]
                if not stories:continue
                new_id=next_id(candidate['requirements'],'REQ-')
                candidate['requirements'].append(dict(req,id=new_id))
                for story in stories:
                    candidate['stories'].append(dict(story,id=next_id(candidate['stories'],'US-'),requirements=[new_id]))
                restored.append(dict(scope_id=rule['id'],source_lane=lane,source_requirement_id=rid,requirement_id=new_id))
                found=True;break
            if found:break
    # Never commit a structurally invalid projection or one that loses required coverage.
    try:
        candidate=pr.validate(candidate);after=assess(candidate,contract)
        if any(x['code']=='missing_required_scope' for x in after['issues']):
            raise ValueError('Required scope not covered')
    except ValueError:
        candidate=original;after=before;denied=set();deferred=[];restored=[];problem_replaced=False;metadata_replaced=[]
    return candidate,dict(changed=digest(original)!=digest(candidate),removed_requirement_ids=sorted(denied),
        deferred_questions=deferred,problem_replaced=problem_replaced,metadata_replaced=metadata_replaced,restored_requirements=restored,before=before,after=after)
