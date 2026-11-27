"""P6.4d.3: map exact executable acceptance cases to static file impact.

Only comparisons ending in the selected candidate are eligible. Mapping is
advisory and never exempts any case from full regression or authorizes execution.
"""
import sqlite3
import engineering_dependency_impact as di
import engineering_test_plan as tp
import acceptance_runner as runner
import project_planning as pp

FLAGS=di.FLAGS

def digest_ok(v):
    return v['evidence_digest']==pp.digest({k:x for k,x in v.items() if k!='evidence_digest'})

def map_cases(cases,targets,graph,comparison):
    files=di.index(graph)
    direct=set(comparison['direct_paths']);transitive=set(comparison['transitive_paths'])
    impacted=set(comparison['current_impacted_paths'])
    if (len(cases)!=len(targets) or not cases or len({x['id'] for x in cases})!=len(cases)
        or not impacted<=set(files) or comparison['full_regression_required'] is not True):
        raise ValueError('Incomplete mapping inputs')
    fallback=comparison['analysis_mode']=='CONSERVATIVE_ALL_FILES'
    if comparison['analysis_mode'] not in ('CONSERVATIVE_ALL_FILES','STATIC_IMPORT_REACHABILITY'):
        raise ValueError('Unknown analysis mode')
    if fallback and impacted!=set(files):raise ValueError('Incomplete conservative impact')
    if not fallback and impacted!=(direct|transitive)&set(files):
        raise ValueError('Incomplete static impact')
    rows=[]
    for case,target in zip(cases,targets):
        x=tp.assertion.validate(case['execution'])
        path=x['module']+'.py'
        if target!={'path':path,'module_sha256':files.get(path,{}).get('sha256')} or path not in files:
            raise ValueError('Exact assertion module binding required')
        if fallback:reason='CONSERVATIVE_FALLBACK'
        elif path in direct:reason='DIRECT_CHANGE'
        elif path in transitive:reason='TRANSITIVE_DEPENDENCY'
        else:reason='NO_STATIC_IMPACT_DETECTED'
        rows.append(dict(case_id=case['id'],criterion_id=case['criterion_id'],kind=case['kind'],
                         assertion_digest=pp.digest(x),path=path,module_sha256=target['module_sha256'],
                         impacted=path in impacted,reason=reason,required=True))
    return dict(from_commit=comparison['from_commit'],to_commit=comparison['to_commit'],
                cases=rows,case_count=len(rows),impacted_count=sum(x['impacted'] for x in rows),
                required_count=len(rows),full_regression_required=True)

def derive(impact,plan,source,targets):
    if (impact['state']!='DEPENDENCY_IMPACT_READY' or not digest_ok(impact)
        or impact['full_regression_required'] is not True or impact['selective_execution_authorized'] is not False
        or plan['state']!='TEST_PLAN_COVERAGE_PASS' or plan['assertion_status']!='ASSERTION_CONTRACT_READY'
        or any(v.get(k) is not False for v in (impact,plan) for k in FLAGS)):
        raise ValueError('Current impact and executable plan required')
    src=impact['source']['git_source'];lane=source['selected']
    receipt=plan['history'][-1];e=receipt['snapshot']
    pid=source['project_id'];jid=source['job_id']
    if (lane not in ('A','B') or lane!=src['selected']
        or any(v['project_id']!=pid or v['job_id']!=jid for v in (impact,plan,src,e,e['source']))
        or e['schema']!=tp.V2 or type(e['version']) is not int
        or e['version']!=plan['latest_version'] or e['version']!=len(plan['history'])
        or receipt['digest']!=pp.digest(e) or receipt['digest']!=source['plan_digest']
        or source['plan_version']!=e['version']
        or e['source_digest']!=pp.digest(e['source'])
        or e['source_digest']!=plan['source_digest'] or e['source_digest']!=source['source_digest']
        or e['source_digest']!=src['qa_source_digest']
        or e['assertion_contract_digest']!=tp.contract_digest(e)
        or e['assertion_contract_digest']!=plan['assertion_contract_digest']
        or e['assertion_contract_digest']!=source['assertion_contract_digest']
        or source['selection_digest']!=src['selection_digest'] or source['sandbox_digest']!=src['sandbox_digest']
        or source['git']!=src['git'][lane]
        or source['candidate_digest']!=source['git']['source_sha256']
        or source['candidate_digest']!=e['source']['candidates'][lane]['digest']
        or any(e.get(k) is not False for k in FLAGS)):
        raise ValueError('Cross-source mapping mismatch')
    cases,cov=tp.coverage(e['source'],e['cases'],tp.V2)
    if cases!=e['cases'] or cov!=e['coverage'] or not cov['complete']:
        raise ValueError('Incomplete executable coverage')
    selected='baseline_to_'+lane
    if impact['selected_comparison']!=selected:raise ValueError('Selected comparison mismatch')
    names=[selected]+(['A_to_B'] if lane=='B' else [])
    graph=impact['graphs'][lane]
    mappings={}
    for name in names:
        comparison=impact['comparisons'][name]
        expected_from=src['base_commit'] if name==selected else src['git']['A']['commit']
        if comparison['from_commit']!=expected_from or comparison['to_commit']!=source['git']['commit']:
            raise ValueError('Comparison commit mismatch')
        mappings[name]=map_cases(cases,targets,graph,comparison)
    return dict(impact_evidence_digest=impact['evidence_digest'],runner_source=source),selected,mappings

def view(c,db,pid,jid):
    out=dict(schema='orbit.impacted-test-mapping.v1',project_id=pid,job_id=jid,state='BLOCK',
             source=None,selected_comparison=None,mappings={},scope='development_evidence_only',
             full_regression_required=True,selective_execution_authorized=False,**FLAGS)
    try:
        impact=di.view(c,db,pid,jid)
        plan=tp.view(c,pid,jid)
        source,cases,_,targets=runner.current(c,db,pid,jid)
        if source['project_id']!=pid or source['job_id']!=jid or cases!=plan['history'][-1]['snapshot']['cases']:
            raise ValueError('Current case mismatch')
        binding,selected,mappings=derive(impact,plan,source,targets)
        out.update(state='IMPACTED_TEST_MAPPING_READY',source=binding,selected_comparison=selected,mappings=mappings)
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,PermissionError,sqlite3.Error,OSError,SyntaxError,RecursionError):
        pass
    out['evidence_digest']=pp.digest(out)
    return out
