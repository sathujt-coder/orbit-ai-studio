"""Immutable acceptance test plans. Coverage is planning coverage, not test success."""
import json
import re
import sqlite3
import studio_verification as qa
import engineering_quality as quality
import project_planning as pp
import product_requirements as pr
import engineering_sandbox as sb
import acceptance_assertion as assertion

FLAGS=sb.FLAGS
KINDS=('POSITIVE','NEGATIVE','BOUNDARY')
ID=re.compile(r'[A-Za-z0-9_-]{1,100}\Z')
MAX_CASES=300
V1='orbit.acceptance-test-plan.v1'
V2='orbit.acceptance-test-plan.v2'

def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_test_plans(
        project_id TEXT NOT NULL REFERENCES projects(id),
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        version INTEGER NOT NULL CHECK(version>0),snapshot TEXT NOT NULL,digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,version))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS engineering_test_plan_no_{op.lower()}
            BEFORE {op} ON engineering_test_plans
            BEGIN SELECT RAISE(ABORT,'Immutable test plan'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS engineering_test_plan_no_replace
        BEFORE INSERT ON engineering_test_plans WHEN EXISTS(SELECT 1 FROM engineering_test_plans
        WHERE project_id=NEW.project_id AND job_id=NEW.job_id AND version=NEW.version)
        BEGIN SELECT RAISE(ABORT,'Duplicate test plan'); END""")

def source(c,pid,jid):
    if not isinstance(jid,str) or not ID.fullmatch(jid):raise ValueError('Invalid job')
    quality.lineage(c,pid,jid)
    src=qa.source(c,pid,jid)
    if src['project_id']!=pid or src['job_id']!=jid:raise ValueError('Source scope mismatch')
    criterion_ids(src)
    return src

def criterion_ids(src):
    ids=[x['id'] for x in src['acceptance']]
    if not ids or len(set(ids))!=len(ids) or len(ids)*len(KINDS)>MAX_CASES:
        raise ValueError('Invalid or excessive acceptance criteria')
    return ids

def field(value,minimum,maximum):
    if not isinstance(value,str) or not minimum<=len(value.strip())<=maximum or '\x00' in value:
        raise ValueError('Invalid test description')
    return value.strip()

def coverage(src,cases,schema=V1):
    if schema not in (V1,V2):raise ValueError('Unsupported test plan schema')
    ids=criterion_ids(src)
    if not isinstance(cases,list) or not 1<=len(cases)<=MAX_CASES:raise ValueError('Invalid test case count')
    seen=set(); matrix={k:{kind:[] for kind in KINDS} for k in ids};normalized=[]
    for item in cases:
        pr.fields(item,('id','criterion_id','kind','scenario','expected')+(('execution',) if schema==V2 else ()))
        ident=item['id'];criterion=item['criterion_id'];kind=item['kind']
        if not isinstance(ident,str) or not ID.fullmatch(ident) or ident in seen:
            raise ValueError('Duplicate or invalid test ID')
        if not isinstance(criterion,str) or criterion not in matrix or kind not in KINDS:
            raise ValueError('Unknown criterion or test kind')
        seen.add(ident)
        normalized.append(dict(id=ident,criterion_id=criterion,kind=kind,
                               scenario=field(item['scenario'],10,1000),expected=field(item['expected'],10,1000)))
        if schema==V2:normalized[-1]['execution']=assertion.validate(item['execution'])
        matrix[criterion][kind].append(ident)
    missing=[dict(criterion_id=k,kind=t) for k in ids for t in KINDS if not matrix[k][t]]
    return normalized,dict(matrix=matrix,missing=missing,criteria_total=len(ids),
                           criteria_covered=sum(all(matrix[k][t] for t in KINDS) for k in ids),
                           cases_total=len(cases),complete=not missing)

def template(src):
    # Deterministic placeholders, never accepted as executable test evidence.
    return [dict(id='TC-%03d-%s'%(i+1,kind),criterion_id=k,kind=kind,
                 scenario='',expected='') for i,k in enumerate(criterion_ids(src)) for kind in KINDS]

def contract_digest(e):
    if e['schema']!=V2:raise ValueError('Executable assertion contract required')
    return pp.digest(dict(schema=assertion.SCHEMA,source_digest=e['source_digest'],
        cases=[{k:x[k] for k in ('id','criterion_id','kind','execution')} for x in e['cases']]))


def history(c,pid,jid):
    result=[]
    for row in c.execute('SELECT * FROM engineering_test_plans WHERE project_id=? AND job_id=? ORDER BY version',(pid,jid)):
        e=json.loads(row['snapshot'])
        if (pp.digest(e)!=row['digest'] or e['schema'] not in (V1,V2)
            or e['project_id']!=pid or e['job_id']!=jid or e['version']!=len(result)+1
            or e['version']!=row['version'] or e['previous_digest']!=(result[-1]['digest'] if result else None)
            or e['source']['project_id']!=pid or e['source']['job_id']!=jid
            or e['source_digest']!=pp.digest(e['source']) or any(e[k] is not False for k in FLAGS)):
            raise ValueError('Invalid test plan history')
        if result and result[-1]['snapshot']['schema']==V2 and e['schema']!=V2:
            raise ValueError('Executable plan downgrade')
        cases,cov=coverage(e['source'],e['cases'],e['schema'])
        if e['schema']==V2 and e['assertion_contract_digest']!=contract_digest(e):
            raise ValueError('Invalid assertion contract digest')
        if e['schema']==V1 and 'assertion_contract_digest' in e:
            raise ValueError('Legacy plan cannot claim assertion contract')
        if cases!=e['cases'] or cov!=e['coverage'] or not cov['complete']:
            raise ValueError('Invalid historical coverage')
        result.append(dict(digest=row['digest'],snapshot=e))
    return result

def record(c,pid,jid,actor,body,stamp):
    pr.fields(body,('source_digest','expected_version','cases','confirmation'))
    if body['confirmation']!='CONFIRM ACCEPTANCE TEST PLAN '+jid:
        raise ValueError('Explicit plan confirmation required')
    c.execute('SAVEPOINT acceptance_test_plan')
    try:
        pp.check_role(c,pid,actor,'approve')
        src=source(c,pid,jid)
        if body['source_digest']!=pp.digest(src):raise ValueError('Stale test plan source')
        chain=history(c,pid,jid)
        if type(body['expected_version']) is not int or body['expected_version']!=len(chain):
            raise ValueError('Stale test plan version')
        raw=body['cases']
        schema=V2 if isinstance(raw,list) and any(isinstance(x,dict) and 'execution' in x for x in raw) else V1
        if chain and chain[-1]['snapshot']['schema']==V2 and schema!=V2:
            raise ValueError('Executable plan downgrade')
        cases,cov=coverage(src,raw,schema)
        if not cov['complete']:raise ValueError('Incomplete criterion/type coverage')
        e=dict(schema=schema,project_id=pid,job_id=jid,
               version=len(chain)+1,previous_digest=chain[-1]['digest'] if chain else None,
               source=src,source_digest=pp.digest(src),cases=cases,coverage=cov,
               actor=actor,created_at=stamp,**FLAGS)
        if schema==V2:e['assertion_contract_digest']=contract_digest(e)
        digest=pp.digest(e)
        c.execute('INSERT INTO engineering_test_plans VALUES(?,?,?,?,?)',(pid,jid,e['version'],pr.canonical(e),digest))
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                  (actor,pid,'engineering_test_plan_confirm','allowed'))
        c.execute('RELEASE acceptance_test_plan')
    except Exception:
        c.execute('ROLLBACK TO acceptance_test_plan');c.execute('RELEASE acceptance_test_plan');raise
    return dict(version=e['version'],digest=digest,**FLAGS)

def view(c,pid,jid):
    out=dict(schema='orbit.acceptance-test-registry.v1',project_id=pid,job_id=jid,state='BLOCK',
             source_digest=None,criteria=[],template=[],history=[],latest_version=0,
             execution_status='NOT_EXECUTED',assertion_status='NOT_READY',assertion_contract_digest=None,**FLAGS)
    try:
        chain=history(c,pid,jid)
        out.update(history=chain,latest_version=len(chain),state='STALE' if chain else 'BLOCK')
        src=source(c,pid,jid)
        out.update(source_digest=pp.digest(src),criteria=src['acceptance'],template=template(src))
        if not chain:out['state']='AWAITING_TEST_PLAN'
        elif chain[-1]['snapshot']['source']==src:
            out['state']='TEST_PLAN_COVERAGE_PASS'
            e=chain[-1]['snapshot']
            if e['schema']==V2:
                out.update(assertion_status='ASSERTION_CONTRACT_READY',assertion_contract_digest=e['assertion_contract_digest'])
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError,sqlite3.Error,OSError):
        pass
    return out
