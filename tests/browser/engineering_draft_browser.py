"""Browser integration: actual SQLite/Git, isolated GitHub contract transport."""
import json
import os
from pathlib import Path
import sqlite3
import sys
root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'backend'),str(root/'tests')]
import engineering_draft as ed
from engineering_draft_fixture import FakeRemote

def main():
    if os.getenv('ORBIT_REQUIREMENTS_BROWSER_FIXTURE')!='1':raise SystemExit('Fixture opt-in required')
    pid,jid=sys.argv[1:]
    db=Path(os.environ['AI_COMPANY_DB'])
    repo,base,sha='example/orbit','main','a'*40
    with sqlite3.connect(db,timeout=20) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        plan,files=ed.prepare(c,db,pid,jid,repo,base,sha)
        digest=ed.pp.digest(plan)
        remote=FakeRemote()
        args=(c,db,pid,jid,'ci-browser-user',repo,base,sha,digest,'CREATE ENGINEERING DRAFT '+jid+' '+repo+' '+digest,remote)
        out=ed.publish(*args)
        assert out['status']=='CREATED_DRAFT'
        assert ed.view(c,db,pid,jid)['state']=='CREATED_DRAFT'
        writes=[(m,r,p) for m,r,p in remote.calls if m!='GET']
        assert len([1 for m,r,p in writes if r.endswith('/pulls')])==1
        assert all('/merge' not in r and '/deployments' not in r for m,r,p in writes)
        assert all(e['path'].startswith('agent-proposals/'+jid+'/candidate-B/') or e['path']=='agent-proposals/'+jid+'/VERIFICATION.json' for e in remote.entries)
        before=len(remote.calls)
        try:ed.publish(*args)
        except ValueError:pass
        else:raise AssertionError('Duplicate publication accepted')
        assert len(remote.calls)==before
        print(json.dumps(dict(schema='orbit.engineering-draft-browser.v1',source_commit=os.environ['GITHUB_SHA'],
              run_id=os.environ['GITHUB_RUN_ID'],run_attempt=os.environ['GITHUB_RUN_ATTEMPT'],
              transport='synthetic_github_api_real_git_sqlite',plan=plan,plan_digest=digest,
              receipt=out,duplicate_blocked=True,remote_writes_real=False,**ed.FLAGS)))

if __name__=='__main__':main()
