"""Test-only CLI: synthetic sandbox transport, production report and compare logic."""
import os
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
