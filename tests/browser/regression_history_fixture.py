#!/usr/bin/env python3
"""Read the real fixture database without mutating historical receipts."""
import json,os,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
import regression_quality_gate as g

def main():
    if os.environ.get('ORBIT_REQUIREMENTS_BROWSER_FIXTURE')!='1':
        raise SystemExit('Isolated browser fixture required')
    db=Path(sys.argv[1]).resolve();pid,jid=sys.argv[2:4]
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=20) as c:
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA query_only=ON')
        c.execute('BEGIN')
        runs=g.registry.history(c,pid,jid)
        versions=[r['version'] for r in c.execute(
            'SELECT version FROM engineering_regression_priority_receipts WHERE project_id=? AND job_id=? ORDER BY version',(pid,jid))]
        receipts=[g.load(c,pid,jid,v) for v in versions]
        for version,receipt in zip(versions,receipts):
            s=receipt['snapshot']
            if (not 1<=version<=len(runs) or s['execution_version']!=version
                or s['execution_receipt_digest']!=runs[version-1]['digest']
                or receipt['digest']!=g.pp.digest(s)):
                raise ValueError('Invalid historical priority receipt')
        count=c.execute("SELECT count(*) FROM auth_audit WHERE project_id=? AND actor=? AND action=? AND outcome=?",
                        (pid,'ci-reviewer','engineering_regression_priority_record','allowed')).fetchone()[0]
        print(json.dumps(dict(execution_history=runs,priority_history=receipts,priority_audit_count=count),sort_keys=True))
if __name__=='__main__':main()
