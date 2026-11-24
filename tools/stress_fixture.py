#!/usr/bin/env python3
"""P5.9 real worker pool, SQLite crash recovery and loopback HTTP failure stress."""
import argparse,json,os,sys,tempfile,threading,time,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from stress_common import Evidence,private_environment,require,integrity

def queue_stress(server,auth,queue):
    with server.db() as c:
        auth.create_user(c,'stress-owner','synthetic-stress-password')
        pids=[server.create_project('Stress '+str(i),'Synthetic load fixture only','Web app',c) for i in range(queue.MAX_QUEUED+1)]
        for pid in pids:auth.grant(c,'stress-owner',pid,'owner')
    ids=[server.enqueue_pipeline(pid,'stress-owner','next',i%10) for i,pid in enumerate(pids[:-1])]
    try:server.enqueue_pipeline(pids[-1],'stress-owner','next')
    except ValueError as e:require(str(e)=='Queue capacity reached','unexpected queue refusal')
    else:raise RuntimeError('queue_capacity_not_enforced')
    # A separate process durably claims two jobs, then is killed before execution.
    script="""import server,agent_queue,time
with agent_queue.dispatcher_lock(server.DB_PATH):
    with server.LOCK,server.db() as c:
        for _ in range(2):
            row=agent_queue.claim(c,int(time.time()),server.now())
            assert row
            c.execute("UPDATE tasks SET status='drafting' WHERE project_id=? AND stage_id='po'",(row['project_id'],))
    time.sleep(90)
"""
    child=subprocess.Popen([sys.executable,'-c',script],env=dict(os.environ,PYTHONPATH=str(Path(server.__file__).parent)),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            with server.db() as c:claimed=c.execute("SELECT id FROM agent_queue WHERE status='running'").fetchall()
            if len(claimed)==2:break
            require(child.poll() is None,'claim_process_exited')
            time.sleep(.05)
        else:raise RuntimeError('claim_timeout')
        interrupted={r[0] for r in claimed};child.kill();child.wait(timeout=5)
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=5)
    peak=0;started=time.monotonic()
    with queue.dispatcher_lock(server.DB_PATH):
        with server.LOCK,server.db() as c:
            queue.recover(c,int(time.time()),server.now());server.BUDGET_GUARD.recover(c)
        server.QUEUE_THREADS.extend(threading.Thread(target=server.queue_worker,name='stress-worker-'+str(i),daemon=True) for i in range(8))
        for worker in server.QUEUE_THREADS:worker.start()
        server.MONITOR.start(*server.monitor_args())
        try:
            while time.monotonic()-started<180:
                with server.LOCK,server.db() as c:
                    states=dict(c.execute('SELECT status,count(*) FROM agent_queue GROUP BY status'))
                    running=c.execute("SELECT project_id FROM agent_queue WHERE status='running'").fetchall()
                require(len({r[0] for r in running})==len(running),'project_double_dispatch')
                peak=max(peak,len(running))
                require(not server.QUEUE_FAILED.is_set(),'dispatcher_failed')
                if states.get('succeeded',0)==len(ids)-2:break
                require(not states.get('dead',0),'unexpected_dead_task')
                time.sleep(.1)
            else:raise RuntimeError('queue_drain_timeout')
            sample=server.MONITOR.view()
            require(sample['sampler']['failures']==0 and sample['snapshot'] is not None,'monitor_failed_under_load')
        finally:
            server.QUEUE_STOP.set();server.QUEUE_WAKE.set();server.MONITOR.close()
            for worker in server.QUEUE_THREADS:worker.join(10)
        require(not any(w.is_alive() for w in server.QUEUE_THREADS),'worker_shutdown_timeout')
        with server.LOCK,server.db() as c:
            states=dict(c.execute('SELECT status,count(*) FROM agent_queue GROUP BY status'))
            require(states=={'interrupted':2,'succeeded':len(ids)-2},'queue_terminal_mismatch')
            recovered=c.execute("SELECT q.id,q.attempts,t.status FROM agent_queue q JOIN tasks t ON t.project_id=q.project_id AND t.stage_id='po' WHERE q.status='interrupted'").fetchall()
            require({r[0] for r in recovered}==interrupted and all(r[1]==1 and r[2]=='needs_revision' for r in recovered),'uncertain_work_replayed')
            require(c.execute("SELECT count(*) FROM agent_queue WHERE status='succeeded' AND attempts!=1").fetchone()[0]==0,'duplicate_dispatch')
            require(c.execute("SELECT count(*) FROM artifacts WHERE kind='final'").fetchone()[0]==len(ids)-2,'final_artifact_count')
            samples=c.execute('SELECT count(*) FROM monitoring_samples').fetchone()[0]
            health=integrity(c)
    require(2<=peak<=8 and samples>=2 and health=={'quick_check':'ok','foreign_key_violations':0},'queue_or_database_gate')
    return {'accepted':len(ids),'capacity_refusals':1,'peak_running_sampled':peak,'states':states,'elapsed_seconds':round(time.monotonic()-started,2),
            'monitor_samples':samples,'database':health,'crash_process_killed':True,'interrupted_replayed':0},pids[:24]

