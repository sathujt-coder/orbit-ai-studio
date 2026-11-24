#!/usr/bin/env python3
"""Resume P4 coding delivery after run_real_models. Local operator only; no GitHub writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import coding_factory as cf
import verification_factory as vf
from react_candidate_gate import verify_react
from select_verified_candidate import bind_decision
from verified_pr import verified_bundle
from web_candidate_selection import compare

def latest(c,jid):
    entries=vf.list_reports(c,jid,1)
    if not entries:raise ValueError('No persisted verification evidence')
    return entries[0]
def require_job(c,jid):
    j=cf.detail(c,jid)
    vf.safe_job(j)
    if set(j['manifest'].get('candidate_files',{}))!={'A','B'}:
        raise ValueError('P4.2 requires both reviewed source manifests; regenerate legacy job')
    return j
def decision_table(c):
    c.execute('CREATE TABLE IF NOT EXISTS p4_decisions(job_id TEXT PRIMARY KEY,decision_json TEXT NOT NULL)')
def select(c,j,entry,**kwargs):
    d=bind_decision(j,entry,**kwargs)
    # Full export preflight (including exit codes and project binding) before persisting.
    verified_bundle(j,entry['report'],decision=d)
    decision_table(c)
    c.execute('INSERT INTO p4_decisions VALUES(?,?) ON CONFLICT(job_id) DO UPDATE SET decision_json=excluded.decision_json',(j['id'],json.dumps(d,ensure_ascii=False)))
    return d
def prepare(c,j,entry):
    decision_table(c)
    row=c.execute('SELECT decision_json FROM p4_decisions WHERE job_id=?',(j['id'],)).fetchone()
    if not row:raise ValueError('Tech Lead selection required')
    d=json.loads(row[0])
    digest=hashlib.sha256(json.dumps(entry['report'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if d.get('verification_id')!=entry['id'] or d.get('verification_digest')!=digest:
        raise ValueError('Selection is stale; select again after latest verification')
    return verified_bundle(j,entry['report'],decision=d),d
def state(c,j):
    out={'job_id':j['id'],'project_id':j['project_id'],'job_status':j['status'],'stage':'awaiting_review','publication':'not_requested','production_approved':False}
    if j['status']!='ready':return out
    try:require_job(c,j['id'])
    except ValueError:out['stage']='blocked';return out
    out['stage']='awaiting_sandbox'
    try:
        entry=latest(c,j['id'])
        out['verification_id']=entry['id']
        out['sandbox_gate']=entry['report']['gate']
        compare(j,entry['report'])
        out['stage']='awaiting_techlead'
    except (ValueError,KeyError,TypeError):return out
    try:
        bundle,_=prepare(c,j,entry)
        out.update(stage='draft_pr_preflight_ready',selected=bundle['selected'])
    except (ValueError,PermissionError,KeyError,TypeError):pass
    return out
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--job-id',required=True)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('status')
    v=sub.add_parser('verify')
    v.add_argument('--profile',choices=['legacy','react-welcome-v1'],default='legacy')
    v.add_argument('--confirm',required=True)
    v.add_argument('--python-image',default=os.getenv('ORBIT_SANDBOX_PYTHON_IMAGE'))
    v.add_argument('--node-image',default=os.getenv('ORBIT_SANDBOX_NODE_IMAGE'))
    v.add_argument('--react-image',default=os.getenv('ORBIT_SANDBOX_REACT_IMAGE'))
    v.add_argument('--timeout',type=int,default=45)
    t=sub.add_parser('select')
    t.add_argument('--selected',choices=['A','B'],required=True)
    t.add_argument('--techlead',required=True)
    t.add_argument('--rationale',required=True)
    t.add_argument('--confirm',required=True)
    e=sub.add_parser('prepare')
    e.add_argument('--decision-output',type=Path,required=True)
    a=p.parse_args(argv)
    if not a.db.is_file():p.error('Database missing')
    try:
        with closing(sqlite3.connect(a.db,timeout=20)) as c:
            c.row_factory=sqlite3.Row
            if a.command=='status':
                print(json.dumps(state(c,cf.detail(c,a.job_id)),indent=2));return 0
            j=require_job(c,a.job_id)
            if a.command=='verify':
                if a.profile=='legacy':
                    report=vf.verify_job(j,python_image=a.python_image,node_image=a.node_image,approval=a.confirm,timeout=a.timeout)
                else:report=verify_react(j,image=a.react_image,approval=a.confirm,timeout=a.timeout)
                ref=vf.store_report(c,report);c.commit()
                print(json.dumps({'verification_id':ref,'gate':report['gate'],'verdict':report['verdict']}))
                return 0 if report['gate']=='PASS' else 2
            entry=latest(c,a.job_id)
            if a.command=='select':
                d=select(c,j,entry,selected=a.selected,techlead=a.techlead,rationale=a.rationale,confirmation=a.confirm)
                c.commit()
                print(json.dumps({'selected':d['selected'],'verification_id':d['verification_id'],'publish_allowed':False}));return 0
            bundle,d=prepare(c,j,entry)
            # Export only the decision, not executable code, to a new local file.
            with a.decision_output.open('x',encoding='utf-8') as f:json.dump(d,f,indent=2,ensure_ascii=False)
            print(json.dumps({'mode':'dry_run','selected':bundle['selected'],'files':[x['path'] for x in bundle['files']],'github_writes':False,'production_approved':False},indent=2));return 0
    except (ValueError,PermissionError,OSError,sqlite3.Error,KeyError,TypeError) as exc:
        print('P4 gate: '+str(exc),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
