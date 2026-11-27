#!/usr/bin/env python3
"""Trusted local operator registry; no HTTP mutation or automatic repair."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import detected_defect_registry as registry
import acceptance_runner as runner
import project_planning as pp

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    for k in ('project','job','actor'):p.add_argument('--'+k,required=True)
    p.add_argument('--register',action='store_true')
    p.add_argument('--expected-digest')
    p.add_argument('--confirm')
    a=p.parse_args()
    if not a.db.is_file():p.error('Existing database required')
    try:
        with sqlite3.connect(a.db,timeout=20) as c:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            if not a.register:runner.restrict_cli_database(c)
            runner.begin_audited_transaction(c)
            if a.register:
                inserted=registry.register(c,a.db,a.project,a.job,a.actor,a.expected_digest,a.confirm)
            else:
                pp.check_role(c,a.project,a.actor,'read')
                inserted=[]
            v=registry.view(c,a.db,a.project,a.job)
            if a.register and v['state']!='REGISTERED':raise ValueError('Registration not verified')
        print(json.dumps(dict(result=v,inserted=inserted),sort_keys=True))
        return 0
    except (ValueError,PermissionError,sqlite3.Error,OSError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
