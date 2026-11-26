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
