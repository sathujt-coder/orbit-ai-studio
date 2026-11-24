#!/usr/bin/env python3
"""Real offline inference with enforced zero-dollar cap, token and stop gate."""
import argparse,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--confirm',required=True);a=p.parse_args()
    if a.confirm!='RUN LOCAL BUDGET' or a.report.exists():p.error('Explicit confirmation and new report required')
    report={'schema':'orbit.offline-budget.v1','gate':'BLOCK'}
    try:
        with tempfile.TemporaryDirectory() as d:
            os.environ.update(AI_COMPANY_DB=str(Path(d)/'budget.sqlite'),AI_PROVIDER='ollama',AI_PROVIDER_A='ollama',AI_PROVIDER_B='ollama',AI_MODEL_A='qwen2.5-coder:3b',AI_MODEL_B='qwen2.5:3b',AI_BASE_URL='http://127.0.0.1:11434/v1',AI_BASE_URL_A='http://127.0.0.1:11434/v1',AI_BASE_URL_B='http://127.0.0.1:11434/v1',AI_API_KEY='',AI_API_KEY_A='',AI_API_KEY_B='',ORBIT_BUDGET_MODE='enforce',ORBIT_MONTHLY_GLOBAL_USD='0',ORBIT_MAX_RUN_CALLS='1',ORBIT_PROVIDER_ADMINS='fixture')
            import server,model_provider as mp,inference_guard as g,usage_store,cost_store
            server.init_db()
            with server.db() as c:pid=server.create_project('Budget fixture','Synthetic offline protection fixture','Web app',c)
            lanes=server.provider_snapshot()[1];run=server.uid()
            call=server.snapshot_call(lanes,project_id=pid,department='dev',purpose='budget_smoke',run_id=run)
            reply=call('Reply exactly OK.','Local budget check','A')
            denied=[]
            def attempt(fn):
                try:fn()
                except mp.BudgetError as e:denied.append(str(e))
            attempt(lambda:call('Reply OK.','Run limit check','B'))
            with server.db() as c:g.set_stop(c,'fixture',{'revision':0,'stopped':True,'confirmation':'STOP NEW INFERENCE'},os.environ)
            next_call=server.snapshot_call(lanes,project_id=pid,department='dev',purpose='budget_smoke',run_id=server.uid())
            attempt(lambda:next_call('Reply OK.','Stop check','B'))
            with server.db() as c:g.set_stop(c,'fixture',{'revision':1,'stopped':False,'confirmation':'RESUME INFERENCE'},os.environ)
            second=next_call('Reply exactly OK.','Resume check','B')
            with server.db() as c:
                data=server.BUDGET_GUARD.view(c,all_projects=True);usage=usage_store.summary(c,pid,1)['totals'];costs=cost_store.summary(c,pid,1)['totals']
            report.update(protection=data,denied=denied,token_usage=usage,cost=costs,concurrency=server.CONCURRENCY.snapshot())
            if reply.strip() and second.strip() and denied==['run_call_limit','emergency_stop'] and usage['requests']==usage['complete_calls']==2 and costs['local_assumed_zero_calls']==2 and data['totals']['held_calls']==0 and not data['stopped'] and len(data['breakers'])==2 and all(b['state']=='closed' for b in data['breakers']):
                report['gate']='PASS'
    except Exception as e:report['error_type']=type(e).__name__;report['error']=str(e) if type(e).__name__ in ('BudgetError','ResourceError','ProviderError') else 'see CI tests'
    finally:
        with a.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
        print(json.dumps(report,indent=2))
    return 0 if report['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
