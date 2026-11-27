#!/usr/bin/env python3
"""Trusted local operator only. No HTTP execution or automatic approval."""
import argparse,json,os,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import acceptance_runner as runner

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    for key in ('project','job','actor','plan-digest','source-digest','assertion-digest','sandbox-digest','confirm'):
        p.add_argument('--'+key,required=True)
    p.add_argument('--python-image',default=os.getenv('ORBIT_SANDBOX_PYTHON_IMAGE'))
    p.add_argument('--expected-registry-version',type=int,default=None,help='Explicit opt-in to append a durable result')
    a=p.parse_args()
    if not a.db.is_file():p.error('Existing database required')
    try:
        with sqlite3.connect(a.db,timeout=20) as c:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            runner.restrict_cli_database(c,persist=a.expected_registry_version is not None)
            result=runner.run(c,a.db,a.project,a.job,a.actor,a.plan_digest,a.source_digest,a.assertion_digest,a.sandbox_digest,a.confirm,image=a.python_image,expected_registry_version=a.expected_registry_version)
        print(json.dumps(result,sort_keys=True))
        return 0 if result['report']['gate']=='PASS' else 2
    except (ValueError,PermissionError,sqlite3.Error,OSError,KeyError,TypeError,SyntaxError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
