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
