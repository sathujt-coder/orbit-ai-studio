#!/usr/bin/env python3
"""24-agent real local client workload, short smoke or 24-hour dedicated soak."""
import argparse,os,sys,tempfile,time,threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from stress_common import Evidence,private_environment,require,integrity,latency

DURATION=86400
WAVE_INTERVAL=300
RSS_GROWTH_CAP=128*1024**2
def run(server,evidence,profile):
    import usage_store,cost_store,monitoring,model_provider
    # One synthetic project per department; all 24 registered agent IDs exercised.
    with server.db() as c:
        projects={s['id']:server.create_project('Soak '+s['id'],'Synthetic offline stress fixture','Web app',c) for s in server.STAGES}
    base=server.provider_snapshot()[1]
    require(model_provider.require_distinct_real(base) and all(v.provider=='ollama' and v.base_url=='http://127.0.0.1:11434/v1' and not v.api_key and 'cloud' not in v.model.lower() for v in base.values()),'non_local_lane')
    agents=sorted(server.AGENTS,key=lambda a:a['lane'])
    require(len(agents)==24 and len({a['id'] for a in agents})==24,'roster_mismatch')
    latencies=[];waves=0;requests=0;rss=[];wave_gaps=[];last_wave=None
    started=time.monotonic();deadline=started+(DURATION if profile=='soak24h' else 0)
    def invoke(a):
        begin=time.monotonic();pid=projects[a['dept']];run_id=server.uid()
        pair=server.route_pair(base,pid,run_id,a['dept'],'chat',40)
        call=server.snapshot_call(pair,project_id=pid,department=a['dept'],purpose='offline_stress',run_id=run_id)
        reply=call('Reply with exactly OK.','Synthetic load check. No tools.',a['lane'])
        require(bool(reply.strip()),'empty_response')
        return round((time.monotonic()-begin)*1000)
    with server.agent_queue.dispatcher_lock(server.DB_PATH):
        server.QUEUE_THREADS.extend(threading.Thread(target=server.queue_worker,name='soak-worker-'+str(i),daemon=True) for i in range(server.CONCURRENCY.policy['workers']))
        for worker in server.QUEUE_THREADS:worker.start()
        server.MONITOR.start(*server.monitor_args())
        try:
            with ThreadPoolExecutor(max_workers=4) as pool:
                while True:
                    wave_start=time.monotonic()
                    if last_wave is not None:wave_gaps.append(round(wave_start-last_wave,2))
                    last_wave=wave_start
                    # Group A then B to avoid needless switching on one-model Ollama.
                    for k in 'AB':latencies.extend(pool.map(invoke,[a for a in agents if a['lane']==k]))
                    waves+=1;requests+=24
                    cc=server.CONCURRENCY.snapshot()
                    require(cc['active']==cc['waiting']==0 and cc['counts']['acquired']==cc['counts']['released']==requests,'slot_leak_or_accounting')
                    require(not server.QUEUE_FAILED.is_set() and all(w.is_alive() for w in server.QUEUE_THREADS),'worker_failure')
                    # Observe a completed-wave sample from the real periodic collector, not an extra inference.
                    view=server.MONITOR.view()
                    require(view['sampler']['failures']==0,'sampler_failure')
                    metrics=server.RESOURCE_MANAGER.measure_fn();value=metrics['process_rss_bytes']
                    require(value is not None,'rss_unavailable')
                    rss.append(value)
                    require(value-rss[0]<=RSS_GROWTH_CAP,'post_warmup_rss_growth')
                    evidence.data.update(waves=waves,requests=requests,elapsed_seconds=round(time.monotonic()-started,2),
                        latency=latency(latencies),rss={'warmup_bytes':rss[0],'max_wave_end_bytes':max(rss),'last_bytes':rss[-1],'growth_cap_bytes':RSS_GROWTH_CAP},
                        max_wave_gap_seconds=max(wave_gaps,default=None),concurrency=cc)
                    evidence.save()
                    if profile=='smoke':break
                    # Fixed workload cadence with no catch-up burst. A long wave is a gate failure.
                    require(time.monotonic()-wave_start<=WAVE_INTERVAL,'wave_exceeded_cadence')
                    remaining=deadline-time.monotonic()
                    if remaining<=0:break
                    next_wave=wave_start+WAVE_INTERVAL
                    # Keep sampler running to actual deadline even after last scheduled wave.
                    if next_wave>=deadline:
                        time.sleep(max(0,remaining));break
                    time.sleep(max(0,next_wave-time.monotonic()))
            # Wait for a fresh collector sample following the last request.
            end=time.monotonic()+max(15,server.MONITOR.policy['interval_seconds']*3)
            while time.monotonic()<end:
                view=server.MONITOR.view()
                snap=view['snapshot']
                if snap and snap['pending_ledger']==0 and snap['usage_24h']['requests']>=24 and snap['concurrency']['counts']['released']==requests:break
                require(view['sampler']['failures']==0,'sampler_failure')
                time.sleep(.2)
            else:raise RuntimeError('final_monitor_sample_missing')
            require(view['sampler']['status']=='fresh' and len(snap['agents'])==24 and len(snap['models_24h'])==2,'monitor_final_gate')
            with server.LOCK,server.db() as c:
                # All-time totals: a rolling 24h window can legitimately exclude first-wave calls.
                ledger=dict(c.execute('SELECT status,count(*) FROM ai_usage GROUP BY status'))
                counts=dict(c.execute('SELECT agent_id,count(*) FROM ai_usage GROUP BY agent_id'))
                complete=c.execute("SELECT count(*) FROM ai_usage WHERE coverage='complete'").fetchone()[0]
                tokens=c.execute('SELECT sum(total_tokens) FROM ai_usage').fetchone()[0]
                cost=dict(c.execute('SELECT kind,count(*) FROM ai_cost_basis GROUP BY kind'))
                reservations=c.execute('SELECT count(*) FROM inference_reservations').fetchone()[0]
                denied=c.execute('SELECT count(*) FROM inference_denials').fetchone()[0]
                breakers=dict(c.execute('SELECT state,count(*) FROM inference_breakers GROUP BY state'))
                history=c.execute('SELECT count(*) FROM monitoring_samples').fetchone()[0]
                sampled_peak=c.execute("SELECT max(CAST(json_extract(snapshot,'$.rss_bytes') AS INTEGER)) FROM monitoring_samples").fetchone()[0]
                db_health=integrity(c)
            elapsed=time.monotonic()-started
            require(ledger=={'ok':requests} and complete==reservations==requests and tokens and denied==0 and breakers=={'closed':2} and cost=={'local_assumed_zero':requests},'ledger_cost_or_protection_gate')
            require(counts=={a['id']:waves for a in agents} and history>=2 and db_health=={'quick_check':'ok','foreign_key_violations':0},'agent_history_or_db_gate')
            require(server.MONITOR.view()['sampler']['failures']==0,'monitor_failure')
            cc=server.CONCURRENCY.snapshot()
            require(cc['active']==cc['waiting']==0 and 1<=cc['peak_active']<=2,'concurrency_gate')
            if profile=='soak24h':
                require(elapsed>=DURATION and waves>=DURATION//WAVE_INTERVAL and max(wave_gaps,default=0)<=WAVE_INTERVAL+10,'duration_or_cadence_gate')
            evidence.data.update(elapsed_seconds=round(elapsed,2),duration_gate='PASS' if profile=='soak24h' else 'NOT_RUN',
                ledger=ledger,complete_calls=complete,agent_counts=counts,tokens=tokens,local_assumed_zero_calls=cost['local_assumed_zero'],
                api_cost_usd='0.000000000000',denials=denied,breakers=breakers,reservations=reservations,history_samples=history,
                monitoring_status=view['sampler'],sampled_peak_backend_rss_bytes=sampled_peak,database=db_health)
        finally:
            server.QUEUE_STOP.set();server.QUEUE_WAKE.set();server.MONITOR.close()
            for worker in server.QUEUE_THREADS:worker.join(10)
            require(not any(w.is_alive() for w in server.QUEUE_THREADS),'worker_shutdown_timeout')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True);p.add_argument('--profile',choices=('smoke','soak24h'),default='smoke');p.add_argument('--confirm',required=True);a=p.parse_args()
    expected='RUN LOCAL 24H SOAK' if a.profile=='soak24h' else 'RUN LOCAL STRESS SMOKE'
    if a.confirm!=expected:p.error('Explicit '+expected+' required')
    evidence=Evidence(a.report,'orbit.offline-stress.v1',a.profile);ok=False
    try:
        with tempfile.TemporaryDirectory() as d:
            private_environment({'AI_COMPANY_DB':str(Path(d)/'offline-stress.sqlite'),'AI_PROVIDER':'ollama','AI_BASE_URL':'http://127.0.0.1:11434/v1',
                'AI_MODEL_A':'qwen2.5-coder:3b','AI_MODEL_B':'qwen2.5:3b','AI_TIMEOUT':'120',
                'ORBIT_QUEUE_WORKERS':'2','ORBIT_INFERENCE_GLOBAL':'2','ORBIT_INFERENCE_ENDPOINT':'2','ORBIT_INFERENCE_MODEL':'2',
                'ORBIT_INFERENCE_WAIT_SECONDS':'180','ORBIT_RESOURCE_MODE':'enforce','ORBIT_RESOURCE_MIN_FREE_MIB':'64','ORBIT_RESOURCE_MAX_MEMORY_PERCENT':'99',
                'ORBIT_BUDGET_MODE':'enforce','ORBIT_MONTHLY_GLOBAL_USD':'0','ORBIT_MAX_RUN_CALLS':'1',
                'ORBIT_MONITOR_INTERVAL':'5' if a.profile=='smoke' else '30','ORBIT_MONITOR_RETENTION_HOURS':'26','ORBIT_MONITOR_MAX_SAMPLES':'4000'})
            import server
            server.init_db();run(server,evidence,a.profile);ok=True
    except Exception as e:
        evidence.data['error_type']=type(e).__name__;evidence.data['reason']=str(e)[:200]
    return evidence.finish(ok)
if __name__=='__main__':raise SystemExit(main())
