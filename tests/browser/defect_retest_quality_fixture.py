"""Real Docker, append-only recurrence/reopen/retest fixture on isolated DB."""
from defect_repair_positive_fixture import (closing, connect, capture, snapshots, runner,
    t, mapping, gate, require, run, body, act, race, item, read, count, Path, sys, os,
    tempfile, json)
import defect_retest_quality as q

def point(db,pid,jid):
    with closing(connect(db)) as c:
        c.execute('BEGIN')
        tracking,detection=t._snapshot(c,db,pid,jid)
        regression=gate.view(c,db,pid,jid)
        registrations=t.registry.history(c,pid,jid)
        receipt=t.runs.history(c,pid,jid)[-1]
        return dict(tracking=tracking,detection=detection,regression=regression,
                    registrations=registrations,receipt=receipt,gate=q.view(c,db,pid,jid))

def register(db,pid,jid):
    with closing(connect(db)) as c:
        c.execute('BEGIN IMMEDIATE')
        d,s=t.registry.current(c,db,pid,jid)
        require(len(d['findings'])==1 and d['findings'][0]['kind']=='EXECUTION_ERROR','Expected single timeout defect')
        rd=t.registry.register(c,db,pid,jid,'ci-reviewer',s['evidence_digest'],'REGISTER DETECTED DEFECTS '+jid)[0]
        c.commit()
        return rd

def command(db,pid,jid,rd,action,actor,assignee=None):
    v=read(db,pid,jid)
    return act(db,pid,jid,actor,body(v,item(v,rd),action,assignee))

def rejected(fn,error,message):
    try:fn()
    except error as e:
        require(message in str(e),'Unexpected rejection: '+str(e))
    else:raise ValueError('Expected rejection: '+message)

def finish(db,pid,jid,rd,closer):
    command(db,pid,jid,rd,'SUBMIT','ci-developer')
    command(db,pid,jid,rd,'VERIFY','ci-reviewer')
    rejected(lambda:command(db,pid,jid,rd,'CLOSE','ci-reviewer'),PermissionError,'Independent closure reviewer')
    command(db,pid,jid,rd,'CLOSE',closer)

def main():
    live=Path(sys.argv[1]).resolve();pid,jid=sys.argv[2:4]
    with tempfile.TemporaryDirectory(prefix='orbit-retest-quality-') as temp:
        db=Path(temp)/'isolated.sqlite'
        with closing(connect(live)) as c:
            before=snapshots.copy_project_snapshot(c,db,pid,lambda c,p:capture(c,p,jid))
        with closing(connect(db)) as c:
            c.execute('PRAGMA journal_mode=WAL');c.execute('BEGIN')
            source,cases,_,_=runner.current(c,db,pid,jid)
            m=mapping.view(c,db,pid,jid)
            version=len(t.runs.history(c,pid,jid))
            require(not t.registry.history(c,pid,jid),'Clean registry baseline required')
            c.rollback()
            closer=c.execute("SELECT m.user_id FROM auth_memberships m JOIN auth_users u ON u.id=m.user_id WHERE m.project_id=? AND m.role='owner' AND u.active=1",(pid,)).fetchone()[0]
        fail_case=cases[0]['id'];points={};executions=[]
        def execute(fail=False):
            result=run(db,pid,jid,source,m,version+len(executions),fail_case if fail else None)
            require(result['report']['gate']==('BLOCK' if fail else 'PASS'),'Unexpected real Docker result')
            executions.append(result)
        def mark(key,state):
            v=point(db,pid,jid);require(v['gate']['state']==state,'Unexpected retest gate '+key+': '+str(v['gate']))
            points[key]=v
        execute(True);r1=register(db,pid,jid);mark('open','BLOCK')
        command(db,pid,jid,r1,'ASSIGN','ci-reviewer','ci-developer')
        command(db,pid,jid,r1,'START','ci-developer')
        execute();mark('recovered','BLOCK')
        finish(db,pid,jid,r1,closer);mark('first_closed','RETEST_QUALITY_PASS')
        old=item(points['first_closed']['tracking'],r1)['history']
        # Explicit reopening of a current closure cannot reuse its execution.
        v=read(db,pid,jid)
        reopen=race(db,pid,jid,'ci-reviewer',body(v,item(v,r1),'REOPEN'))
        mark('reopened','BLOCK')
        command(db,pid,jid,r1,'START','ci-developer')
        rejected(lambda:command(db,pid,jid,r1,'SUBMIT','ci-developer'),ValueError,'newer than last closure')
        mark('same_run_rejected','BLOCK')
        execute(True);r2=register(db,pid,jid)
        require(r2!=r1,'Distinct occurrence required')
        mark('recurrence','BLOCK')
        command(db,pid,jid,r2,'ASSIGN','ci-reviewer','ci-developer')
        command(db,pid,jid,r2,'START','ci-developer')
        command(db,pid,jid,r1,'SUBMIT','ci-developer')
        rejected(lambda:command(db,pid,jid,r1,'VERIFY','ci-reviewer'),ValueError,'original assertion')
        command(db,pid,jid,r1,'REJECT','ci-reviewer')
        execute();mark('fresh','BLOCK')
        finish(db,pid,jid,r1,closer);mark('historical_closed','BLOCK')
        finish(db,pid,jid,r2,closer);mark('both_closed','RETEST_QUALITY_PASS')
        # Another successful execution still invalidates both exact closures.
        execute();mark('stale','BLOCK')
        require(all(x['status']=='STALE_RETEST' for x in points['stale']['gate']['items']),'Expected both closures stale')
        for rd in (r1,r2):
            command(db,pid,jid,rd,'REOPEN','ci-reviewer')
            command(db,pid,jid,rd,'START','ci-developer')
            finish(db,pid,jid,rd,closer)
        mark('final','RETEST_QUALITY_PASS')
        require(item(points['final']['tracking'],r1)['history'][:len(old)]==old,'Immutable closure changed')
        with closing(connect(db)) as c:
            c.execute('BEGIN')
            q.require_current(c,db,pid,jid,points['final']['gate']['evidence_digest'])
            rejected(lambda:q.require_current(c,db,pid,jid,points['both_closed']['gate']['evidence_digest']),ValueError,'Current defect retest quality gate required')
        with closing(connect(live)) as c:
            require(snapshots.capture(c,pid,lambda c,p:capture(c,p,jid))==before,'Live evidence modified')
        print(json.dumps(dict(schema='orbit.defect-retest-quality-browser.v1',source_commit=os.environ['GITHUB_SHA'],
            run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'],project_id=pid,job_id=jid,
            registrations=[r1,r2],executions=executions,points=points,reopen_race=reopen,
            same_run_rejected=True,failed_verify_rejected=True,stale_digest_rejected=True,live_unchanged=True),sort_keys=True))
if __name__=='__main__':main()
