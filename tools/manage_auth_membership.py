#!/usr/bin/env python3
"""Trusted local administrator only; no browser credentials or network calls."""
import argparse,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import auth_store
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=ROOT/'company.sqlite')
    p.add_argument('--list-projects',action='store_true')
    p.add_argument('--user')
    p.add_argument('--project')
    p.add_argument('--role',choices=[*auth_store.ROLES,'revoke'])
    a=p.parse_args()
    if not a.db.is_file():p.error('Database missing')
    with sqlite3.connect(a.db) as c:
        if a.list_projects:
            for row in c.execute('SELECT id,name FROM projects'):print(*row,sep='\t')
            return
        if not all((a.user,a.project,a.role)):p.error('User, project, role required')
        if not c.execute('SELECT 1 FROM projects WHERE id=?',(a.project,)).fetchone():p.error('Unknown project')
        if a.role=='revoke':c.execute('DELETE FROM auth_memberships WHERE user_id=? AND project_id=?',(a.user,a.project))
        else:auth_store.grant(c,a.user,a.project,a.role)
        c.execute('INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,?)',('local-operator',a.project,'membership:'+a.role,'success',int(time.time())))
if __name__=='__main__':main()
