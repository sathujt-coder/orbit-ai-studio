#!/usr/bin/env python3
"""Trusted local operator only; never exposed as an HTTP execution endpoint."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_sandbox as sandbox

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--project',required=True)
    p.add_argument('--job',required=True)
    p.add_argument('--actor',required=True)
    p.add_argument('--source-digest',required=True)
    p.add_argument('--expected-version',type=int,required=True)
    p.add_argument('--confirm',required=True)
    p.add_argument('--python-image',default=os.getenv('ORBIT_SANDBOX_PYTHON_IMAGE'))
    p.add_argument('--node-image',default=os.getenv('ORBIT_SANDBOX_NODE_IMAGE'))
    p.add_argument('--react-image',default=os.getenv('ORBIT_SANDBOX_REACT_IMAGE'))
    p.add_argument('--timeout',type=int,default=25)
    a=p.parse_args()
    if not a.db.is_file():p.error('Existing ORBIT database required')
    try:
        with sqlite3.connect(a.db,timeout=20) as c:
            c.row_factory=sqlite3.Row
            c.execute('PRAGMA foreign_keys=ON')
            result=sandbox.run(c,a.db,a.project,a.job,a.actor,a.source_digest,
                a.expected_version,a.confirm,python_image=a.python_image,node_image=a.node_image,
                react_image=a.react_image,timeout=a.timeout)
        print(json.dumps(result,indent=2))
        return 0 if result['gate']=='PASS' else 2
    except (ValueError,PermissionError,sqlite3.Error,OSError,KeyError,TypeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
