#!/usr/bin/env python3
"""Select a candidate using the latest persisted verification; no GitHub writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from coding_factory import detail
from verification_factory import list_reports
from web_candidate_selection import decide

def bind_decision(job, entry, **kwargs):
    decision=decide(job,entry['report'],**kwargs)
    decision['verification_id']=entry['id']
    decision['verification_digest']=hashlib.sha256(json.dumps(entry['report'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return decision

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=ROOT/'company.sqlite')
    p.add_argument('--job-id',required=True)
    p.add_argument('--selected',choices=['A','B'],required=True)
    p.add_argument('--techlead',required=True)
    p.add_argument('--rationale',required=True)
    p.add_argument('--confirm',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(argv)
    if not a.db.is_file(): p.error('Database missing')
    try:
        with sqlite3.connect(a.db) as conn:
            conn.row_factory=sqlite3.Row
            job=detail(conn,a.job_id)
            entries=list_reports(conn,a.job_id,1)
            if not entries: raise ValueError('No verification evidence')
            d=bind_decision(job,entries[0],selected=a.selected,techlead=a.techlead,rationale=a.rationale,confirmation=a.confirm)
        with a.output.open('x',encoding='utf-8') as f:
            json.dump(d,f,ensure_ascii=False,indent=2)
        print('Decision saved; no GitHub writes')
        return 0
    except (ValueError,PermissionError,OSError,sqlite3.Error,KeyError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr)
        return 1
if __name__=='__main__': raise SystemExit(main())
