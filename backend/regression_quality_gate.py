"""P6.4d.5: durable priority receipt and conjunctive regression quality gate.

A sidecar is written only by the explicitly persisted trusted runner, in the
same transaction as the assertion receipt. Existing receipts are not rewritten.
"""
import json
import sqlite3
import acceptance_runner as runner
import engineering_assertion_registry as registry
import execution_quality_gate as execution
import engineering_impacted_tests as mapping
import regression_priority as priority
import project_planning as pp
import product_requirements as pr

FLAGS=priority.FLAGS
CHECKS=('execution_quality','current_mapping','durable_priority_receipt','mandatory_regression')

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_regression_priority_receipts(
        project_id TEXT NOT NULL,job_id TEXT NOT NULL,version INTEGER NOT NULL CHECK(version>0),
        snapshot TEXT NOT NULL,digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,version),
        FOREIGN KEY(project_id,job_id,version) REFERENCES engineering_assertion_runs(project_id,job_id,version))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS engineering_regression_priority_no_{op.lower()}
            BEFORE {op} ON engineering_regression_priority_receipts
            BEGIN SELECT RAISE(ABORT,'Immutable regression priority receipt'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS engineering_regression_priority_no_replace
        BEFORE INSERT ON engineering_regression_priority_receipts WHEN EXISTS(
        SELECT 1 FROM engineering_regression_priority_receipts WHERE project_id=NEW.project_id
        AND job_id=NEW.job_id AND version=NEW.version)
        BEGIN SELECT RAISE(ABORT,'Duplicate regression priority receipt'); END""")

def make_receipt(pid,jid,receipt,trace,schedule,cases,targets,stamp):
    r=receipt['snapshot'];report=r['report']
    pr.fields(receipt,('digest','snapshot'))
    if (r['schema']!='orbit.assertion-run-receipt.v1' or r['project_id']!=pid or r['job_id']!=jid
        or type(r['version']) is not int or r['version']<1 or receipt['digest']!=pp.digest(r)
        or r['report_digest']!=pp.digest(report) or any(r.get(k) is not False for k in FLAGS)
        or report['source']['project_id']!=pid or report['source']['job_id']!=jid):
        raise ValueError('Invalid execution receipt binding')
    if registry.validate_report(report,schedule['source'],cases,targets)!=r['summary']:
        raise ValueError('Invalid execution receipt summary')
    if trace!=priority.evidence(schedule,trace['attempted_order'],report):
        raise ValueError('Invalid priority trace')
    e=dict(schema='orbit.regression-priority-receipt.v1',project_id=pid,job_id=jid,
           execution_version=r['version'],execution_receipt_digest=receipt['digest'],
           report_digest=r['report_digest'],priority=trace,priority_digest=pp.digest(trace),
           created_at=stamp,**FLAGS)
    return dict(digest=pp.digest(e),snapshot=e)

def append(c,pid,jid,receipt,trace,schedule,cases,targets,stamp):
    if not c.in_transaction:raise ValueError('Priority receipt transaction required')
    e=make_receipt(pid,jid,receipt,trace,schedule,cases,targets,stamp);s=e['snapshot']
    row=c.execute('SELECT snapshot,digest FROM engineering_assertion_runs WHERE project_id=? AND job_id=? AND version=?',
                  (pid,jid,s['execution_version'])).fetchone()
    if not row or row['digest']!=receipt['digest'] or json.loads(row['snapshot'])!=receipt['snapshot']:
        raise ValueError('Exact persisted execution receipt required')
    c.execute('INSERT INTO engineering_regression_priority_receipts VALUES(?,?,?,?,?)',
              (pid,jid,s['execution_version'],pr.canonical(s),e['digest']))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
              (receipt['snapshot']['report']['actor'],pid,'engineering_regression_priority_record','allowed'))
    return e

def load(c,pid,jid,version):
    row=c.execute('SELECT snapshot,digest FROM engineering_regression_priority_receipts WHERE project_id=? AND job_id=? AND version=?',
                  (pid,jid,version)).fetchone()
    return dict(digest=row['digest'],snapshot=json.loads(row['snapshot'])) if row else None

def evaluate(pid,jid,q,r,m,source,cases,targets,receipt):
    out=dict(schema='orbit.regression-quality-gate.v1',project_id=pid,job_id=jid,state='BLOCK',
             checks={k:'BLOCK' for k in CHECKS},receipts={},priority_receipt=None,coverage=None,
             full_regression_required=True,selective_execution_authorized=False,
             scope='development_evidence_only',**FLAGS)
    checks=out['checks'];bindings=out['receipts']
    try:
        if (q['project_id']==pid and q['job_id']==jid and q['state']=='EXECUTION_QUALITY_PASS'
            and set(q['checks'])==set(execution.CHECKS) and all(x=='PASS' for x in q['checks'].values())
            and not q['findings'] and mapping.digest_ok(q) and all(q.get(k) is False for k in FLAGS)):
            checks['execution_quality']='PASS';bindings['execution_quality']=q['evidence_digest']
        if source is None:raise ValueError('Current executable source required')
        if source['project_id']!=pid or source['job_id']!=jid:raise ValueError('Wrong scope')
        # Validate the selected baseline schedule even when no durable priority receipt exists.
        baseline=priority.schedule(m,source,cases,targets,m['selected_comparison'],m['evidence_digest'])
        checks['current_mapping']='PASS';bindings['mapping']=baseline['mapping_digest']
        if (r['project_id']!=pid or r['job_id']!=jid or any(r.get(k) is not False for k in FLAGS)
            or r['state'] not in ('EXECUTION_RECORDED_PASS','EXECUTION_RECORDED_BLOCK')
            or not r['history'] or r['latest_version']!=len(r['history'])
            or r['current_receipt']!=r['history'][-1] or receipt is None):
            raise ValueError('Current durable priority execution required')
        run=r['current_receipt'];s=run['snapshot'];trace=receipt['snapshot']['priority']
        if s['version']!=r['latest_version']:raise ValueError('Execution version mismatch')
        schedule=priority.schedule(m,source,cases,targets,trace['schedule']['comparison'],m['evidence_digest'])
        expected=make_receipt(pid,jid,run,trace,schedule,cases,targets,receipt['snapshot']['created_at'])
        if receipt!=expected:raise ValueError('Priority receipt digest or binding mismatch')
        checks['durable_priority_receipt']='PASS';bindings.update(execution=run['digest'],priority=receipt['digest'],
                                                                  report=s['report_digest'])
        out['priority_receipt']=receipt
        summary=s['summary'];out['coverage']=summary
        if (r['state']=='EXECUTION_RECORDED_PASS' and summary['gate']=='PASS'
            and summary['case_count']==summary['executed_count']==summary['pass_count']==schedule['required_count']>0
            and trace['attempted_order']==schedule['execution_order'] and trace['unattempted_order']==[]
            and q['receipts'].get('execution')==run['digest']
            and q['receipts'].get('runner_report')==s['report_digest']
            and q['coverage']==summary and q['selected']==source['selected']):
            checks['mandatory_regression']='PASS'
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,PermissionError,sqlite3.Error,OSError,SyntaxError,RecursionError):
        pass
    out['findings']=[dict(check=k,code=k.upper()+'_NOT_CURRENT') for k in CHECKS if checks[k]!='PASS']
    if not out['findings']:out['state']='REGRESSION_QUALITY_PASS'
    out['evidence_digest']=pp.digest(out)
    return out

def view(c,db,pid,jid):
    q=execution.view(c,db,pid,jid)
    try:
        m=mapping.view(c,db,pid,jid)
        r=registry.view(c,db,pid,jid)
        source,cases,_,targets=runner.current(c,db,pid,jid)
        receipt=load(c,pid,jid,r['latest_version']) if r['current_receipt'] else None
        return evaluate(pid,jid,q,r,m,source,cases,targets,receipt)
    except (ValueError,KeyError,TypeError,AttributeError,IndexError,PermissionError,sqlite3.Error,OSError,SyntaxError,RecursionError):
        return evaluate(pid,jid,q,{}, {},None,[],[],None)

def require_current(c,db,pid,jid,expected_digest):
    if not c.in_transaction:raise ValueError('Consistent transaction required')
    v=view(c,db,pid,jid)
    if v['state']!='REGRESSION_QUALITY_PASS' or v['evidence_digest']!=expected_digest:
        raise ValueError('Current regression quality gate required')
    return v