def http_stress(server,mp,usage,guard_module,pids):
    state={'calls':0,'active':0,'peak':0,'fail':True,'hold':False}
    lock=threading.Lock();entered=threading.Event();release=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            with lock:
                state['calls']+=1;state['active']+=1;state['peak']=max(state['peak'],state['active'])
                fail,hold=state['fail'],state['hold']
            try:
                if fail:self.send_error(503);return
                if hold:
                    entered.set()
                    if not release.wait(15):self.send_error(503);return
                time.sleep(.06)
                raw=json.dumps({'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            finally:
                with lock:state['active']-=1
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    lane=mp.Lane('A','openai-compatible','http://127.0.0.1:'+str(http.server_port)+'/v1','stress-fixture','',20,max_tokens=64)
    guard=server.BUDGET_GUARD
    with server.db() as c:
        c.execute('INSERT INTO ai_rates(provider,endpoint_id,model,input_rate,output_rate,active,created_at,actor) VALUES(?,?,?,?,?,1,?,?)',(*guard_module.key(lane),0,0,int(time.time()),'fixture'))
    def invoke(i,model=lane):
        try:
            result=usage.tracked_chat(server.db,server.LOCK,model,'Reply OK.','Synthetic fixture',project_id=pids[i%24],agent_id=server.AGENTS[i%24]['id'],purpose='stress_fixture',run_id=server.uid(),concurrency_guard=server.CONCURRENCY,budget_guard=guard)
            return 'ok' if result=='OK' else 'invalid_reply'
        except mp.BudgetError as e:return str(e)
        except mp.ProviderError:return 'provider_error'
    try:
        require([invoke(0),invoke(1)]==['provider_error']*2,'failure_injection_failed')
        with ThreadPoolExecutor(max_workers=24) as pool:
            blocked=list(pool.map(invoke,range(24)))
        require(blocked==['circuit_open']*24 and state['calls']==2,'circuit_open_load_gate')
        # Wait actual configured cooldown, then hold the sole half-open request.
        time.sleep(guard.policy['cooldown_seconds']+1)
        with lock:state['fail']=False;state['hold']=True
        with ThreadPoolExecutor(max_workers=24) as pool:
            probe=pool.submit(invoke,0)
            try:
                require(entered.wait(5),'half_open_probe_missing')
                half=list(pool.map(invoke,range(1,24)))
                require(half==['circuit_half_open_busy']*23 and state['calls']==3,'half_open_exclusivity')
            finally:release.set()
            require(probe.result(5)=='ok','half_open_recovery_failed')
        with lock:state['hold']=False
        with ThreadPoolExecutor(max_workers=24) as pool:healthy=list(pool.map(invoke,range(24)))
        require(healthy==['ok']*24,'healthy_load_failed')
        # No network request to this unpriced candidate: budget guard rejects it.
        remote=mp.Lane('B','openai-compatible','https://stress-fixture.invalid/v1','unpriced','',5,max_tokens=64)
        require(invoke(0,remote)=='unpriced_model','unpriced_candidate_not_blocked')
        with server.db() as c:
            ledger=dict(c.execute('SELECT status,count(*) FROM ai_usage GROUP BY status'))
            denials=dict(c.execute('SELECT reason,count(*) FROM inference_denials GROUP BY reason'))
            breaker=c.execute('SELECT state FROM inference_breakers WHERE model=?',(lane.model,)).fetchone()[0]
            health=integrity(c)
        cc=server.CONCURRENCY.snapshot()
        require(state['calls']==27 and 1<=state['peak']<=2 and ledger=={'ok':25,'provider_error':2} and denials=={'circuit_open':24,'circuit_half_open_busy':23,'unpriced_model':1} and breaker=='closed' and cc['active']==cc['waiting']==0 and cc['counts']['acquired']==cc['counts']['released'] and health=={'quick_check':'ok','foreign_key_violations':0},'http_stress_gate')
        return {'http_calls':state['calls'],'peak_http_requests':state['peak'],'ledger':ledger,'denials':denials,'breaker':breaker,'concurrency':cc,'database':health}
    finally:release.set();http.shutdown();http.server_close();thread.join()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True);p.add_argument('--confirm',required=True);a=p.parse_args()
    if a.confirm!='RUN ISOLATED STRESS FIXTURE':p.error('Explicit confirmation required')
    evidence=Evidence(a.report,'orbit.stress-fixture.v1','fixture');ok=False
    try:
        with tempfile.TemporaryDirectory() as d:
            private_environment({'AI_COMPANY_DB':str(Path(d)/'stress.sqlite'),'AI_PROVIDER':'demo','ORBIT_QUEUE_WORKERS':'8','ORBIT_MONITOR_INTERVAL':'5',
                'ORBIT_INFERENCE_GLOBAL':'2','ORBIT_INFERENCE_ENDPOINT':'2','ORBIT_INFERENCE_MODEL':'2','ORBIT_INFERENCE_WAIT_SECONDS':'60',
                'ORBIT_BUDGET_MODE':'enforce','ORBIT_MONTHLY_GLOBAL_USD':'0','ORBIT_BREAKER_FAILURES':'2','ORBIT_BREAKER_COOLDOWN':'5'})
            import server,auth_store,agent_queue,model_provider,usage_store,inference_guard
            server.init_db()
            evidence.data['queue'],pids=queue_stress(server,auth_store,agent_queue);evidence.save()
            evidence.data['http']=http_stress(server,model_provider,usage_store,inference_guard,pids);ok=True
    except Exception as e:
        evidence.data['error_type']=type(e).__name__;evidence.data['reason']=str(e)[:200]
    return evidence.finish(ok)
if __name__=='__main__':raise SystemExit(main())
