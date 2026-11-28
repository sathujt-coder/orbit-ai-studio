"""Shared literal constraint engine. AND groups, OR approved phrases.
No stemming, text insertion or modification of the approved contract.
"""
import requirements_scope as rs

POLICY='orbit.planning-constraints.v1'

def rules_for(policy,requirements,kind,evidence=None):
    return [rule for rule in policy['rules'] if rule['requirement'] in requirements
        and rule['kind']==kind and (evidence is None or rule['evidence'] in evidence)]

def groups_for(rules):
    return [group for rule in rules for group in rule['matches']]

def matches(text,group):
    return any(rs.contains(text,phrase) for phrase in group)

def missing_groups(text,groups):
    return [group for group in groups if not matches(text,group)]

def required_exact_terms(groups,retained_text=''):
    """Deterministic greedy cover; only approved phrases, stable ties.
    Hints are not new gate conditions: any approved alternative is valid.
    """
    pending=missing_groups(retained_text,groups)
    terms=[]
    while pending:
        choices=list(dict.fromkeys(phrase for group in pending for phrase in group))
        best=max(choices,key=lambda phrase:sum(matches(phrase,group) for group in pending))
        terms.append(best)
        pending=[group for group in pending if not matches(best,group)]
    return terms

def lost_groups(before,after,groups):
    return [group for group in groups if matches(before,group) and not matches(after,group)]

def losses(before,after,rules):
    result=[]
    for rule in rules:
        lost=lost_groups(before,after,rule['matches'])
        if lost:
            result.append(dict(requirement=rule['requirement'],kind=rule['kind'],
                evidence=rule['evidence'],lost_groups=lost))
    return result
