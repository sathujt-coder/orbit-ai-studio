import sys,threading,time,unittest,sqlite3,tempfile,os,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from contextlib import contextmanager
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import concurrency_control as cc
import model_provider as mp
import usage_store as us
import resource_manager as rm

def lane(url='http://127.0.0.1:11434/v1',model='fixture'):
    return mp.Lane('A','ollama',url,model,'')

class ConcurrencyTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        p=cc.policy({});self.assertEqual((p['workers'],p['global_limit'],p['endpoint_limit']), (1,1,1))
        for env in ({'ORBIT_QUEUE_WORKERS':'9'},{'ORBIT_INFERENCE_GLOBAL':'0'},{'ORBIT_INFERENCE_MODEL':'2'},{'ORBIT_INFERENCE_WAITERS':'129'}):
            with self.assertRaises(ValueError):cc.policy(env)
    def test_alias_endpoint_and_distinct_ports(self):
        self.assertEqual(cc.endpoint(lane()),cc.endpoint(lane('http://localhost:11434/v1','other')))
        self.assertEqual(cc.endpoint(lane()),cc.endpoint(lane('http://[::1]:11434/v1')))
        self.assertNotEqual(cc.endpoint(lane()),cc.endpoint(lane('http://localhost:11435/v1')))
    def test_limits_and_release_after_exception(self):
        guard=cc.Limiter({'ORBIT_INFERENCE_GLOBAL':'2','ORBIT_INFERENCE_WAIT_SECONDS':'0'})
        with guard.acquire(lane(),'p'):
            with self.assertRaises(mp.ConcurrencyError):
                with guard.acquire(lane(model='other'),'q'):pass
            with self.assertRaises(mp.ConcurrencyError):
                with guard.acquire(lane('http://localhost:11435/v1'),'p'):pass
            with self.assertRaisesRegex(RuntimeError,'fixture'):
                with guard.acquire(lane('http://localhost:11435/v1'),'q'):
                    self.assertEqual(guard.snapshot()['active'],2);raise RuntimeError('fixture')
        s=guard.snapshot();self.assertEqual(s['active'],0);self.assertEqual(s['counts']['released'],2)
    def test_wait_queue_full_timeout_and_release(self):
        g=cc.Limiter({'ORBIT_INFERENCE_WAIT_SECONDS':'1','ORBIT_INFERENCE_WAITERS':'1'})
        errors=[]
        def wait():
            try:
                with g.acquire(lane(),'other'):pass
            except mp.ConcurrencyError as e:errors.append(str(e))
        with g.acquire(lane(),'p'):
            t=threading.Thread(target=wait);t.start()
            deadline=time.monotonic()+2
            while not g.snapshot()['waiting'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(g.snapshot()['waiting'],1)
            with self.assertRaisesRegex(mp.ConcurrencyError,'wait_queue_full'):
                with g.acquire(lane(),'third'):pass
            t.join(3);self.assertFalse(t.is_alive());self.assertIn('wait_timeout',errors[0])
        with g.acquire(lane(),'new'):pass
        self.assertEqual(g.snapshot()['active'],0)
    def test_eligible_waiter_skips_blocked_endpoint(self):
        g=cc.Limiter({'ORBIT_INFERENCE_GLOBAL':'2','ORBIT_INFERENCE_WAIT_SECONDS':'3'})
        got=threading.Event();done=threading.Event()
        def wait():
            with g.acquire(lane(),'q'):got.set()
            done.set()
        with g.acquire(lane(),'p'):
            t=threading.Thread(target=wait);t.start()
            deadline=time.monotonic()+1
            while not g.snapshot()['waiting'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(g.snapshot()['waiting'],1)
            with g.acquire(lane('http://localhost:11435/v1'),'r'):self.assertEqual(g.snapshot()['active'],2);self.assertFalse(got.is_set())
        self.assertTrue(done.wait(2));t.join();self.assertEqual(g.snapshot()['active'],0)
    def test_shutdown_wakes_waiters(self):
        g=cc.Limiter({'ORBIT_INFERENCE_WAIT_SECONDS':'5'})
        errors=[]
        def f():
            try:
                with g.acquire(lane(),'other'):pass
            except mp.ConcurrencyError as e:errors.append(str(e))
        with g.acquire(lane(),'p'):
            t=threading.Thread(target=f);t.start()
            deadline=time.monotonic()+1
            while not g.snapshot()['waiting'] and time.monotonic()<deadline:time.sleep(.01)
            g.close();t.join(2);self.assertFalse(t.is_alive());self.assertIn('closed',errors[0])
        self.assertEqual(g.snapshot()['active'],0)
    def test_refused_before_ledger_and_memory_failure_releases(self):
        g=cc.Limiter({'ORBIT_INFERENCE_WAIT_SECONDS':'0'});lock=threading.RLock()
        with sqlite3.connect(':memory:') as c:
            us.ensure_schema(c)
            with patch.object(mp,'chat') as chat:
                with g.acquire(lane(),'p'):
                    with self.assertRaises(mp.ConcurrencyError):
                        us.tracked_chat(lambda:c,lock,lane(),'s','u',project_id='q',agent_id='dev-A',purpose='test',concurrency_guard=g)
                with patch.object(rm.Manager,'admit',side_effect=mp.ResourceError('fixture')):
                    with self.assertRaises(mp.ResourceError):
                        us.tracked_chat(lambda:c,lock,lane(),'s','u',project_id='q',agent_id='dev-A',purpose='test',concurrency_guard=g,resource_guard=rm.Manager({}))
                chat.assert_not_called()
            self.assertEqual(c.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM ai_cost_basis').fetchone()[0],0)
        self.assertEqual(g.snapshot()['active'],0)
    def test_actual_http_overlap_global_limit_and_ledger(self):
        import json
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        lk=threading.Lock();state={'active':0,'peak':0,'calls':0};overlap=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                with lk:
                    state['active']+=1;state['peak']=max(state['peak'],state['active']);state['calls']+=1
                    if state['active']==2:overlap.set()
                try:
                    overlap.wait(3);time.sleep(.08)
                    raw=json.dumps({'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}}).encode()
                    self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                finally:
                    with lk:state['active']-=1
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        g=cc.Limiter({'ORBIT_INFERENCE_GLOBAL':'2','ORBIT_INFERENCE_ENDPOINT':'2','ORBIT_INFERENCE_MODEL':'2','ORBIT_INFERENCE_WAIT_SECONDS':'5'})
        try:
            with tempfile.TemporaryDirectory() as d:
                database=Path(d)/'u.sqlite';lock=threading.RLock()
                @contextmanager
                def conn():
                    c=sqlite3.connect(database,timeout=5);c.row_factory=sqlite3.Row
                    try:
                        with c:yield c
                    finally:c.close()
                with conn() as c:us.ensure_schema(c)
                l=mp.Lane('A','openai-compatible','http://127.0.0.1:'+str(server.server_port)+'/v1','fixture','',5)
                barrier=threading.Barrier(4)
                def invoke(i):
                    barrier.wait(5)
                    return us.tracked_chat(conn,lock,l,'s','u',project_id=str(i),agent_id='dev-A',purpose='test',concurrency_guard=g)
                with ThreadPoolExecutor(max_workers=4) as pool:self.assertEqual(list(pool.map(invoke,range(4))),['OK']*4)
                with conn() as c:self.assertEqual(us.summary(c,None,1,all_projects=True)['totals']['total_tokens'],12)
                self.assertEqual(state['peak'],2);self.assertEqual(state['calls'],4);self.assertEqual(g.snapshot()['active'],0);self.assertGreaterEqual(g.snapshot()['counts']['waited'],1)
        finally:server.shutdown();server.server_close();thread.join()
    def test_real_multiworker_dispatcher_project_isolation(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ,AI_COMPANY_DB=str(Path(d)/'queue.sqlite'),AI_PROVIDER='demo',AI_PROVIDER_A='demo',AI_PROVIDER_B='demo',ORBIT_QUEUE_WORKERS='2',PYTHONPATH=str(root/'backend'))
            script="""import server,auth_store,agent_queue,threading,time
server.init_db()
with server.db() as c:
    a=server.create_project('Concurrency A','Synthetic fixture project A','Web app',c)
    b=server.create_project('Concurrency B','Synthetic fixture project B','Web app',c)
    auth_store.create_user(c,'fixture','fixture-password-123')
    for pid in (a,b):auth_store.grant(c,'fixture',pid,'owner')
first=server.enqueue_pipeline(a,'fixture','next',9)
second=server.enqueue_coding(a,'fixture','Implement a synthetic web coding feature',8)
third=server.enqueue_pipeline(b,'fixture','next',7)
original=server.run_stage
barrier=threading.Barrier(2)
observed=[]
def stage(pid,sid,lanes,*,queue_id=None):
    with server.LOCK,server.db() as c:
        active=c.execute("SELECT project_id FROM agent_queue WHERE status='running'").fetchall()
        assert len({r[0] for r in active})==len(active)
    barrier.wait(5)
    with server.LOCK,server.db() as c:
        observed.append(c.execute("SELECT count(*) FROM agent_queue WHERE status='running'").fetchone()[0])
    return original(pid,sid,lanes,queue_id=queue_id)
server.run_stage=stage
workers=[threading.Thread(target=server.queue_worker) for _ in range(2)]
for t in workers:t.start()
try:
    end=time.monotonic()+15
    while time.monotonic()<end:
        with server.LOCK,server.db() as c:
            states=[r[0] for r in c.execute('SELECT status FROM agent_queue')]
        if states==['succeeded']*3:break
        time.sleep(.05)
    else:raise AssertionError(states)
    assert observed==[2,2],observed
finally:
    server.QUEUE_STOP.set();server.QUEUE_WAKE.set()
    for t in workers:t.join(5)
    assert not any(t.is_alive() for t in workers)
"""
            subprocess.run([sys.executable,'-c',script],env=env,check=True,timeout=30)
