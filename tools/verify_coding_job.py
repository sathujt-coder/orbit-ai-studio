#!/usr/bin/env python3
"""Review ORBIT v0.5 execution plan and explicitly run Docker-only tests.

CLI execution is intentionally NOT exposed via the unauthenticated localhost API.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from coding_factory import detail
from react_candidate_gate import verify_react, plan_react
from verification_factory import safe_job
from verification_factory import preview_job, verify_job, store_report, ensure_schema


def main(argv=None):
    parser = argparse.ArgumentParser(description='Review or execute sandbox tests for a reviewed ORBIT coding job')
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--db', type=Path, default=ROOT / 'company.sqlite')
    parser.add_argument('--profile', choices=['legacy','react-welcome-v1'], default='legacy')
    parser.add_argument('--react-image', default=os.getenv('ORBIT_SANDBOX_REACT_IMAGE'))
    parser.add_argument('--execute', action='store_true', help='Run generated code only in Docker sandbox')
    parser.add_argument('--confirm', default='', help='Exact confirmation RUN SANDBOX <job id>')
    parser.add_argument('--python-image', default=os.getenv('ORBIT_SANDBOX_PYTHON_IMAGE'))
    parser.add_argument('--node-image', default=os.getenv('ORBIT_SANDBOX_NODE_IMAGE'))
    parser.add_argument('--timeout', type=int, default=25)
    args = parser.parse_args(argv)
    if not args.db.is_file():
        parser.error('SQLite database not found; run ORBIT locally first')
    try:
        with sqlite3.connect(args.db) as conn:
            conn.row_factory = sqlite3.Row
            job = detail(conn, args.job_id)
            if not args.execute:
                data = ({lane: plan_react(p) for lane,p in safe_job(job).items()}
                        if args.profile == 'react-welcome-v1' else preview_job(job))
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return 0
            if args.profile == 'react-welcome-v1':
                report = verify_react(job, image=args.react_image, approval=args.confirm, timeout=args.timeout)
            else:
                report = verify_job(job, approval=args.confirm, python_image=args.python_image,
                                    node_image=args.node_image, timeout=args.timeout)
            ensure_schema(conn)
            ref = store_report(conn, report)
            conn.commit()
        print(json.dumps({'verification_id': ref, **report}, ensure_ascii=False, indent=2))
        return 0 if report['gate'] == 'PASS' else 2
    except (ValueError, PermissionError, sqlite3.Error, OSError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
