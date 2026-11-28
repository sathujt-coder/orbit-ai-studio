#!/usr/bin/env python3
"""Trusted local defect observation; only the existing RBAC audit may write."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import acceptance_runner as runner
import automated_defect_detection as detection
import defect_classification as classification
import project_planning as pp

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    for k in ('project','job','actor'):
        p.add_argument('--'+k,required=True)
    p.add_argument('--classify',action='store_true')
    a=p.parse_args()
    if not a.db.is_file():p.error('Existing database required')
    try:
        with sqlite3.connect(a.db,timeout=20) as c:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            runner.restrict_cli_database(c)
            runner.begin_audited_transaction(c)
            pp.check_role(c,a.project,a.actor,'read')
            v=detection.view(c,a.db,a.project,a.job)
            if a.classify:v=classification.classify(a.project,a.job,v)
        print(json.dumps(v,sort_keys=True))
        return 0
    except (ValueError,PermissionError,sqlite3.Error,OSError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
