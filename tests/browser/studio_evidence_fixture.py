"""Test-only CLI: synthetic sandbox transport, production report and compare logic."""
import os
import json
import sys
import sqlite3
from pathlib import Path
if os.environ.get('ORBIT_REQUIREMENTS_BROWSER_FIXTURE')!='1':
    raise SystemExit('Explicit isolated fixture required')
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'backend'),str(root/'tests')]
import server
import coding_factory as cf
import verification_factory as vf
import studio_verification as qa
import agent_queue as aq
from web_candidate_selection import compare
from test_verification_factory import FakeDocker,PY_IMG

def dependency_snapshot(c,pid):
    """Exact persisted row digests, not merely counts; exclude HTTP access audit."""
    import project_planning as pp
    queries={
        'coding_jobs':'SELECT * FROM coding_jobs WHERE project_id=? ORDER BY rowid',
        'agent_queue':'SELECT * FROM agent_queue WHERE project_id=? ORDER BY rowid',
        'studio_coding_bindings':'SELECT * FROM studio_coding_bindings WHERE project_id=? ORDER BY rowid',
        'engineering_queue_sources':'SELECT * FROM engineering_queue_sources WHERE project_id=? ORDER BY rowid',
        'queue_events':'SELECT e.* FROM agent_queue_events e JOIN agent_queue q ON q.id=e.task_id WHERE q.project_id=? ORDER BY e.seq',
        'project_events':'SELECT * FROM events WHERE project_id=? ORDER BY rowid',
        'dependency_audit':"SELECT * FROM auth_audit WHERE project_id=? AND action='engineering_dependency_queue' ORDER BY rowid",
        'usage':'SELECT * FROM ai_usage WHERE project_id=? ORDER BY rowid',
        'completions':'SELECT * FROM engineering_completions WHERE project_id=? ORDER BY rowid',
        'qa':'SELECT * FROM studio_qa_receipts WHERE project_id=? ORDER BY rowid',
        'verification':'SELECT * FROM coding_verifications WHERE project_id=? ORDER BY rowid',
    }
    out={}
    for name,query in queries.items():
        rows=[dict(row) for row in c.execute(query,(pid,))]
        out[name]=dict(count=len(rows),digest=pp.digest(rows))
    assert not c.execute('PRAGMA foreign_key_check').fetchall()
    return out

