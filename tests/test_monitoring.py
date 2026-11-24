import sys,os,sqlite3,tempfile,threading,time,unittest,json,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import monitoring as m,auth_policy,usage_store as u,model_provider as mp,inference_guard as g
from contextlib import contextmanager

class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');u.ensure_schema(self.c);m.ensure_schema(self.c);self.c.commit()
        self.p=m.policy({});self.now=int(time.time())
    def tearDown(self):self.c.close()
    def point(self,now=None,alerts=None):
        return {'sampled_at':self.now if now is None else now,'boot_id':'fixture','resources':{'metrics':{'process_cpu_percent':None,'process_rss_bytes':100,'effective_memory_available_bytes':None,'cgroup':{'memory_current_bytes':None,'memory_limit_bytes':None}},'gpu':{'devices':[]}},'concurrency':{'active':1,'waiting':0},'queue':{'counts':{'queued':2,'running':1}},'usage_24h':{'total_tokens':None},'cost_24h':{'total_usd':None},'protection':{'totals':{'held_tokens':10}},'alerts':alerts or []}
    def test_policy_validation(self):
        self.assertEqual(self.p['interval_seconds'],30)
        for env in ({'ORBIT_MONITOR_INTERVAL':'0'},{'ORBIT_MONITOR_MAX_SAMPLES':'10081'},{'ORBIT_MONITOR_RETENTION_HOURS':'169'}):
            with self.assertRaises(ValueError):m.policy(env)
    def test_history_bounds_retention_and_nulls(self):
        p=dict(self.p,max_samples=60,retention_hours=1)
        m.persist(self.c,self.point(self.now-3700),p)
        for i in range(70):m.persist(self.c,self.point(self.now-70+i),p)
        h=m.history(self.c,self.now,1,10)
        self.assertEqual(h['stored_points'],60);self.assertEqual(len(h['points']),10);self.assertTrue(h['downsampled'])
        self.assertEqual(h['points'][0]['sampled_at'],self.now-60);self.assertEqual(h['points'][-1]['sampled_at'],self.now-1)
        self.assertIsNone(h['points'][0]['cpu_percent']);self.assertIsNone(h['points'][0]['gpu_max_utilization_percent'])
        self.assertEqual(self.c.execute('SELECT count(*) FROM monitoring_samples').fetchone()[0],60)
        with self.assertRaises(ValueError):m.history(self.c,self.now,2,10)
    def test_alert_transitions_deduplicated_and_resolved(self):
        a=[m.alert('queue_wait','warning','fixture')]
        m.persist(self.c,self.point(self.now-3,a),self.p)
        m.persist(self.c,self.point(self.now-2,a),self.p)
        m.persist(self.c,self.point(self.now-1,[]),self.p)
        self.assertEqual([r['transition'] for r in m.history(self.c,self.now,1,10)['events']],['resolved','raised'])
    def test_stale_no_sample_and_failed_sample(self):
        monitor=m.Monitor({})
        self.assertEqual(monitor.view()['sampler']['status'],'stale')
        monitor.latest=self.point(self.now)
        self.assertEqual(monitor.view(self.now)['sampler']['status'],'fresh')
        self.assertEqual(monitor.view(self.now+91)['sampler']['status'],'stale')
        monitor.last_error_at=self.now
        self.assertEqual(monitor.view(self.now)['sampler']['status'],'stale')
    def test_scope_operator_only(self):
        for path in ('/api/provider/monitoring','/api/provider/monitoring/history'):
            self.assertEqual(auth_policy.scope(self.c,'GET',path),('','provider_monitoring_read'))
            self.assertIsNone(auth_policy.scope(self.c,'POST',path))
    def test_sampler_failure_and_recovery(self):
        monitor=m.Monitor({'ORBIT_MONITOR_INTERVAL':'5'})
        def broken(*args):raise RuntimeError('fixture')
        monitor.sample=broken;monitor.start()
        try:
            end=time.monotonic()+2
            while not monitor.view()['sampler']['failures'] and time.monotonic()<end:time.sleep(.01)
            self.assertEqual(monitor.view()['sampler']['failures'],1)
            self.assertEqual(monitor.view()['sampler']['status'],'stale')
        finally:monitor.close()
        self.assertFalse(monitor.view()['sampler']['running'])
    def test_actual_server_collect_and_no_inference(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ,AI_COMPANY_DB=str(Path(d)/'monitor.sqlite'),AI_PROVIDER='demo',AI_PROVIDER_A='demo',AI_PROVIDER_B='demo',PYTHONPATH=str(root/'backend'))
            script="""import server,monitoring,usage_store,model_provider,inference_guard,time
from unittest.mock import patch
server.init_db()
with server.db() as c:
    pid=server.create_project('Monitor fixture','Synthetic monitoring fixture','Web app',c)
    lane=model_provider.Lane('A','ollama',model_provider.DEFAULT_URL,'fixture','')
    uid=usage_store.start(c,lane,pid,'dev-A','test','run')
    usage_store.finish(c,uid,{'status':'ok','coverage':'complete','input_tokens':2,'output_tokens':3,'total_tokens':5,'source':'fixture','elapsed_ms':1})
    usage_store.start(c,lane,pid,'dev-B','test','run')
    inference_guard.deny(c,pid,'dev-A','run','run_call_limit')
with patch.object(model_provider,'chat') as chat:
    snapshot=server.MONITOR.sample(*server.monitor_args())
    chat.assert_not_called()
assert len(snapshot['agents'])==24
assert snapshot['usage_24h']['requests']==2 and snapshot['usage_24h']['total_tokens']==5
assert snapshot['pending_ledger']==1 and snapshot['recent_denials']==1
assert next(a for a in snapshot['agents'] if a['id']=='dev-B')['pending_ledger']==1
assert 'recent_denials' in [a['code'] for a in snapshot['alerts']]
with server.db() as c:
    h=monitoring.history(c,int(time.time()),1,10)
    assert len(h['points'])==1
    assert h['points'][0]['tokens_24h']==5
    assert c.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0]==2
    assert 'fixture-password' not in c.execute('SELECT snapshot FROM monitoring_samples').fetchone()[0]
"""
            subprocess.run([sys.executable,'-c',script],env=env,check=True,timeout=20)
