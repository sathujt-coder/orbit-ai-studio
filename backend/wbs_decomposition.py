"""P6.2d: bounded model-generated WBS detail proposals, never adoption."""
import copy,json
import product_requirements as pr
import project_planning as pp
import planning_discovery as pd
import work_breakdown as w
import model_provider as mp
import requirements_scope as rs
import planning_constraints as pc

POLICY='orbit.wbs-decomposition.v6'
CONTEXT_POLICY='orbit.wbs-isolated-context.v1'
WIRE='flat-package-field.v1'
BATCH=3
MAX_OUTPUT=1536
MAX_CONTEXT_BYTES=16000
RULES=('Return only the requested keys as a flat JSON object of strings. '
       'Plan concrete work for each package description and acceptance criterion. '
       'Follow every field contract; action 8–14 words (minimum 5), output 3+, evidence 4+. '
       'Use distinct concrete details; never copy instructions or approved titles. '
       'Satisfy all match groups using required_exact_terms, with retained coverage counted. '
       'Resolve every listed issue code on repair. No excluded scope, estimates or completed-work claims.')

# Short schema descriptions are the only prose field instructions; the
# request body uses numerical limits and diagnostic codes, not FIX prose.
FIELD_CONTRACTS={
    'implement':dict(action='Imperative technical change: object and mechanism.',
        output='Planned implementation artifact noun phrase.',
        evidence='Expected observable implementation proof.'),
    'verify':dict(action='Begin Test, Verify or Check; operation and condition.',
        output='Planned verification artifact noun phrase.',
        evidence='Expected observable verification result.')}

def packages(document):
    return {p['id']:p for d in document['deliverables'] for p in d['packages']}

def batches(document):
    ids=list(packages(document))
    return [ids[i:i+BATCH] for i in range(0,len(ids),BATCH)]

def full_fields(ids):
    return {pid:list(w.DETAIL_FIELDS) for pid in ids}

def repair_fields(ids,issues):
    # A cross-field scope violation is assigned to action; other fields
    # remain untouched unless independently flagged by the validator. Every
    # example_contamination finding is field-specific, so all copied fields
    # are editable together within the same bounded repair call.
    return {pid:[k for k in w.DETAIL_FIELDS if any(x['package']==pid and
        (x['field']==k or (x['field']=='details' and k=='action')) for x in issues)]
        for pid in ids if any(x['package']==pid for x in issues)}

def flat_key(pid,field):
    return pid+'.'+field

def flat_fields(ids,fields):
    return {flat_key(pid,k):(pid,k) for pid in ids for k in fields[pid]}

def flatten(patch):
    """Canonical wire mapping; values remain unchanged model-authored text."""
    return {flat_key(pid,k):value for pid,detail in patch.items() for k,value in detail.items()}

def schema(ids,fields=None,document=None):
    fields=full_fields(ids) if fields is None else fields
    by_id=packages(document) if document is not None else {}
    mapping=flat_fields(ids,fields)
    properties={}
    for key,(pid,k) in mapping.items():
        kind=by_id[pid]['kind'] if pid in by_id else 'implement'
        properties[key]=dict(type='string',minLength=1,maxLength=159,description=FIELD_CONTRACTS[kind][k])
    return dict(type='object',additionalProperties=False,required=list(mapping),properties=properties)

def exact_terms(groups):
    return pc.required_exact_terms(groups)

def context(source,document,ids,issues=None,fields=None):
    fields=full_fields(ids) if fields is None else fields
    targets=[]
    # No generated detail text is serialized into any subsequent request.
    # Retained coverage is computed locally. References are identifiers only.
    # Fail closed if a contaminated retained field was omitted from repair.
    for pid,p in packages(document).items():
        for k in w.DETAIL_FIELDS:
            if (pid not in fields or k not in fields[pid]) and w.detail_contaminated(p[k]):
                raise ValueError('Contaminated field must be included in repair targets')
    for d in document['deliverables']:
        for p in d['packages']:
            pid=p['id']
            if pid not in ids:continue
            criteria=[a for a in d['acceptance'] if a['id'] in p['criteria']]
            retained={k:p[k] for k in w.DETAIL_FIELDS if k not in fields[pid]}
            groups=pc.groups_for(w.match_rules(d,p,source['policy']))
            retained_text=' '.join(v or '' for v in retained.values())
            covered=[i for i,g in enumerate(groups) if pc.matches(retained_text,g)]
            relevant_issues=[x for x in (issues or []) if x['package']==pid]
            contracts={}
            for k in fields[pid]:
                flagged=[x for x in relevant_issues if x['field']==k or (x['field']=='details' and k=='action')]
                entry=dict(min_words=w.MIN_DETAIL_WORDS[k],max_chars=159,
                    fix=list(dict.fromkeys(x['code'] for x in flagged)))
                if k=='action':entry['target_words']=[8,14]
                conflicts=[dict(key=flat_key(x['conflicts_with']['package'],x['conflicts_with']['field']))
                    for x in flagged if x['code']=='duplicate_detail' and 'conflicts_with' in x]
                if conflicts:entry['conflicts_with']=conflicts
                contracts[flat_key(pid,k)]=entry
            targets.append(dict(id=pid,kind=p['kind'],requirement=d['requirement'],description=d['outcome'],
                acceptance=criteria,retained_fields=list(retained),match_groups=groups,
                retained_coverage=covered,required_exact_terms=pc.required_exact_terms(groups,retained_text),
                field_contracts=contracts))
    return dict(protocol=CONTEXT_POLICY,wire=WIRE,forbidden=source['policy']['forbidden'],targets=targets)

