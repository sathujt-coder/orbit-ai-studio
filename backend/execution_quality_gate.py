"""P6.4c.4: conjunctive, read-only execution quality gate.

Legacy QC remains unchanged. This gate requires BOTH legacy QC and current,
complete durable execution receipts. No execution, approval or release authority.
"""
import sqlite3
import engineering_qc as qc
import engineering_test_plan as tp
import engineering_assertion_registry as registry
import project_planning as pp

FLAGS=qc.FLAGS
CHECKS=('legacy_qc','test_plan','execution_receipt','exact_execution_coverage','cross_binding')

def valid_digest(value):
    return registry.hex_digest(value)

def evaluate(pid,jid,q,p,r):
    out=dict(schema='orbit.execution-quality-gate.v1',project_id=pid,job_id=jid,
             state='BLOCK',checks={k:'BLOCK' for k in CHECKS},receipts={},
             coverage=None,selected=None,findings=[],scope='development_evidence_only',**FLAGS)
    checks=out['checks'];receipts=out['receipts']
    try:
        if any(v['project_id']!=pid or v['job_id']!=jid or any(v.get(k) is not False for k in FLAGS) for v in (q,p,r)):
            raise ValueError('Evidence scope or authority mismatch')
        if (q['state']=='QA_QC_EVIDENCE_PASS' and set(q['checks'])==set(qc.CHECKS)
            and all(x=='PASS' for x in q['checks'].values()) and not q['findings']
            and valid_digest(q['evidence_digest'])
            and q['evidence_digest']==pp.digest({k:v for k,v in q.items() if k!='evidence_digest'})):
            checks['legacy_qc']='PASS';receipts['legacy_qc']=q['evidence_digest']
        if (p['state']=='TEST_PLAN_COVERAGE_PASS' and p['assertion_status']=='ASSERTION_CONTRACT_READY'
            and type(p['latest_version']) is int and p['latest_version']>0
            and len(p['history'])==p['latest_version']):
            plan=p['history'][-1];e=plan['snapshot']
            cases,cov=tp.coverage(e['source'],e['cases'],tp.V2)
            if (e['schema']==tp.V2 and e['version']==p['latest_version']
                and e['project_id']==pid and e['job_id']==jid
                and plan['digest']==pp.digest(e)
                and p['source_digest']==e['source_digest']==pp.digest(e['source'])
                and p['assertion_contract_digest']==e['assertion_contract_digest']==tp.contract_digest(e)
                and cases==e['cases'] and cov==e['coverage'] and cov['complete']
                and all(e[k] is False for k in FLAGS)):
                checks['test_plan']='PASS';receipts['test_plan']=plan['digest']
                receipts['assertion_contract']=e['assertion_contract_digest']
        if (r['state']=='EXECUTION_RECORDED_PASS' and type(r['latest_version']) is int and r['latest_version']>0
            and len(r['history'])==r['latest_version'] and r['current_receipt']==r['history'][-1]):
            receipt=r['current_receipt'];s=receipt['snapshot'];report=s['report'];src=report['source']
            if (s['schema']=='orbit.assertion-run-receipt.v1' and s['project_id']==pid and s['job_id']==jid
                and s['version']==r['latest_version'] and receipt['digest']==pp.digest(s)
                and s['report_digest']==pp.digest(report)
                and s['previous_digest']==(r['history'][-2]['digest'] if len(r['history'])>1 else None)
                and all(s[k] is False for k in FLAGS)):
                checks['execution_receipt']='PASS';receipts['execution']=receipt['digest']
                receipts['runner_report']=s['report_digest']
                if checks['test_plan']=='PASS':
                    summary=registry.validate_report(report,src,cases)
                    out['coverage']=summary
                    if (summary==s['summary'] and summary['gate']=='PASS'
                        and summary['case_count']==summary['executed_count']==summary['pass_count']>0):
                        checks['exact_execution_coverage']='PASS'
                if all(checks[k]=='PASS' for k in CHECKS if k!='cross_binding'):
                    lane=src['selected'];binding=q['binding'];qr=q['receipts']
                    if (lane in ('A','B') and lane==q['selected']
                        and src['project_id']==pid and src['job_id']==jid
                        and src['plan_version']==e['version'] and src['plan_digest']==plan['digest']
                        and src['source_digest']==e['source_digest']
                        and src['assertion_contract_digest']==e['assertion_contract_digest']
                        and src['selection_digest']==qr['candidate_selection']
                        and src['sandbox_digest']==qr['sandbox']
                        and src['candidate_digest']==src['git']['source_sha256']==e['source']['candidates'][lane]['digest']
                        and all(e['source'][k]==binding[k] for k in ('adoption_version','package_id','binding_digest','spec_digest'))):
                        checks['cross_binding']='PASS';out['selected']=lane
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError,sqlite3.Error,OSError,SyntaxError):
        pass
    out['findings']=[dict(code=k.upper()+'_NOT_CURRENT',check=k) for k in CHECKS if checks[k]!='PASS']
    if not out['findings']:out['state']='EXECUTION_QUALITY_PASS'
    out['evidence_digest']=pp.digest(out)
    return out

def view(c,db,pid,jid):
    # Caller owns a single consistent read transaction. All underlying views
    # revalidate current source and registry history, including exact Git targets.
    try:
        return evaluate(pid,jid,qc.view(c,db,pid,jid),tp.view(c,pid,jid),registry.view(c,db,pid,jid))
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError,sqlite3.Error,OSError,SyntaxError):
        return evaluate(pid,jid,{}, {}, {})

def require_current(c,db,pid,jid,expected_digest):
    """For downstream development workflow transitions; no automatic transition."""
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    v=view(c,db,pid,jid)
    if v['state']!='EXECUTION_QUALITY_PASS' or v['evidence_digest']!=expected_digest:
        raise ValueError('Current execution quality gate required')
    return v
