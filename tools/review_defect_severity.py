#!/usr/bin/env python3
"""Local trusted operator severity review; never dispatches or changes gates."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import defect_severity as s
import acceptance_runner as runner
import project_planning as pp

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    for k in ('project','job','actor'):p.add_argument('--'+k,required=True)
    p.add_argument('--attest',action='store_true')
    for k in ('finding','expected-digest','impact','rationale','confirm'):p.add_argument('--'+k)
    a=p.parse_args()
    if not a.db.is_file():p.error('Existing database required')
    try:
        with sqlite3.connect(a.db,timeout=20) as c:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            runner.begin_audited_transaction(c)
            pp.check_role(c,a.project,a.actor,'approve' if a.attest else 'read')
            if a.attest:
                s.ensure_schema(c)
                digest=s.attest(c,a.db,a.project,a.job,a.actor,a.finding,a.expected_digest,a.impact,a.rationale,a.confirm)
            else:
                # Schema installation is an explicit migration, never a side effect of a read.
                runner.restrict_cli_database(c)
                digest=None
            v=s.view(c,a.db,a.project,a.job)
        print(json.dumps(dict(result=v,attestation_digest=digest),sort_keys=True))
        return 0
    except (ValueError,PermissionError,sqlite3.Error,OSError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