def request(source,document,ids,issues=None,fields=None):
    fields=full_fields(ids) if fields is None else fields
    payload=context(source,document,ids,issues,fields)
    body=pr.canonical(payload);shape=schema(ids,fields,document)
    if len(body.encode())>MAX_CONTEXT_BYTES:raise ValueError('Decomposition context exceeds 16 KB; split approved scope')
    return body,shape,dict(wire=WIRE,example_policy=w.EXAMPLE_POLICY,instruction_policy=w.INSTRUCTION_POLICY,context_policy=CONTEXT_POLICY,source_digest=pp.digest(w.bindings(source)),targets=ids,fields=fields,keys=shape['required'],prompt_digest=pp.digest(RULES),context_digest=pp.digest(payload),schema_digest=pp.digest(shape),context_bytes=len(body.encode()))

def decode(raw,ids,fields=None):
    fields=full_fields(ids) if fields is None else fields
    mapping=flat_fields(ids,fields)
    data=pd.strict_json(raw)
    if not isinstance(data,dict):raise pd.RepairError('detail_not_object')
    if set(data)!=set(mapping):
        raise pd.RepairError('detail_target_mismatch',missing=sorted(set(mapping)-set(data)),unexpected_count=len(set(data)-set(mapping)))
    out={pid:{} for pid in ids}
    for key,(pid,field) in mapping.items():
        try:out[pid][field]=pr.string(data[key],159)
        except ValueError:raise pd.RepairError('detail_text_invalid',target=pid,field=field) from None
    return out

def apply(document,patch,source):
    result=copy.deepcopy(document);by_id=packages(result)
    for pid,detail in patch.items():by_id[pid].update(detail)
    return w.validate(result,source)

def local_issues(document,source,ids):
    return [x for x in w.assess(document,source)['issues'] if x['package'] in ids]

def convergence(before,after,source,ids,fields):
    a=local_issues(before,source,ids);b=local_issues(after,source,ids)
    old=packages(before);new=packages(after)
    changed=[(pid,k) for pid,p in old.items() for k in w.DETAIL_FIELDS if p[k]!=new[pid][k]]
    allowed={(pid,k) for pid,keys in fields.items() for k in keys}
    old_issues={pr.canonical(x) for x in a}
    introduced=[x for x in b if pr.canonical(x) not in old_issues]
    # An initially clean field must remain unchanged, except the designated
    # action needed to repair a package-wide missing evidence group.
    no_op=not any(rs.norm(old[pid][k] or '')!=rs.norm(new[pid][k] or '') for pid,k in changed)
    lost=[dict(package=p['id'],**item) for d in before['deliverables'] for p in d['packages']
        for item in pc.losses(' '.join(p[k] or '' for k in w.DETAIL_FIELDS),
            ' '.join(new[p['id']][k] or '' for k in w.DETAIL_FIELDS),w.match_rules(d,p,source['policy']))]
    return dict(passed=bool(a and not b and not introduced and not no_op and set(changed)<=allowed and not lost),
        before_issues=len(a),after_issues=len(b),new_issues=introduced,lost_scope_groups=lost,unchanged_unflagged=set(changed)<=allowed,
        no_op=no_op,before_digest=pp.digest(before),after_digest=pp.digest(after))

def blank(source,document):
    doc=w.validate(document,source)
    if any(p[k] is not None for p in packages(doc).values() for k in w.DETAIL_FIELDS):
        raise ValueError('AI decomposition requires a blank WBS draft; create a fresh draft')
    return doc

