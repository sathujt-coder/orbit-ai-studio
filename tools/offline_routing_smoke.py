#!/usr/bin/env python3
"""Real production routing selection and tracked inference; isolated synthetic project."""
import argparse,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
def candidate(identifier,model,caps,quality,provider='ollama',url='http://127.0.0.1:11434/v1'):
    return {'id':identifier,'settings':{'provider':provider,'url':url,'model':model,'timeout':120,'temperature':0.1,'context_window':8192,'max_tokens':128},'capabilities':caps,'quality':quality,'min_ram_mib':64 if provider=='ollama' else 0,'min_vram_mib':0,'min_cpu_cores':0}
def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--confirm',required=True);a=p.parse_args()
    if a.confirm!='RUN LOCAL ROUTING' or a.report.exists():p.error('Explicit confirmation and new report required')
    report={'schema':'orbit.offline-routing.v1','gate':'BLOCK'}
    try:
        with tempfile.TemporaryDirectory() as d:
            # Reverse configured defaults to prove registry selection changes them.
            os.environ.update(AI_COMPANY_DB=str(Path(d)/'routing.sqlite'),AI_PROVIDER='ollama',AI_PROVIDER_A='ollama',AI_PROVIDER_B='ollama',
                AI_BASE_URL='http://127.0.0.1:11434/v1',AI_BASE_URL_A='http://127.0.0.1:11434/v1',AI_BASE_URL_B='http://127.0.0.1:11434/v1',
                AI_MODEL_A='qwen2.5:3b',AI_MODEL_B='qwen2.5-coder:3b',AI_API_KEY='',AI_API_KEY_A='',AI_API_KEY_B='',
                ORBIT_ROUTING_MODE='smart',ORBIT_ROUTING_ALLOW_REMOTE='0',ORBIT_ROUTING_MAX_RATE_USD_PER_MILLION='0',
                ORBIT_PROVIDER_ENDPOINTS=json.dumps([{'provider':'openai-compatible','url':'https://routing-fixture.invalid/v1'}]),
                ORBIT_ROUTING_REGISTRY=json.dumps({'A':[candidate('local-code','qwen2.5-coder:3b',['coding','structured'],80),candidate('remote-blocked','remote-fixture',['coding','structured'],100,'openai-compatible','https://routing-fixture.invalid/v1')],
                    'B':[candidate('local-review','qwen2.5:3b',['general','structured'],75)]}))
            import server,usage_store,cost_store,model_routing
            server.init_db()
            with server.db() as c:pid=server.create_project('Routing smoke','Synthetic local routing fixture','Web app',c)
            run=server.uid();base=server.provider_snapshot()[1]
            selected=server.route_pair(base,pid,run,'dev','coding',100)
            call=server.snapshot_call(selected,project_id=pid,department='dev',purpose='routing_smoke',run_id=run)
            replies=[call('Reply with exactly OK.','Local routing test',k) for k in 'AB']
            with server.db() as c:
                history=model_routing.history(c,pid)
                totals=usage_store.summary(c,pid,1)['totals']
                costs=cost_store.summary(c,pid,1)['totals']
                actual=[dict(r) for r in c.execute('SELECT lane,model,status FROM ai_usage WHERE run_id=? ORDER BY rowid',(run,))]
            report.update(decision=history[0]['decision'],calls=actual,token_usage=totals,cost=costs,concurrency=server.CONCURRENCY.snapshot())
            if len(history)==1 and all(r.strip() for r in replies) and [(r['lane'],r['model'],r['status']) for r in actual]==[('A','qwen2.5-coder:3b','ok'),('B','qwen2.5:3b','ok')] and totals['complete_calls']==2 and costs['local_assumed_zero_calls']==2 and any(x['reason']=='remote_not_opted_in' for x in report['decision']['excluded']['A']):
                report['gate']='PASS'
    except Exception as e:report['error_type']=type(e).__name__
    finally:
        with a.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
        print(json.dumps(report,indent=2))
    return 0 if report['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
