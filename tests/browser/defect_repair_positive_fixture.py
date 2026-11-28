"""Isolated actual Docker timeout recovery, immutable repair receipts and SQLite writers."""
import concurrent.futures
from contextlib import closing
import json,os,sqlite3,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch

if os.environ.get('ORBIT_REQUIREMENTS_BROWSER_FIXTURE')!='1':
    raise SystemExit('Explicit isolated browser fixture required')
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'backend'),str(root/'tests')]
import isolated_workspace_snapshot as snapshots
import acceptance_runner as runner
import defect_repair_tracking as t
import engineering_impacted_tests as mapping
import regression_quality_gate as gate

def require(ok,message):
    if not ok:raise ValueError(message)

def connect(db):
    c=sqlite3.connect(db,timeout=90)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def capture(c,pid,jid):
    return {name:[dict(x) for x in c.execute(sql,(pid,jid))]
        for name,sql in {
        'runs':'SELECT * FROM engineering_assertion_runs WHERE project_id=? AND job_id=? ORDER BY version',
        'priority':'SELECT * FROM engineering_regression_priority_receipts WHERE project_id=? AND job_id=? ORDER BY version',
        'registry':'SELECT * FROM engineering_detected_defects WHERE project_id=? AND job_id=? ORDER BY finding_id,version',
        'repairs':'SELECT * FROM engineering_defect_repair_events WHERE project_id=? AND job_id=? ORDER BY finding_id,registration_digest,version',
        }.items()}

def read(db,pid,jid):
    with closing(connect(db)) as c:
        c.execute('BEGIN')
        return t.view(c,db,pid,jid)

def run(db,pid,jid,source,m,version,fail_case=None):
    # Only shorten the actual Docker transport deadline for one case in this
    # disposable test process. No fabricated reports, no production timeout change.
    real=runner.execute_case
    def fault(root,image,case,meta,timeout):
        return real(root,image,case,meta,0.001 if case['id']==fail_case else timeout)
    with closing(connect(db)) as c,patch.object(runner,'execute_case',side_effect=fault):
        runner.restrict_cli_database(c,persist=True,persist_priority=True)
        return runner.run(c,db,pid,jid,'ci-reviewer',source['plan_digest'],source['source_digest'],
            source['assertion_contract_digest'],source['sandbox_digest'],'RUN ACCEPTANCE ASSERTIONS '+jid,
            image=os.environ['ORBIT_SANDBOX_PYTHON_IMAGE'],expected_registry_version=version,
            priority_comparison='baseline_to_B',priority_mapping_digest=m['evidence_digest'])

def body(v,item,action,assignee=None):
    return dict(action=action,finding_id=item['finding_id'],registration_digest=item['registration_digest'],
        expected_digest=v['evidence_digest'],assignee=assignee,note='Controlled Docker execution recovery',
        confirmation=action+' DEFECT '+v['job_id']+' '+item['finding_id'])

def act(db,pid,jid,actor,b):
    with closing(connect(db)) as c:
        c.execute('BEGIN IMMEDIATE')
        try:
            r=t.record(c,db,pid,jid,actor,b,runner.vf.utc_now())
            c.commit()
            return r
        except Exception:
            c.rollback()
            raise

def count(db,pid,action):
    with closing(connect(db)) as c:
        return c.execute("SELECT count(*) FROM auth_audit WHERE project_id=? AND action=? AND outcome='allowed'",
            (pid,'engineering_defect_repair_'+action.lower())).fetchone()[0]

def race(db,pid,jid,actor,b):
    barrier=threading.Barrier(2)
    before=count(db,pid,b['action'])
    def writer():
        barrier.wait(timeout=10)
        try:return dict(status='accepted',receipt=act(db,pid,jid,actor,b))
        except ValueError as e:
            if str(e)!='Stale repair view or registry':raise
            return dict(status='stale')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(writer) for _ in range(2)]
        results=[x.result(timeout=120) for x in tasks]
    after=count(db,pid,b['action'])
    require(sorted(x['status'] for x in results)==['accepted','stale'] and after==before+1,'Concurrent writer or audit violation')
    return dict(action=b['action'],expected_digest=b['expected_digest'],results=results,audit_before=before,audit_after=after)

def item(v,rd):
    return next(x for x in v['items'] if x['registration_digest']==rd)

