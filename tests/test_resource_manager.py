import sqlite3,sys,threading,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import resource_manager as rm
import model_provider as mp
import usage_store as u
import auth_policy,auth_store,auth_http
class ResourceTests(unittest.TestCase):
    def reader(self,extra=None):
        d={'/proc/self/cgroup':'0::/work/child\n','/proc/self/mountinfo':'1 2 0:3 / /sys/fs/cgroup rw - cgroup2 cgroup rw',
           '/proc/meminfo':'MemTotal: 8388608 kB\nMemAvailable: 4194304 kB',
           '/proc/self/status':'VmRSS: 2048 kB',
           '/sys/fs/cgroup/work/child/memory.current':str(200*rm.MIB),
           '/sys/fs/cgroup/work/child/memory.max':str(1024*rm.MIB),
           '/sys/fs/cgroup/work/child/cpu.max':'200000 100000',
           '/sys/fs/cgroup/work/memory.current':str(900*rm.MIB),
           '/sys/fs/cgroup/work/memory.max':str(1024*rm.MIB),
           '/sys/fs/cgroup/work/cpu.max':'100000 100000',
           '/sys/fs/cgroup/memory.max':'max','/sys/fs/cgroup/cpu.max':'max 100000'}
        d.update(extra or {})
        return lambda p:d.get(str(p),'')
    def metrics(self,extra=None):return rm.measure(self.reader(extra),'Linux')
    def lane(self):return mp.Lane('A','ollama',mp.DEFAULT_URL,'fixture','')
    def test_cgroup_ancestor_effective_headroom_and_quota(self):
        m=self.metrics()
        self.assertEqual(m['effective_memory_available_bytes'],124*rm.MIB)
        self.assertEqual(m['cgroup']['memory_limit_bytes'],1024*rm.MIB)
        self.assertEqual(m['cgroup']['cpu_quota_cores'],1)
        self.assertEqual(m['process_rss_bytes'],2*rm.MIB)
    def test_incomplete_and_unsupported_metrics_are_unknown(self):
        m=self.metrics({'/sys/fs/cgroup/work/memory.current':''})
        self.assertIsNone(m['effective_memory_available_bytes'])
        self.assertEqual(rm.pressure(m,rm.policy({})),'memory_telemetry_unavailable')
        self.assertIsNone(rm.measure(self.reader(),'Darwin')['effective_memory_available_bytes'])
    def test_observe_and_enforce(self):
        a=rm.Manager({},self.metrics);a.admit(self.lane())
        self.assertEqual(a.snapshot()['admission']['would_block'],1)
        b=rm.Manager({'ORBIT_RESOURCE_MODE':'enforce'},self.metrics)
        with self.assertRaises(mp.ResourceError):b.admit(self.lane())
        self.assertEqual(b.snapshot()['admission']['blocked'],1)
        c=rm.Manager({'ORBIT_RESOURCE_MODE':'enforce','ORBIT_RESOURCE_MIN_FREE_MIB':'64'},self.metrics)
        c.admit(self.lane());self.assertEqual(c.snapshot()['admission']['allowed'],1)
    def test_blocked_call_does_not_enter_token_or_cost_ledger(self):
        manager=rm.Manager({'ORBIT_RESOURCE_MODE':'enforce'},self.metrics)
        with sqlite3.connect(':memory:') as c:
            u.ensure_schema(c)
            with patch.object(mp,'chat') as chat:
                with self.assertRaises(mp.ResourceError):u.tracked_chat(lambda:c,threading.RLock(),self.lane(),'s','u',project_id='p',agent_id='dev-A',purpose='test',resource_guard=manager)
                chat.assert_not_called()
            self.assertEqual(c.execute('SELECT count(*) FROM ai_usage').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM ai_cost_basis').fetchone()[0],0)
    def test_policy_validation_and_gpu_unknown(self):
        for env in ({'ORBIT_RESOURCE_MODE':'bad'},{'ORBIT_RESOURCE_MIN_FREE_MIB':'0'},{'ORBIT_RESOURCE_MAX_MEMORY_PERCENT':'101'}):
            with self.assertRaises(ValueError):rm.policy(env)
        with patch.object(rm.shutil,'which',return_value=None):
            self.assertEqual(rm.gpu_snapshot()['status'],'unavailable')
    def test_local_model_status_no_remote_requests(self):
        with patch.object(rm.urllib.request,'build_opener') as opener:
            self.assertEqual(rm.loaded_models(mp.Lane('A','ollama','https://remote.example/v1','x',''))['status'],'not_local_ollama')
            opener.assert_not_called()
    def test_resource_api_admin_only(self):
        with sqlite3.connect(':memory:') as c:
            auth_store.ensure_schema(c);auth_store.create_user(c,'operator','fixture-password-123');auth_store.create_user(c,'viewer','fixture-password-123')
            with patch.dict('os.environ',{'ORBIT_PROVIDER_ADMINS':'operator'}):
                for user,expected in [('operator',200),('viewer',403)]:
                    token=auth_store.login(c,user,'fixture-password-123')
                    headers={'Cookie':auth_http.COOKIE+'='+token,'Origin':'http://127.0.0.1:8787','X-ORBIT-CSRF':auth_http.csrf_for(token)}
                    self.assertEqual(auth_policy.check(c,'GET','/api/provider/resources','',{},headers,8787)[0],expected)
                    self.assertEqual(auth_policy.check(c,'POST','/api/provider/resources/models','',{},headers,8787)[0],expected)
                self.assertEqual(auth_policy.check(c,'GET','/api/provider/resources','',{}, {},8787)[0],401)

    def test_private_cgroup_namespace_and_missing_controller(self):
        m=self.metrics({'/proc/self/cgroup':'0::/','/proc/self/mountinfo':'1 2 0:3 /docker/fixture /sys/fs/cgroup rw - cgroup2 cgroup rw',
                        '/sys/fs/cgroup/memory.max':str(512*rm.MIB),'/sys/fs/cgroup/memory.current':str(256*rm.MIB)})
        self.assertEqual(m['effective_memory_available_bytes'],256*rm.MIB)
        m=self.metrics({'/proc/self/cgroup':'0::/','/sys/fs/cgroup/memory.max':'','/sys/fs/cgroup/memory.current':''})
        self.assertIsNone(m['effective_memory_available_bytes'])
    def test_gpu_parsing_and_bounded_command(self):
        from subprocess import CompletedProcess
        with patch.object(rm.shutil,'which',return_value='/fixture/nvidia-smi'),patch.object(rm.subprocess,'run',return_value=CompletedProcess([],0,'0, 8192, 4096, 25\n1, 1024, 2048, 50\nbad\n','')) as run:
            g=rm.gpu_snapshot()
            self.assertEqual(g['status'],'available')
            self.assertEqual(g['devices'],[{'index':0,'vram_total_bytes':8192*rm.MIB,'vram_used_bytes':4096*rm.MIB,'utilization_percent':25}])
            self.assertEqual(run.call_args.kwargs['timeout'],3)
            self.assertNotIn('shell',run.call_args.kwargs)
    def test_actual_http_model_metadata(self):
        import json
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append((self.path,self.headers.get('Authorization')))
                raw=json.dumps({'models':[{'name':'fixture:3b','size':1000,'size_vram':0,'context_length':8192,'digest':'do-not-return'}]}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            lane=mp.Lane('A','ollama','http://127.0.0.1:'+str(server.server_port)+'/v1','fixture:3b','fixture-secret')
            self.assertEqual(rm.loaded_models(lane),{'status':'available','models':[{'model':'fixture:3b','size_bytes':1000,'size_vram_bytes':0,'context_length':8192}]})
            self.assertEqual(seen,[('/api/ps','Bearer fixture-secret')])
        finally:
            server.shutdown();server.server_close();worker.join()
