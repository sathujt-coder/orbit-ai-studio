#!/usr/bin/env python3
"""Provision a local user without exposing a public registration endpoint."""
import argparse
import getpass
import sqlite3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import auth_store
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',type=Path,default=ROOT/'company.sqlite')
    p.add_argument('--user',required=True)
    p.add_argument('--project',help='Existing project ID to grant membership')
    p.add_argument('--role',choices=sorted(auth_store.ROLES),default='viewer')
    a=p.parse_args()
    if not a.db.is_file():p.error('Start ORBIT first')
    password=getpass.getpass('Password: ')
    if password!=getpass.getpass('Repeat password: '):p.error('Passwords differ')
    try:
        with sqlite3.connect(a.db) as c:
            auth_store.ensure_schema(c)
            auth_store.create_user(c,a.user,password)
            if a.project:
                if not c.execute('SELECT 1 FROM projects WHERE id=?',(a.project,)).fetchone():raise ValueError('Unknown project')
                auth_store.grant(c,a.user,a.project,a.role)
                auth_store.authorize(c,a.user,a.project,'read')
        print('User created; explicit project membership applied' if a.project else 'User created; no existing project membership')
    except (ValueError,sqlite3.Error) as e:p.error(str(e))
if __name__=='__main__':main()
