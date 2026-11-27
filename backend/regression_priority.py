"""Explicit impact-prioritized scheduling; never a test waiver.

The runner still executes the entire mandatory plan within its original
time limits. Priority metadata is supplemental local output, not a new
execution authority or a replacement for an immutable registry receipt.
"""
import engineering_impacted_tests as mapping
import project_planning as pp
import acceptance_assertion as ac

FLAGS=mapping.FLAGS
KIND_ORDER={'NEGATIVE':0,'BOUNDARY':1,'POSITIVE':2}
REASONS={'DIRECT_CHANGE':True,'TRANSITIVE_DEPENDENCY':True,
         'CONSERVATIVE_FALLBACK':True,'NO_STATIC_IMPACT_DETECTED':False}

def schedule(v,source,cases,targets,comparison,expected_digest):
    if (v['schema']!='orbit.impacted-test-mapping.v1'
        or v['state']!='IMPACTED_TEST_MAPPING_READY'
        or not mapping.digest_ok(v) or v['evidence_digest']!=expected_digest
        or v['source']['runner_source']!=source
        or v['project_id']!=source['project_id'] or v['job_id']!=source['job_id']
        or v['full_regression_required'] is not True or v['selective_execution_authorized'] is not False
        or any(v.get(k) is not False for k in FLAGS)):
        raise ValueError('Current exact mapping required')
    if comparison not in v['mappings']:raise ValueError('Invalid comparison for selected candidate')
    m=v['mappings'][comparison]
    rows=m['cases'];n=len(cases)
    if (not n or len(targets)!=n or len(rows)!=n or type(m['case_count']) is not int
        or m['case_count']!=n or type(m['required_count']) is not int or m['required_count']!=n
        or m['full_regression_required'] is not True
        or len({x['id'] for x in cases})!=n or m['to_commit']!=source['git']['commit']):
        raise ValueError('Incomplete mandatory regression inventory')
    impacted=[]
    for i,(row,case,target) in enumerate(zip(rows,cases,targets)):
        x=ac.validate(case['execution'])
        reason=row['reason']
        if (reason not in REASONS or type(row['impacted']) is not bool
            or row['impacted']!=REASONS[reason] or row['required'] is not True
            or row['case_id']!=case['id'] or row['criterion_id']!=case['criterion_id']
            or row['kind']!=case['kind'] or row['kind'] not in KIND_ORDER
            or row['assertion_digest']!=pp.digest(x)
            or row['path']!=target['path'] or row['path']!=x['module']+'.py'
            or row['module_sha256']!=target['module_sha256']):
            raise ValueError('Mandatory test identity mismatch')
        if row['impacted']:impacted.append(i)
    if type(m['impacted_count']) is not int or m['impacted_count']!=len(impacted):
        raise ValueError('Invalid impact count')
    first=sorted(impacted,key=lambda i:(KIND_ORDER[cases[i]['kind']],i))
    order=first+[i for i in range(n) if i not in set(impacted)]
    return dict(schema='orbit.regression-priority-schedule.v1',mapping_digest=expected_digest,
                comparison=comparison,source=source,required_count=n,impacted_count=len(impacted),
                execution_order=[cases[i]['id'] for i in order],
                full_regression_required=True,selective_execution_authorized=False,**FLAGS)

def current(c,db,pid,jid,source,cases,targets,comparison,expected_digest):
    return schedule(mapping.view(c,db,pid,jid),source,cases,targets,comparison,expected_digest)

def evidence(plan,attempted,report):
    order=plan['execution_order']
    if attempted!=order[:len(attempted)]:raise ValueError('Invalid attempted execution order')
    results={x['case_id']:x for x in report['results']}
    if len(results)!=len(order) or set(results)!=set(order) or report['source']!=plan['source']:
        raise ValueError('Incomplete prioritized result coverage')
    for ident in order[len(attempted):]:
        r=results[ident]
        if r['status']!='NOT_EXECUTED' or r['executed'] is not False or r['reason']!='TOTAL_TIMEOUT':
            raise ValueError('Missing mandatory execution result')
    if any(results[i]['status']=='NOT_EXECUTED' for i in attempted):
        raise ValueError('Unexpected unexecuted attempt')
    if report['gate']=='PASS' and (attempted!=order or not all(r['executed'] is True and r['status']=='PASS' for r in results.values())):
        raise ValueError('Incomplete execution cannot pass')
    return dict(schema='orbit.regression-priority-evidence.v1',schedule=plan,
                attempted_order=attempted,unattempted_order=order[len(attempted):],
                report_digest=pp.digest(report),gate=report['gate'],
                full_regression_required=True,selective_execution_authorized=False,**FLAGS)
