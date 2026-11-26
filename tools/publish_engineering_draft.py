#!/usr/bin/env python3
"""Explicit local GitHub draft only; token never accepted via HTTP."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_draft as draft
from github_pr import GitHubError

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    for key in ('project','job','actor','repo','base','base-sha'):
        p.add_argument('--'+key,required=True)
    p.add_argument('--plan-digest',default='')
    p.add_argument('--confirm',default='')
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if not a.db.is_file():p.error('Existing ORBIT database required')
    try:
        with sqlite3.connect(a.db,timeout=20) as c:
            c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
            if not a.apply:
                draft.pp.check_role(c,a.project,a.actor,'publish')
                plan,_=draft.prepare(c,a.db,a.project,a.job,a.repo,a.base,a.base_sha)
                print(json.dumps(dict(mode='dry-run',plan=plan,plan_digest=draft.pp.digest(plan)),indent=2))
                return 0
            if os.getenv('ORBIT_GITHUB_WRITES')!='1' or not os.getenv('GITHUB_TOKEN'):
                raise PermissionError('Explicit local GitHub write opt-in and token required')
            result=draft.publish(c,a.db,a.project,a.job,a.actor,a.repo,a.base,a.base_sha,
                                  a.plan_digest,a.confirm,draft.DraftClient(os.environ['GITHUB_TOKEN']))
            print(json.dumps(result,indent=2));return 0
    except (ValueError,PermissionError,sqlite3.Error,KeyError,TypeError,OSError,GitHubError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
