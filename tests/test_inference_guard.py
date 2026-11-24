import sys,sqlite3,threading,unittest,tempfile,time,json
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import inference_guard as g,usage_store as u,model_provider as mp,cost_store as cost

class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');u.ensure_schema(self.c)
        self.local=mp.Lane('A','ollama',mp.DEFAULT_URL,'local-a','',context_window=4096,max_tokens=128)
        self.remote=mp.Lane('B','openai-compatible','https://fixture.invalid/v1','remote-b','',context_window=4096,max_tokens=128)
        self.now=int(time.time())
    def tearDown(self):self.c.close()
    def rate(self,lane,i=1000000,o=2000000):
        self.c.execute('INSERT INTO ai_rates(provider,endpoint_id,model,input_rate,output_rate,active,created_at,actor) VALUES(?,?,?,?,?,1,?,?)',(*g.key(lane),i,o,self.now,'fixture'))
    def start(self,guard,lane=None,project='p',agent='dev-A',run='r',now=None):
        lane=lane or self.local;plan=guard.check(self.c,lane,project,agent,run,128,now)
        identifier=u.start(self.c,lane,project,agent,'test',run);guard.reserve(self.c,identifier,lane,plan);return identifier
    def finish(self,guard,identifier,lane=None,status='ok',complete=True,now=None):
        lane=lane or self.local;event={'status':status,'coverage':'complete' if complete else 'unknown','input_tokens':100 if complete else None,'output_tokens':10 if complete else None,'total_tokens':110 if complete else None,'source':'fixture','elapsed_ms':1}
        u.finish(self.c,identifier,event);guard.finish(self.c,identifier,lane,event,now)
    def test_zero_budget_local_and_unknown_remote(self):
        guard=g.Guard({'ORBIT_BUDGET_MODE':'enforce','ORBIT_MONTHLY_GLOBAL_USD':'0'})
        i=self.start(guard);self.finish(guard,i)
        with self.assertRaisesRegex(mp.BudgetError,'unpriced_model'):self.start(guard,self.remote)
        self.rate(self.remote)
        with self.assertRaisesRegex(mp.BudgetError,'global_cost_limit'):self.start(guard,self.remote)
        self.assertEqual(g.totals(self.c,self.now)['accounted_picos'],0)
    def test_project_budget_reservation_and_settlement(self):
        self.rate(self.remote)
        self.c.execute('INSERT INTO ai_budgets VALUES(?,?,?,?,?)',('p',1,5000,self.now,'owner'))
        guard=g.Guard({'ORBIT_BUDGET_MODE':'enforce'})
        first=self.start(guard,self.remote)
        with self.assertRaisesRegex(mp.BudgetError,'project_cost_limit'):self.start(guard,self.remote)
        self.finish(guard,first,self.remote)
        second=self.start(guard,self.remote)
        self.finish(guard,second,self.remote,complete=False)
        t=g.totals(self.c,self.now,project='p',scope='project')
        self.assertEqual(t['held_picos'],4352000000);self.assertEqual(t['accounted_picos'],4472000000)
    def test_agent_global_token_and_run_limit(self):
        guard=g.Guard({'ORBIT_BUDGET_MODE':'enforce','ORBIT_MONTHLY_AGENT_TOKENS':'4300','ORBIT_MAX_RUN_CALLS':'1'})
        self.start(guard)
        with self.assertRaisesRegex(mp.BudgetError,'run_call_limit'):self.start(guard)
        with self.assertRaisesRegex(mp.BudgetError,'agent_token_limit'):self.start(guard,project='q',run='r2')
        self.start(guard,project='q',agent='dev-B',run='r3')
    def test_legacy_unknown_is_not_zero(self):
        u.start(self.c,self.remote,'p','dev-A','test','old')
        guard=g.Guard({'ORBIT_BUDGET_MODE':'enforce','ORBIT_MONTHLY_GLOBAL_USD':'0'})
        with self.assertRaisesRegex(mp.BudgetError,'global_cost_unknown'):self.start(guard)
    def test_observe_warning_and_price_snapshot(self):
        guard=g.Guard({'ORBIT_BUDGET_MODE':'observe','ORBIT_MONTHLY_GLOBAL_USD':'0'})
        i=self.start(guard,self.remote)
        self.assertIn('unpriced_model',self.c.execute('SELECT warning FROM inference_reservations WHERE usage_id=?',(i,)).fetchone()[0])
        self.rate(self.remote);self.finish(guard,i,self.remote)
        self.assertEqual(g.totals(self.c,self.now)['unknown_cost'],1)
    def test_circuit_open_cooldown_half_open_and_epoch(self):
        guard=g.Guard({'ORBIT_BREAKER_FAILURES':'2','ORBIT_BREAKER_COOLDOWN':'5'})
        old=self.start(guard)
        for n in range(2):
            i=self.start(guard);self.finish(guard,i,status='provider_error',complete=False,now=self.now)
        with self.assertRaisesRegex(mp.BudgetError,'circuit_open'):self.start(guard,now=self.now+4)
        probe=self.start(guard,now=self.now+5)
        with self.assertRaisesRegex(mp.BudgetError,'circuit_half_open_busy'):self.start(guard,now=self.now+6)
        self.finish(guard,old,now=self.now+6)
        self.assertEqual(self.c.execute('SELECT state FROM inference_breakers').fetchone()[0],'half_open')
        self.finish(guard,probe,now=self.now+6)
        self.assertEqual(self.c.execute('SELECT state FROM inference_breakers').fetchone()[0],'closed')
    def test_half_open_failure_and_restart_hold(self):
        guard=g.Guard({'ORBIT_BREAKER_FAILURES':'1','ORBIT_BREAKER_COOLDOWN':'5'})
        i=self.start(guard);self.finish(guard,i,status='provider_error',complete=False,now=self.now)
        p=self.start(guard,now=self.now+5);guard.recover(self.c,self.now+6)
        with self.assertRaisesRegex(mp.BudgetError,'circuit_open'):self.start(guard,now=self.now+10)
        self.assertEqual(g.totals(self.c,self.now)['held_calls'],2)
        self.assertEqual(self.c.execute("SELECT status FROM ai_usage WHERE id=?",(p,)).fetchone()[0],'pending')
    def test_emergency_persistent_revision_and_denial_no_ledger(self):
        env={'ORBIT_PROVIDER_ADMINS':'op'}
        body={'revision':0,'stopped':True,'confirmation':'STOP NEW INFERENCE'}
        with self.assertRaises(PermissionError):g.set_stop(self.c,'viewer',body,env)
        g.set_stop(self.c,'op',body,env)
        with self.assertRaises(ValueError):g.set_stop(self.c,'op',body,env)
        with patch.object(mp,'chat') as chat:
            with self.assertRaisesRegex(mp.BudgetError,'emergency_stop'):
                u.tracked_chat(lambda:self.c,threading.RLock(),self.local,'s','u',project_id='p',agent_id='dev-A',purpose='test',budget_guard=g.Guard({}))
            chat.assert_not_called()
        self.assertEqual(self.c.execute('SELECT count(*) FROM ai_usage').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT reason FROM inference_denials').fetchone()[0],'emergency_stop')
        self.assertFalse(g.set_stop(self.c,'op',{'revision':1,'stopped':False,'confirmation':'RESUME INFERENCE'},env)['stopped'])
    def test_real_http_failure_circuit_and_recovery(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        state={'calls':0,'fail':True}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']));state['calls']+=1
                if state['fail']:self.send_error(503);return
                raw=json.dumps({'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        lane=mp.Lane('A','openai-compatible','http://127.0.0.1:'+str(server.server_port)+'/v1','fixture','',5)
        guard=g.Guard({'ORBIT_BREAKER_FAILURES':'2','ORBIT_BREAKER_COOLDOWN':'1'})
        def call():return u.tracked_chat(lambda:self.c,threading.RLock(),lane,'s','u',project_id='p',agent_id='dev-A',purpose='test',budget_guard=guard)
        try:
            for n in range(2):
                with self.assertRaises(mp.ProviderError):call()
            with self.assertRaisesRegex(mp.BudgetError,'circuit_open'):call()
            self.assertEqual(state['calls'],2)
            self.c.execute("UPDATE inference_breakers SET open_until=0")
            state['fail']=False;self.assertEqual(call(),'OK')
            self.assertEqual(state['calls'],3);self.assertEqual(self.c.execute('SELECT state FROM inference_breakers').fetchone()[0],'closed')
        finally:server.shutdown();server.server_close();thread.join()