def stale_dispatch_copy(c,pid,root_job):
    """Use a coherent SQLite backup, no live-worker control or source mocks.
    Run the actual dispatcher in two isolated copies; prohibit model transport.
    """
    import tempfile
    from contextlib import closing
    from unittest.mock import patch
    import dependency_queue as dq
    import dependency_completion as dc
    import studio_coding as sc
    root=cf.detail(c,root_job)
    assert root['project_id']==pid and root['status']=='ready'
    assert root['proposal_a']['summary'].startswith('Synthetic coding fixture ')
    ready=[x for x in dq.view(c,pid)['items'] if x['state']=='READY_FOR_EXPLICIT_SUBMISSION']
    assert len(ready)==1
    item=ready[0];source=item['source']
    assert [x['job_id'] for x in source['prerequisites']]==[root_job]
    body=dict(adoption_version=item['adoption_version'],package_id=item['package_id'],
        binding_digest=source['binding_digest'],source_digest=item['source_digest'],confirmation='QUEUE DEPENDENT WORK PACKAGE')
    assert next(x for x in dc.view(c,pid)['items'] if x['job_id']==root_job)['state']=='COMPLETION_EVIDENCE_CONFIRMED'
    original=dependency_snapshot(c,pid)
    results=[]
    for scenario in ('before_claim','after_routing'):
        with tempfile.TemporaryDirectory(prefix='orbit-dependent-dispatch-') as temp:
            copy_path=Path(temp)/'isolated.sqlite'
            with closing(sqlite3.connect(copy_path)) as dest:c.backup(dest)
            with patch.object(server,'DB_PATH',copy_path),aq.dispatcher_lock(copy_path):
                # Other concurrent browser tests may have queued work in the
                # backup. Defer it in the COPY only; never touch the live DB.
                with server.db() as isolated:
                    assert not isolated.execute("SELECT 1 FROM agent_queue WHERE project_id=? AND status IN ('queued','running')",(pid,)).fetchone()
                    isolated.execute("UPDATE agent_queue SET available_at=253402300799 WHERE project_id<>? AND status='queued'",(pid,))
                submitted=server.enqueue_dependent_coding(pid,'ci-developer',body)
                jid,qid=submitted['job_id'],submitted['queue_id']
                with server.db() as isolated:
                    assert aq.get(isolated,pid,qid)['status']=='queued'
                    row=sc.lookup(isolated,pid,jid)
                    pinned=dict(isolated.execute('SELECT * FROM engineering_queue_sources WHERE project_id=? AND job_id=?',(pid,jid)).fetchone())
                    assert pinned['digest']==item['source_digest']
                    assert dq.checked_package(isolated,pid,row)
                    assert not isolated.execute('SELECT 1 FROM ai_usage WHERE run_id=?',(jid,)).fetchone()
                def invalidate():
                    with server.db() as isolated:
                        row=isolated.execute('SELECT id,report_json FROM coding_verifications WHERE project_id=? AND job_id=? ORDER BY rowid DESC LIMIT 1',(pid,root_job)).fetchone()
                        new=vf.store_report(isolated,json.loads(row['report_json']))
                        assert new!=row['id']
                        assert next(x for x in dc.view(isolated,pid)['items'] if x['job_id']==root_job)['state']=='STALE'
                real_route=server.route_pair
                def route_then_invalidate(*args,**kwargs):
                    lanes=real_route(*args,**kwargs)
                    invalidate()
                    return lanes
                if scenario=='before_claim':invalidate()
                # Any model invocation is a regression. Use spies with failing
                # side effects so even a caught exception cannot pass the test.
                with (patch.object(server,'route_pair',side_effect=route_then_invalidate if scenario=='after_routing' else AssertionError('Unexpected routing')) as routing,
                      patch.object(cf,'generate_proposal',side_effect=AssertionError('Unexpected generation')) as generate,
                      patch.object(cf,'review_proposal',side_effect=AssertionError('Unexpected review')) as review,
                      patch.object(server.model_provider,'chat',side_effect=AssertionError('Unexpected transport')) as transport):
                    assert server.dispatch_one() is True
                    assert routing.call_count==(1 if scenario=='after_routing' else 0)
                    generate.assert_not_called();review.assert_not_called();transport.assert_not_called()
                with server.db() as isolated:
                    queue=aq.get(isolated,pid,qid);job=cf.detail(isolated,jid)
                    assert queue['status']=='dead' and queue['reason']=='coding_source_invalid'
                    assert queue['attempts']==1 and job['status']=='failed'
                    assert all(job[k] is None for k in ('proposal_a','proposal_b','review_a','review_b','manifest'))
                    assert not isolated.execute('SELECT 1 FROM ai_usage WHERE run_id=?',(jid,)).fetchone()
                    assert dict(isolated.execute('SELECT * FROM engineering_queue_sources WHERE project_id=? AND job_id=?',(pid,jid)).fetchone())==pinned
                    assert sc.evidence(isolated,pid,jid)['state']=='STALE'
                    assert qa.view(isolated,pid,jid)['state']=='BLOCK'
                    assert next(x for x in dq.view(isolated,pid)['items'] if x['package_id']==item['package_id'])['state']=='BLOCK'
                    assert not isolated.execute('PRAGMA foreign_key_check').fetchall()
                try:server.retry_queue(pid,qid,'ci-developer','RETRY QUEUE TASK')
                except ValueError as err:assert 'Bound coding retry' in str(err)
                else:raise AssertionError('Unexpected automatic retry path')
                results.append(dict(scenario=scenario,queue='dead',reason='coding_source_invalid',job='failed',model_calls=0,pin_unchanged=True))
    assert dependency_snapshot(c,pid)==original
    return results

