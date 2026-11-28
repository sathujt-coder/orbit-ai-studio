"""P6.5a: read-only, source-bound development security evidence, never authorization."""
import sqlite3
import acceptance_runner as runner
import engineering_assertion_registry as registry
import defect_retest_quality as retest
import project_planning as pp

FLAGS=dict(retest.FLAGS,security_release_authorized=False,security_gate_override=False)
CHECKS=('exact_source','durable_execution','sandbox_report','sandbox_command_policy','current_retest')
ASSESSMENTS=('threat_model','sast','dependency_vulnerabilities','secret_scan','dast','production_transport','malicious_candidate_resistance')
DIGESTS=('plan_digest','source_digest','assertion_contract_digest','selection_digest','sandbox_digest','candidate_digest')
ERRORS=(ValueError,KeyError,TypeError,AttributeError,IndexError,PermissionError,sqlite3.Error,OSError,SyntaxError,RecursionError)

def sandbox_policy(image):
    """Check the configured command template, not a runtime inspection or execution."""
    image=runner.vf.pinned_image(image)
    argv=runner.vf._docker_cmd(image,'/security-evidence-fixture',['python','-I','-B','-c','fixture'],'orbit-security-evidence')
    expected=['docker','run','--rm','--pull','never','--name','orbit-security-evidence',
        '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--pids-limit','64','--memory','256m','--cpus','1','--user','65534:65534',
        '--tmpfs','/tmp:rw,noexec,nosuid,size=32m',
        '--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONNOUSERSITE=1','--env','PYTHONPATH=/work','--env','TMPDIR=/tmp',
        '--mount','type=bind,src=/security-evidence-fixture,dst=/work,readonly','--workdir','/work',image,'python','-I','-B','-c','fixture']
    if argv!=expected:raise ValueError('Sandbox command policy mismatch')
    return pp.digest(argv)

def evaluate(pid,jid,source,receipt,gate):
    checks=dict.fromkeys(CHECKS,'BLOCK')
    out=dict(schema='orbit.security-evidence.v1',project_id=pid,job_id=jid,state='BLOCK',
        security_gate='BLOCK',scope='development_evidence_only',checks=checks,
        assessments=dict.fromkeys(ASSESSMENTS,'NOT_ASSESSED'),source=None,
        policy_digest=None,**FLAGS)
    try:
        if (source['project_id'],source['job_id'])!=(pid,jid) or not all(registry.hex_digest(source[k]) for k in DIGESTS):
            raise ValueError('Invalid security source')
        if source['selected'] not in ('A','B') or source['git']['source_sha256']!=source['candidate_digest']:
            raise ValueError('Candidate mismatch')
        if type(source['plan_version']) is not int or source['plan_version']<1:raise ValueError('Invalid plan version')
        checks['exact_source']='PASS'
        snap=receipt['snapshot'];report=snap['report']
        if (snap['schema']!='orbit.assertion-run-receipt.v1' or (snap['project_id'],snap['job_id'])!=(pid,jid)
            or receipt['digest']!=pp.digest(snap) or snap['report_digest']!=pp.digest(report)
            or report['source']!=source or any(snap.get(k) is not False or report.get(k) is not False for k in retest.FLAGS)
            or type(snap['version']) is not int or snap['version']<1):
            raise ValueError('Invalid durable execution')
        checks['durable_execution']='PASS'
        if report['schema']!='orbit.acceptance-runner-report.v1' or (report['runtime'],report['network'],report['workspace'])!=('docker','none','read-only'):
            raise ValueError('Untrusted sandbox report')
        image=runner.vf.pinned_image(report['image'])
        checks['sandbox_report']='PASS'
        out['policy_digest']=sandbox_policy(image)
        checks['sandbox_command_policy']='PASS'
        if ((gate['project_id'],gate['job_id'])!=(pid,jid) or gate['schema']!='orbit.defect-retest-quality.v1'
            or gate['evidence_digest']!=pp.digest({k:v for k,v in gate.items() if k!='evidence_digest'})
            or any(gate.get(k) is not False for k in retest.FLAGS)
            or gate['automatic_closure'] is not False or gate['quality_gate_override'] is not False
            or gate['execution_digest']!=receipt['digest'] or not registry.hex_digest(gate['regression_digest'])):
            raise ValueError('Invalid retest binding')
        out['source']=dict(**{k:source[k] for k in DIGESTS},plan_version=source['plan_version'],
            selected=source['selected'],execution_digest=receipt['digest'],execution_version=snap['version'],
            report_digest=snap['report_digest'],regression_digest=gate['regression_digest'],retest_digest=gate['evidence_digest'])
        if (gate['state']=='RETEST_QUALITY_PASS' and set(gate['checks'])==set(retest.CHECKS)
            and all(x=='PASS' for x in gate['checks'].values()) and report['gate']=='PASS'
            and type(report['case_count']) is int and report['case_count']>0
            and report['executed_count']==report['case_count']==len(report['results'])
            and all(x['executed'] is True and x['status']=='PASS' for x in report['results'])):
            checks['current_retest']='PASS'
        if all(x=='PASS' for x in checks.values()):out['state']='SECURITY_EVIDENCE_READY'
    except ERRORS:
        pass
    out['evidence_digest']=pp.digest(out)
    return out

def view(c,db,pid,jid):
    """Caller checks project read RBAC within the same transaction."""
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    try:
        source,_,_,_=runner.current(c,db,pid,jid)
        runs=registry.view(c,db,pid,jid)
        if runs['state'] not in ('EXECUTION_RECORDED_PASS','EXECUTION_RECORDED_BLOCK') or not runs['current_receipt']:
            raise ValueError('No current execution')
        return evaluate(pid,jid,source,runs['current_receipt'],retest.view(c,db,pid,jid))
    except ERRORS:
        return evaluate(pid,jid,{}, {}, {})
