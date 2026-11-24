#!/usr/bin/env python3
"""Dry-run or opt-in publish a verified candidate as GitHub *draft* PR."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from coding_factory import detail
from verification_factory import list_reports
from verified_pr import verified_bundle, VerifiedCodePRClient
from github_pr import GitHubError, VALID_REPO


def main(argv=None, client_type=VerifiedCodePRClient):
    parser = argparse.ArgumentParser(description='Open a draft GitHub PR for sandbox-verified code')
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--decision', type=Path, required=True, help='Tech Lead decision JSON from an authorized, audited workflow')
    parser.add_argument('--db', type=Path, default=ROOT / 'company.sqlite')
    parser.add_argument('--apply', action='store_true', help='Explicitly write code under agent-proposals/ and create draft PR')
    parser.add_argument('--confirm', default='', help='Exact confirmation CREATE CODE PR <job id>')
    args = parser.parse_args(argv)
    if not VALID_REPO.fullmatch(args.repo) or '..' in args.repo:
        parser.error('Invalid repository')
    if not args.db.is_file():
        parser.error('SQLite database missing')
    try:
        with sqlite3.connect(args.db) as conn:
            conn.row_factory = sqlite3.Row
            job = detail(conn, args.job_id)
            prior = conn.execute("SELECT status,pr_url FROM code_pr_exports WHERE job_id=?", (args.job_id,)).fetchone() if _has_table(conn) else None
            if prior and prior['status'] in ('pending', 'created'):
                raise ValueError('Code PR already pending or created: ' + str(prior['pr_url']))
            results = list_reports(conn, args.job_id)
            if not results:
                raise ValueError('No sandbox verification evidence exists')
            if not args.decision.is_file():
                raise ValueError('Tech Lead decision JSON is missing')
            if args.decision.stat().st_size > 50_000:
                raise ValueError('Tech Lead decision JSON is too large')
            decision = json.loads(args.decision.read_text(encoding='utf-8'))
            if results[0]['report'].get('profile') == 'react-welcome-v1' or 'verification_id' in decision:
                digest = hashlib.sha256(json.dumps(results[0]['report'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
                if decision.get('verification_id') != results[0]['id'] or decision.get('verification_digest') != digest:
                    raise ValueError('Decision does not bind latest persisted verification')
            bundle = verified_bundle(job, results[0]['report'], decision=decision)
            if not args.apply:
                print(json.dumps({'mode': 'dry-run', 'repo': args.repo,
                                  'selected': bundle['selected'], 'source_prefix': bundle['prefix'],
                                  'files': [f['path'] for f in bundle['files']],
                                  'reviews': bundle['review_summary'],
                                  'notice': 'No GitHub mutation; pass --apply and explicit --confirm'},
                                 ensure_ascii=False, indent=2))
                return 0
            if args.confirm != 'CREATE CODE PR ' + args.job_id:
                raise PermissionError('Confirmation required: CREATE CODE PR <job id>')
            if os.getenv('ORBIT_GITHUB_WRITES') != '1':
                raise PermissionError('ORBIT_GITHUB_WRITES=1 is required')
            token = os.getenv('GITHUB_TOKEN', '')
            if not token:
                raise PermissionError('GITHUB_TOKEN is required locally; never put it in a web form')
            conn.execute('''CREATE TABLE IF NOT EXISTS code_pr_exports(
                job_id TEXT PRIMARY KEY,repo TEXT NOT NULL,status TEXT NOT NULL,
                pr_url TEXT,pr_number INTEGER,branch TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('INSERT INTO code_pr_exports(job_id,repo,status) VALUES(?,?,?) '
                         'ON CONFLICT(job_id) DO UPDATE SET status=excluded.status,repo=excluded.repo',
                         (args.job_id,args.repo,'pending'))
            conn.commit()
        result = client_type(token).draft_pr(args.repo, bundle)
        with sqlite3.connect(args.db) as conn:
            conn.execute('UPDATE code_pr_exports SET status=?,pr_url=?,pr_number=?,branch=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?',
                         ('created',result['url'],result['number'],result['branch'],args.job_id))
            conn.commit()
        print(json.dumps({'mode':'created',**result},ensure_ascii=False,indent=2))
        return 0
    except (ValueError, PermissionError, sqlite3.Error, KeyError, GitHubError) as exc:
        if args.apply and args.confirm == 'CREATE CODE PR ' + args.job_id:
            try:
                with sqlite3.connect(args.db) as conn:
                    conn.execute("UPDATE code_pr_exports SET status='failed', updated_at=CURRENT_TIMESTAMP WHERE job_id=? AND status='pending'",(args.job_id,))
                    conn.commit()
            except sqlite3.Error:
                pass
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1


def _has_table(conn):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='code_pr_exports'").fetchone())


if __name__ == '__main__':
    raise SystemExit(main())