def main():
    live=Path(sys.argv[1]).resolve();pid,jid=sys.argv[2:4]
    with tempfile.TemporaryDirectory(prefix='orbit-defect-repair-positive-') as temp:
        db=Path(temp)/'isolated.sqlite'
        with closing(connect(live)) as c:
            before=snapshots.copy_project_snapshot(c,db,pid,lambda c,p:capture(c,p,jid))
        with closing(connect(db)) as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('BEGIN')
            source,cases,_,_=runner.current(c,db,pid,jid)
            m=mapping.view(c,db,pid,jid)
            initial=gate.view(c,db,pid,jid)
            version=len(t.runs.history(c,pid,jid))
            c.rollback()
            closer=c.execute("SELECT m.user_id FROM auth_memberships m JOIN auth_users u ON u.id=m.user_id WHERE m.project_id=? AND m.role='owner' AND u.active=1",(pid,)).fetchone()[0]
        require(initial['state']=='REGRESSION_QUALITY_PASS','Expected passing source fixture')
        fail_case=cases[0]['id']
        failed=run(db,pid,jid,source,m,version,fail_case)
        errors=[x for x in failed['report']['results'] if x['status']!='PASS']
        require(failed['report']['gate']=='BLOCK' and len(errors)==1 and errors[0]['case_id']==fail_case
            and errors[0]['status']=='ERROR' and errors[0]['reason']=='TIMEOUT','Expected one real Docker timeout')
        with closing(connect(db)) as c:
            c.execute('BEGIN IMMEDIATE')
            d,s=t.registry.current(c,db,pid,jid)
            require(len(d['findings'])==1 and d['findings'][0]['kind']=='EXECUTION_ERROR','Expected execution defect')
            rd=t.registry.register(c,db,pid,jid,'ci-reviewer',s['evidence_digest'],'REGISTER DETECTED DEFECTS '+jid)[0]
            c.commit()
        opened=read(db,pid,jid); original=item(opened,rd)
        assign=race(db,pid,jid,'ci-reviewer',body(opened,original,'ASSIGN','ci-developer'))
        assigned=read(db,pid,jid)
        act(db,pid,jid,'ci-developer',body(assigned,item(assigned,rd),'START'))
        started=read(db,pid,jid)
        recovered=run(db,pid,jid,source,m,version+1)
        require(recovered['report']['gate']=='PASS' and recovered['report']['source']==failed['report']['source']
            and all(x['status']=='PASS' for x in recovered['report']['results']),'Same assertion recovery failed')
        after=read(db,pid,jid)
        require(after['items']==started['items'] and after['registry_state']=='NO_CURRENT_FINDINGS','Recovery modified repair history')
        submit=race(db,pid,jid,'ci-developer',body(after,item(after,rd),'SUBMIT'))
        submitted=read(db,pid,jid)
        act(db,pid,jid,'ci-reviewer',body(submitted,item(submitted,rd),'VERIFY'))
        verified=read(db,pid,jid)
        try:act(db,pid,jid,'ci-reviewer',body(verified,item(verified,rd),'CLOSE'))
        except PermissionError:pass
        else:raise ValueError('Same reviewer closed defect')
        close=race(db,pid,jid,closer,body(verified,item(verified,rd),'CLOSE'))
        closed=read(db,pid,jid)
        require(item(closed,rd)['state']=='CLOSED','Explicit closure failed')
        with closing(connect(db)) as c:
            c.execute('BEGIN')
            final_gate=gate.view(c,db,pid,jid)
            registry=t.registry.history(c,pid,jid)
            c.rollback()
        with closing(connect(live)) as c:
            require(snapshots.capture(c,pid,lambda c,p:capture(c,p,jid))==before,'Live evidence modified')
        print(json.dumps(dict(schema='orbit.defect-repair-positive-browser.v1',source_commit=os.environ['GITHUB_SHA'],
            run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'],registration_digest=rd,
            opened=opened,assigned=assigned,started=started,recovered_view=after,submitted=submitted,
            verified=verified,closed=closed,failed_run=failed,recovered_run=recovered,final_gate=final_gate,
            registration=next(x for chain in registry.values() for x in chain if x['digest']==rd),
            races=[assign,submit,close],same_reviewer_rejected=True,live_unchanged=True),sort_keys=True))
if __name__=='__main__':main()
