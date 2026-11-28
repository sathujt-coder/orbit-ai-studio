"""Append-only results from trusted local assertion execution, never HTTP ingestion."""
import json
import sqlite3
import re
import acceptance_runner as runner
import acceptance_assertion as ac
import engineering_test_plan as tp
import project_planning as pp
import product_requirements as pr

FLAGS=runner.FLAGS
HEX=re.compile(r'[0-9a-f]{64}\Z')
ERRORS={'TIMEOUT','OUTPUT_LIMIT','DOCKER_OR_PROCESS_ERROR','DOCKER_UNAVAILABLE',
        'MISSING_OBSERVATION','MODULE_OR_TARGET_ERROR','ABNORMAL_EXIT','INVALID_RESULT','INVALID_OBSERVATION'}

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_assertion_runs(
        project_id TEXT NOT NULL REFERENCES projects(id),
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        version INTEGER NOT NULL CHECK(version>0),snapshot TEXT NOT NULL,digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,version))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS engineering_assertion_run_no_{op.lower()}
            BEFORE {op} ON engineering_assertion_runs
            BEGIN SELECT RAISE(ABORT,'Immutable assertion run'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS engineering_assertion_run_no_replace
        BEFORE INSERT ON engineering_assertion_runs WHEN EXISTS(SELECT 1 FROM engineering_assertion_runs
        WHERE project_id=NEW.project_id AND job_id=NEW.job_id AND version=NEW.version)
        BEGIN SELECT RAISE(ABORT,'Duplicate assertion run'); END""")

def hex_digest(value):
    return isinstance(value,str) and HEX.fullmatch(value) is not None

def validate_report(report,source,cases,targets=None):
    pr.fields(report,('schema','source','actor','image','runtime','network','workspace','results',
                      'executed_count','case_count','gate','persisted',*FLAGS))
    if (report['schema']!='orbit.acceptance-runner-report.v1' or report['source']!=source
        or report['runtime']!='docker' or report['network']!='none' or report['workspace']!='read-only'
        or report['persisted'] is not False or any(report[k] is not False for k in FLAGS)
        or not isinstance(report['actor'],str) or not report['actor']):
        raise ValueError('Invalid runner provenance')
    runner.vf.pinned_image(report['image'])
    if not isinstance(report['results'],list) or not cases or len(report['results'])!=len(cases):
        raise ValueError('Incomplete execution coverage')
    if targets is not None and len(targets)!=len(cases):raise ValueError('Incomplete target binding')
    executed=0;passes=0;seen=set()
    for i,(case,result) in enumerate(zip(cases,report['results'])):
        x=ac.validate(case['execution']);a=x['assertion']
        common=('case_id','criterion_id','kind','assertion_digest','path','module_sha256','status','executed','reason')
        if not isinstance(result,dict):raise ValueError('Invalid case result')
        if (result.get('case_id'),result.get('criterion_id'),result.get('kind'))!=(case['id'],case['criterion_id'],case['kind']):
            raise ValueError('Case identity mismatch')
        if case['id'] in seen:raise ValueError('Duplicate case')
        seen.add(case['id'])
        if (result.get('assertion_digest')!=pp.digest(x) or result.get('path')!=x['module']+'.py'
            or not hex_digest(result.get('module_sha256'))):
            raise ValueError('Assertion or module binding mismatch')
        if targets is not None and {k:result[k] for k in ('path','module_sha256')}!=targets[i]:
            raise ValueError('Exact Git module mismatch')
        status=result['status']
        if status in ('PASS','FAIL'):
            if result['executed'] is not True:raise ValueError('Unexecuted assertion verdict')
            executed+=1
            if result.get('observation')=='returned':
                pr.fields(result,common+('observation','value_digest'))
                if not hex_digest(result['value_digest']):raise ValueError('Invalid value digest')
                match=a['operator']=='equals' and result['value_digest']==pp.digest(a['value'])
            elif result.get('observation')=='raised':
                pr.fields(result,common+('observation','exception'))
                if result['exception'] not in ac.EXCEPTIONS+('OTHER',):raise ValueError('Invalid exception')
                match=a['operator']=='raises' and result['exception']==a['exception']
            else:raise ValueError('Missing observation')
            if status!=('PASS' if match else 'FAIL') or result['reason']!=('ASSERTION_MATCH' if match else 'ASSERTION_MISMATCH'):
                raise ValueError('False assertion verdict')
            passes+=int(match)
        else:
            pr.fields(result,common)
            if result['executed'] is not False or not (
                (status=='ERROR' and result['reason'] in ERRORS) or
                (status=='NOT_EXECUTED' and result['reason']=='TOTAL_TIMEOUT')):
                raise ValueError('Invalid non-executed result')
    gate='PASS' if passes==len(cases) else 'BLOCK'
    if (type(report['case_count']) is not int or report['case_count']!=len(cases)
        or type(report['executed_count']) is not int or report['executed_count']!=executed or report['gate']!=gate):
        raise ValueError('Invalid execution summary')
    return dict(case_count=len(cases),executed_count=executed,pass_count=passes,gate=gate)

def history(c,pid,jid):
    plans=tp.history(c,pid,jid)
    result=[]
    for row in c.execute('SELECT * FROM engineering_assertion_runs WHERE project_id=? AND job_id=? ORDER BY version',(pid,jid)):
        e=json.loads(row['snapshot'])
        pr.fields(e,('schema','project_id','job_id','version','previous_digest','report','report_digest','summary','created_at',*FLAGS))
        if (e['schema']!='orbit.assertion-run-receipt.v1' or e['project_id']!=pid or e['job_id']!=jid
            or type(e['version']) is not int or e['version']!=row['version'] or e['version']!=len(result)+1
            or e['previous_digest']!=(result[-1]['digest'] if result else None)
            or pp.digest(e)!=row['digest'] or any(e[k] is not False for k in FLAGS)):
            raise ValueError('Invalid execution receipt chain')
        report=e['report'];src=report['source']
        if e['report_digest']!=pp.digest(report):raise ValueError('Runner report digest mismatch')
        version=src['plan_version']
        if type(version) is not int or not 1<=version<=len(plans):raise ValueError('Unknown plan version')
        plan=plans[version-1];p=plan['snapshot']
        if (p['schema']!=tp.V2 or src['project_id']!=pid or src['job_id']!=jid
            or src['plan_digest']!=plan['digest'] or src['source_digest']!=p['source_digest']
            or src['assertion_contract_digest']!=p['assertion_contract_digest']
            or src['selected'] not in ('A','B')
            or src['candidate_digest']!=p['source']['candidates'][src['selected']]['digest']
            or src['git']['source_sha256']!=src['candidate_digest']):
            raise ValueError('Historical plan or candidate mismatch')
        if e['summary']!=validate_report(report,src,p['cases']):raise ValueError('Invalid receipt summary')
        result.append(dict(digest=row['digest'],snapshot=e))
    return result

def check_version(c,pid,jid,expected):
    chain=history(c,pid,jid)
    if type(expected) is not int or expected!=len(chain):raise ValueError('Stale execution registry version')
    return chain

def append(c,pid,jid,expected,report,source,cases,targets,stamp):
    # Internal call only, inside runner's fresh post-execution transaction.
    if not c.in_transaction:raise ValueError('Execution receipt transaction required')
    chain=check_version(c,pid,jid,expected)
    summary=validate_report(report,source,cases,targets)
    e=dict(schema='orbit.assertion-run-receipt.v1',project_id=pid,job_id=jid,
           version=expected+1,previous_digest=chain[-1]['digest'] if chain else None,
           report=report,report_digest=pp.digest(report),summary=summary,created_at=stamp,**FLAGS)
    digest=pp.digest(e)
    c.execute('INSERT INTO engineering_assertion_runs VALUES(?,?,?,?,?)',(pid,jid,e['version'],pr.canonical(e),digest))
    c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
              (report['actor'],pid,'engineering_assertion_run_record','allowed'))
    return dict(digest=digest,snapshot=e)

def view(c,db,pid,jid):
    out=dict(schema='orbit.assertion-run-registry.v1',project_id=pid,job_id=jid,state='BLOCK',
             latest_version=0,history=[],current_receipt=None,**FLAGS)
    try:
        chain=history(c,pid,jid)
        out.update(history=chain,latest_version=len(chain),state='STALE' if chain else 'BLOCK')
        src,cases,_,targets=runner.current(c,db,pid,jid)
        if not chain:out['state']='AWAITING_EXECUTION'
        elif chain[-1]['snapshot']['report']['source']==src:
            receipt=chain[-1]
            summary=validate_report(receipt['snapshot']['report'],src,cases,targets)
            out.update(state='EXECUTION_RECORDED_PASS' if summary['gate']=='PASS' else 'EXECUTION_RECORDED_BLOCK',
                       current_receipt=receipt)
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError,sqlite3.Error,OSError,SyntaxError):
        pass
    return out
