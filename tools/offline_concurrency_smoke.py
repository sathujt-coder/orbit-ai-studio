#!/usr/bin/env python3
"""Three real local client requests, bounded two client slots; no cloud/API."""
import argparse,json,sys,tempfile,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model_provider as mp
import concurrency_control as cc
import resource_manager as rm
import usage_store as us
import sqlite3
from contextlib import contextmanager

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True);p.add_argument('--confirm',required=True)
    a=p.parse_args()
    if a.confirm!='RUN LOCAL CONCURRENCY':p.error('Explicit RUN LOCAL CONCURRENCY required')
    if a.report.exists():p.error('Report must be new')
    report={'schema':'orbit.offline-concurrency.v1','gate':'BLOCK','note':'Two concurrent client admissions; Ollama may serialize GPU/CPU execution internally.'}
    try:
        manager=cc.Limiter({'ORBIT_INFERENCE_GLOBAL':'2','ORBIT_INFERENCE_ENDPOINT':'2','ORBIT_INFERENCE_MODEL':'2','ORBIT_INFERENCE_WAIT_SECONDS':'180'})
        resource=rm.Manager({'ORBIT_RESOURCE_MODE':'enforce','ORBIT_RESOURCE_MIN_FREE_MIB':'64','ORBIT_RESOURCE_MAX_MEMORY_PERCENT':'99'})
        lane=mp.Lane('A','ollama','http://127.0.0.1:11434/v1','qwen2.5:3b','',120)
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/'usage.sqlite';lock=threading.RLock()
            @contextmanager
            def conn():
                c=sqlite3.connect(db,timeout=15);c.row_factory=sqlite3.Row
                try:
                    with c:yield c
                finally:c.close()
            with conn() as c:us.ensure_schema(c)
            start=threading.Barrier(3)
            def request(i):
                start.wait(10)
                before=time.monotonic()
                try:
                    reply=us.tracked_chat(conn,lock,lane,'Reply with exactly OK.','Local concurrency check',project_id='fixture-'+str(i),agent_id='dev-A',purpose='concurrency_smoke',resource_guard=resource,concurrency_guard=manager,max_tokens=64,runtime_settings=True)
                    return {'slot':i,'status':'ok','nonempty':bool(reply.strip()),'elapsed_ms':round((time.monotonic()-before)*1000)}
                except Exception as e:return {'slot':i,'status':'failed','error_type':type(e).__name__}
            with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(request,range(3)))
            with conn() as c:totals=us.summary(c,None,1,all_projects=True)['totals']
            snap=manager.snapshot()
            report.update(results=results,concurrency=snap,token_usage=totals,resource=resource.snapshot()['admission'])
            if all(r['status']=='ok' and r['nonempty'] for r in results) and snap['peak_active']==2 and snap['peak_waiting']>=1 and snap['active']==snap['waiting']==0 and snap['counts']['acquired']==snap['counts']['released']==3 and totals['requests']==totals['complete_calls']==3:
                report['gate']='PASS'
    except Exception as e:report['error_type']=type(e).__name__
    finally:
        with a.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
        print(json.dumps(report,indent=2))
    return 0 if report['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