def main():
    db=Path(os.environ['AI_COMPANY_DB']).resolve()
    if db.name!='requirements-browser.sqlite' or not db.is_file():
        raise SystemExit('Only isolated requirements browser database permitted')
    action,pid,identifier=sys.argv[1:]
    with server.db() as c:
        if action=='fault-on':
            # Only the supplied project; abort the actual production binding INSERT.
            if not pid.isalnum():raise ValueError('Invalid project ID')
            c.execute("CREATE TRIGGER sg6f_binding_fault BEFORE INSERT ON studio_coding_bindings WHEN NEW.project_id='"+pid+"' BEGIN SELECT RAISE(ABORT,'fixture binding fault'); END")
            return
        if action=='fault-off':
            c.execute('DROP TRIGGER sg6f_binding_fault')
            for table in ('coding_jobs','studio_coding_bindings'):
                assert c.execute('SELECT COUNT(*) FROM '+table+' WHERE project_id=?',(pid,)).fetchone()[0]==0
            assert c.execute("SELECT COUNT(*) FROM agent_queue WHERE project_id=? AND kind='coding'",(pid,)).fetchone()[0]==0
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
            return
        if action in ('dependency-pin-fault-on','dependency-audit-fault-on'):
            if not pid.isalnum():raise ValueError('Invalid project ID')
            assert not c.execute("SELECT 1 FROM agent_queue WHERE project_id=? AND status IN ('queued','running')",(pid,)).fetchone()
            before=dependency_snapshot(c,pid)
            if action=='dependency-pin-fault-on':
                c.execute("CREATE TRIGGER p63_pin_fault AFTER INSERT ON engineering_queue_sources WHEN NEW.project_id='"+pid+"' BEGIN SELECT RAISE(ABORT,'fixture dependency pin persistence fault'); END")
            else:
                c.execute("CREATE TRIGGER p63_audit_fault AFTER INSERT ON auth_audit WHEN NEW.project_id='"+pid+"' AND NEW.action='engineering_dependency_queue' BEGIN SELECT RAISE(ABORT,'fixture dependency audit persistence fault'); END")
            print(json.dumps(before));return
        if action=='dependency-fault-off':
            c.execute('DROP TRIGGER IF EXISTS p63_pin_fault')
            c.execute('DROP TRIGGER IF EXISTS p63_audit_fault')
            print(json.dumps(dependency_snapshot(c,pid)));return
        if action=='stale-dispatch-copy':
            print(json.dumps(stale_dispatch_copy(c,pid,identifier)));return
        job=cf.detail(c,identifier)
        assert job['project_id']==pid and job['status']=='ready'
        assert job['proposal_a']['summary'].startswith('Synthetic coding fixture ')
        assert job['proposal_b']['summary'].startswith('Synthetic coding fixture ')
        if action=='report':
            report=vf.verify_job(job,python_image=PY_IMG,approval='RUN SANDBOX '+identifier,runner=FakeDocker())
            assert report['gate']=='PASS'
            compare(job,report)
            vf.store_report(c,report)
        elif action=='dependency-pin':
            import dependency_queue as dq
            import studio_coding as sc
            import project_planning as pp
            bound=sc.lookup(c,pid,identifier)
            assert bound and aq.get(c,pid,bound['queue_id'])['status']=='succeeded'
            pinned=c.execute('SELECT snapshot,digest FROM engineering_queue_sources WHERE project_id=? AND job_id=?',(pid,identifier)).fetchone()
            assert pinned
            snap=json.loads(pinned['snapshot'])
            assert pp.digest(snap)==pinned['digest']
            assert dq.source(c,pid,bound['adoption_version'],bound['package_id'],bound['binding_digest'])==snap
            assert sc.spec_for(dq.checked_package(c,pid,bound))==job['spec']
            assert pp.digest(job['spec'])==bound['spec_digest']==snap['spec_digest']
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
            print(json.dumps(dict(source=snap,digest=pinned['digest'],queue_id=bound['queue_id'],actor=bound['actor'])))
        elif action=='dependency-completion':
            import dependency_completion as dc
            import studio_coding as sc
            import project_planning as pp
            bound=sc.lookup(c,pid,identifier)
            row=dc.latest(c,pid,bound['adoption_version'],bound['package_id'])
            assert row and row['job_id']==identifier and row['version']==1
            snap=json.loads(row['snapshot'])
            assert pp.digest(snap)==row['digest']
            assert dc.source(c,pid,identifier)==snap['source']
            decision=snap['decision']
            checked=dc.selection(c,pid,snap['source'],row['actor'],decision['selected'],decision['rationale'])
            assert {k:v for k,v in checked.items() if k!='decided_at'}=={k:v for k,v in decision.items() if k!='decided_at'}
            print(json.dumps(dict(digest=row['digest'],source_digest=pp.digest(snap['source']),dependency_source_digest=snap['source']['dependency_source_digest'],selected_digest=decision['selected_digest'])))
        elif action=='qa-receipt':
            row=c.execute('SELECT version,digest,snapshot FROM studio_qa_receipts WHERE project_id=? AND job_id=? ORDER BY version DESC LIMIT 1',(pid,identifier)).fetchone()
            assert row and row['version']==1
            import project_planning as pp
            snap=json.loads(row['snapshot'])
            assert pp.digest(snap)==row['digest']
            state=qa.view(c,pid,identifier)
            assert state['state']=='HUMAN_QA_PASS' and state['receipt']['digest']==row['digest']
            print(json.dumps(dict(version=row['version'],digest=row['digest'],source_digest=pp.digest(snap['source']),criteria=snap['criteria'])))
        elif action=='reopen-check':
            # New process and connection; invoke startup queue recovery only
            # when no task is in flight. Not a live-server restart.
            assert not c.execute("SELECT 1 FROM agent_queue WHERE status='running'").fetchone()
            before=qa.view(c,pid,identifier)
            assert before['state']=='HUMAN_QA_PASS'
            aq.recover(c,0,server.now())
            assert qa.view(c,pid,identifier)==before
        else:raise ValueError('Unknown fixture action')

if __name__=='__main__':main()