def run(call,source,document):
    base=blank(source,document);candidate=base;history=[]
    for ids in batches(base):
        batch=dict(ids=ids,attempts=[]);history.append(batch)
        targets=ids;issues=None;fields=full_fields(ids)
        for retry in (False,True):
            phase='wbs_decompose_repair' if retry else 'wbs_decompose'
            body,shape,meta=request(source,candidate,targets,issues,fields)
            attempt=dict(phase=phase,request=meta,valid=False);batch['attempts'].append(attempt)
            try:raw=call(phase,RULES,body,shape)
            except mp.OutputError as error:
                attempt['diagnostic']=pd.output_diagnostic(error)
                if retry:break
                continue
            try:
                patch=decode(raw,targets,fields)
                revised=apply(candidate,patch,source)
            except ValueError as error:
                attempt['diagnostic']=pd.output_diagnostic(error)
                if retry:break
                continue
            attempt.update(valid=True,patch=flatten(patch),issues_before=local_issues(candidate,source,targets),
                issues_after=local_issues(revised,source,ids))
            if retry:attempt['convergence']=convergence(candidate,revised,source,ids,fields)
            candidate=revised
            issues=attempt['issues_after']
            if not issues:break
            fields=repair_fields(ids,issues);targets=list(fields)
        if local_issues(candidate,source,ids):break
    evidence=dict(policy=POLICY,wire=WIRE,example_policy=w.EXAMPLE_POLICY,instruction_policy=w.INSTRUCTION_POLICY,context_policy=CONTEXT_POLICY,base_digest=pp.digest(base),history=history,candidate=candidate)
    return {**evidence,**gate(evidence,source,base)}

def gate(evidence,source,document):
    """Replay exact model patches against source; never trust ready/audit flags."""
    base=blank(source,document);candidate=base;expected=batches(base)
    history=evidence['history']
    if (evidence.get('policy')!=POLICY or evidence.get('wire')!=WIRE or
            evidence.get('example_policy')!=w.EXAMPLE_POLICY or evidence.get('instruction_policy')!=w.INSTRUCTION_POLICY or
            evidence.get('context_policy')!=CONTEXT_POLICY or evidence.get('base_digest')!=pp.digest(base)):
        raise ValueError('Decomposition source or policy mismatch')
    if not isinstance(history,list) or not 1<=len(history)<=len(expected):raise ValueError('Invalid batch history')
    audit=True;calls=0
    for index,batch in enumerate(history):
        ids=expected[index];attempts=batch['attempts']
        if batch['ids']!=ids or not isinstance(attempts,list) or not 1<=len(attempts)<=2:
            raise ValueError('Invalid batch mapping or call bound')
        targets=ids;issues=None;fields=full_fields(ids)
        for i,attempt in enumerate(attempts):
            calls+=1
            _,_,meta=request(source,candidate,targets,issues,fields)
            phase='wbs_decompose_repair' if i else 'wbs_decompose'
            if attempt['phase']!=phase or attempt['request']!=meta:raise ValueError('Decomposition request audit mismatch')
            if attempt['valid'] is True:
                patch=decode(pr.canonical(attempt['patch']),targets,fields)
                if flatten(patch)!=attempt['patch']:raise ValueError('Noncanonical flat patch')
                revised=apply(candidate,patch,source)
                if attempt['issues_before']!=local_issues(candidate,source,targets) or attempt['issues_after']!=local_issues(revised,source,ids):
                    raise ValueError('Decomposition issue audit mismatch')
                if i:
                    check=convergence(candidate,revised,source,ids,fields)
                    if attempt.get('convergence')!=check:raise ValueError('Decomposition convergence audit mismatch')
                    if not check['passed']:audit=False
                candidate=revised;issues=attempt['issues_after']
                if not issues and i+1!=len(attempts):raise ValueError('Unexpected retry after clean batch')
                fields=repair_fields(ids,issues);targets=list(fields)
            elif attempt['valid'] is False:
                if 'patch' in attempt or not isinstance(attempt.get('diagnostic'),dict):raise ValueError('Invalid failure audit')
            else:raise ValueError('Invalid attempt state')
        if local_issues(candidate,source,ids) and index+1!=len(history):raise ValueError('Continued after blocked batch')
    if candidate!=w.validate(evidence['candidate'],source):raise ValueError('Decomposition replay mismatch')
    analysis=w.assess(candidate,source)
    ready=bool(audit and len(history)==len(expected) and analysis['detail_ready'])
    return dict(ready=ready,repair_audit_valid=audit,analysis=analysis,call_count=calls,
        max_calls=2*len(expected),candidate_digest=pp.digest(candidate),semantic_reviewed=False)
