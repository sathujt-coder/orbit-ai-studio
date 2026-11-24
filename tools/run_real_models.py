#!/usr/bin/env python3
"""Run independent model proposal/review workflow against an explicitly configured provider.
No Docker execution, no GitHub writes; verify and select separately with existing operator CLI."""
import argparse,json,os,re,sys,time,threading
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
def config(env):
    provider=env.get('AI_PROVIDER','demo')
    a=env.get('AI_MODEL_A','').strip();b=env.get('AI_MODEL_B','').strip()
    url=urlsplit(env.get('AI_BASE_URL','http://127.0.0.1:11434/v1'))
    if provider not in ('ollama','openai-compatible') or not a or not b or a==b:
        raise ValueError('Explicit real provider and two distinct model IDs required')
    if not url.hostname or url.username or url.password or url.query or url.fragment or (url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('localhost','127.0.0.1'))):
        raise ValueError('Use HTTPS provider URL or localhost HTTP')
    return {'provider':provider,'model_a':a,'model_b':b,'host':url.hostname}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--project',required=True)
    p.add_argument('--spec',required=True)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--confirm',default='')
    a=p.parse_args()
    try:
        cfg=config(os.environ)
        if not a.db.is_file():raise ValueError('Existing local DB required')
        if not a.execute:
            print(json.dumps({'mode':'preflight_no_model_calls',**cfg}));return 0
        if a.confirm!='RUN REAL MODELS '+a.project:raise ValueError('Explicit project confirmation required')
        os.environ['AI_COMPANY_DB']=str(a.db.resolve())
        import server,coding_factory
        done=threading.Event()
        def worker(jid,pid):
            try:coding_factory.work(server.db,server.LOCK,jid,pid,server.model_call,server.now,server.log,server.get_preceding)
            finally:done.set()
        jid=coding_factory.begin(server.db,server.LOCK,a.project,a.spec,server.uid,server.now,server.log,worker)
        print(json.dumps({'job_id':jid,**cfg}),flush=True)
        done.wait()
        with server.LOCK,server.db() as c:j=coding_factory.detail(c,jid)
        print(json.dumps({'job_id':jid,'status':j['status'],'reviews':[{k:r.get(k) for k in ('verdict','score')} for r in (j.get('review_a') or {},j.get('review_b') or {})],'sandbox_verified':False,'production_approved':False}))
        return 0 if j['status']=='ready' else 2
    except (ValueError,OSError) as e:
        print('Preflight failed: '+str(e),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
