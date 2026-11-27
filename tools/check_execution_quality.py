#!/usr/bin/env python3
"""Trusted local development evidence check; never authorizes execution or release."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import acceptance_runner as runner
import execution_quality_gate as gate

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    for k in ('project','job','actor','expected-digest'):p.add_argument('--'+k,required=True)
    a=p.parse_args()
    if not a.db.is_file():p.error('Existing database required')
    try:
        with sqlite3.connect(a.db,timeout=20) as c:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            runner.restrict_cli_database(c)
            c.execute('BEGIN')
            gate.pp.check_role(c,a.project,a.actor,'read')
            v=gate.require_current(c,a.db,a.project,a.job,a.expected_digest)
        print(json.dumps(v,sort_keys=True))
        return 0
    except (ValueError,PermissionError,sqlite3.Error,OSError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
