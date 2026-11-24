import sys,sqlite3,unittest,json,os,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model_routing as r,model_provider as mp,cost_store,usage_store,agent_queue,auth_policy,auth_store,auth_http

def candidate(identifier,model,caps=('general','structured'),quality=80,ram=0,vram=0,cpu=0,provider='ollama',url=mp.DEFAULT_URL,ctx=8192):
    return {'id':identifier,'settings':{'provider':provider,'url':url,'model':model,'timeout':5,'temperature':0.1,'context_window':ctx,'max_tokens':128},
            'capabilities':list(caps),'quality':quality,'min_ram_mib':ram,'min_vram_mib':vram,'min_cpu_cores':cpu}
def config(a,b,remote='0',cap='0'):
    return {'ORBIT_ROUTING_MODE':'smart','ORBIT_ROUTING_ALLOW_REMOTE':remote,'ORBIT_ROUTING_MAX_RATE_USD_PER_MILLION':cap,
            'ORBIT_PROVIDER_ENDPOINTS':json.dumps([{'provider':'openai-compatible','url':'https://fixture.invalid/v1','key_env':'ORBIT_PROVIDER_KEY_TEST'}]),
            'ORBIT_PROVIDER_KEY_TEST':'secret-never-return','ORBIT_ROUTING_REGISTRY':json.dumps({'A':a,'B':b})}
class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        usage_store.ensure_schema(self.c);r.ensure_schema(self.c)
        self.base=mp.load_config({'AI_PROVIDER':'ollama','AI_MODEL_A':'base-a','AI_MODEL_B':'base-b'})
        self.b=candidate('b','review-b');self.task=r.classify('dev','coding',10)
        self.metrics={'effective_memory_available_bytes':2048*r.MIB,'effective_cpu_cores':2}
    def tearDown(self):self.c.close()
    def choose(self,a,b=None,remote='0',cap='0',metrics=None,gpu=None,task=None):
        cfg=r.load(config(a,b or [self.b],remote,cap),self.base)
        return r.select(self.c,cfg,self.base,task or self.task,self.metrics if metrics is None else metrics,gpu)
    def remote(self):return candidate('remote','remote-x',('coding','structured'),100,provider='openai-compatible',url='https://fixture.invalid/v1')
    def rate(self,active=1,price=1000000):
        self.c.execute('INSERT INTO ai_rates(provider,endpoint_id,model,input_rate,output_rate,active,created_at,actor) VALUES(?,?,?,?,?,?,?,?)',('openai-compatible',cost_store.endpoint_id('openai-compatible','https://fixture.invalid/v1'),'remote-x',price,price,active,1,'op'))
    def test_fixed_and_demo_unchanged(self):
        lanes,d=r.select(self.c,r.load({},self.base),self.base,self.task)
        self.assertEqual(lanes,self.base);self.assertEqual(d['reason'],'fixed_explicit_configuration')
        demo=mp.load_config({});cfg=r.load(config([candidate('a','local-a')],[self.b]),self.base)
        lanes,d=r.select(self.c,cfg,demo,self.task);self.assertEqual(lanes,demo);self.assertEqual(d['reason'],'demo_no_inference')
    def test_local_priority_and_disjoint_pair(self):
        self.rate()
        lanes,d=self.choose([candidate('a','local-a',('coding','structured'),50),self.remote()],remote='1',cap='2')
        self.assertEqual(lanes['A'].model,'local-a');self.assertEqual(d['status'],'selected')
        with self.assertRaises(ValueError):r.load(config([candidate('a','review-b')],[self.b]),self.base)
    def test_remote_policy_unknown_disabled_and_ceiling(self):
        for remote,cap,reason in [('0','9','remote_not_opted_in'),('1','9','rate_unknown')]:
            lanes,d=self.choose([self.remote()],remote=remote,cap=cap);self.assertIsNone(lanes);self.assertEqual(d['excluded']['A'][0]['reason'],reason)
        self.rate(price=2000000);lanes,d=self.choose([self.remote()],remote='1',cap='1');self.assertIsNone(lanes);self.assertEqual(d['excluded']['A'][0]['reason'],'rate_above_ceiling')
        lanes,d=self.choose([self.remote()],remote='1',cap='2');self.assertEqual(lanes['A'].model,'remote-x');self.assertNotIn('secret-never-return',json.dumps(d))
        self.rate(active=0);lanes,d=self.choose([self.remote()],remote='1',cap='9');self.assertIsNone(lanes)
    def test_resource_constraints_and_fallback_before_send(self):
        lanes,d=self.choose([candidate('large','large-a',quality=100,ram=4096),candidate('gpu','gpu-a',vram=100),candidate('cpu','cpu-a',cpu=4),candidate('small','small-a',quality=50)])
        self.assertEqual(lanes['A'].model,'small-a')
        self.assertEqual({x['reason'] for x in d['excluded']['A']},{'ram_unavailable_or_low','vram_unavailable_or_low','cpu_unavailable_or_low'})
        lanes,d=self.choose([candidate('gpu','gpu-a',vram=100)],gpu={'devices':[{'vram_total_bytes':512*r.MIB,'vram_used_bytes':100*r.MIB}]})
        self.assertEqual(lanes['A'].model,'gpu-a')
        lanes,d=self.choose([candidate('large','large-a',ram=1)],metrics={});self.assertIsNone(lanes)
    def test_task_capability_complexity_and_deterministic_choice(self):
        a=[candidate('cheap','cheap-a',quality=40,ram=1),candidate('quality','quality-a',quality=100,ram=10),candidate('no-schema','text-a',('coding',),100),candidate('short','short-a',quality=100,ctx=4096)]
        lanes,d=self.choose(a);self.assertEqual(lanes['A'].model,'quality-a')
        self.assertEqual({x['reason'] for x in d['excluded']['A']},{'structured_not_declared','context_too_small'})
        lanes,d=self.choose(a[:2],task=r.classify('pm','chat',10));self.assertEqual(lanes['A'].model,'cheap-a')
        lanes,d=self.choose([candidate('z','z-a'),candidate('a','a-a')]);self.assertEqual(lanes['A'].model,'a-a')
    def test_invalid_registry_and_fingerprint(self):
        a=candidate('a','a-a')
        for invalid in [dict(a,quality=True),dict(a,capabilities=['invalid']),dict(a,settings=dict(a['settings'],url='https://unapproved.invalid/v1')),dict(a,settings=dict(a['settings'],model='cloud:test'))]:
            with self.assertRaises((ValueError,PermissionError)):r.load(config([invalid],[self.b]),self.base)
        x=r.load(config([a],[self.b]),self.base);y=r.load(config([dict(a,quality=99)],[self.b]),self.base)
        self.assertNotEqual(x['fingerprint'],y['fingerprint']);self.assertNotEqual(agent_queue.fingerprint(self.base,x['fingerprint']),agent_queue.fingerprint(self.base,y['fingerprint']))
        self.assertNotIn('secret-never-return',json.dumps(r.public(x)))
    def test_history_scoping_and_preview_no_write(self):
        lanes,d=self.choose([candidate('a','a-a')]);self.assertEqual(r.history(self.c,'p'),[])
        r.record(self.c,'p','run',d);r.record(self.c,'q','other',d)
        self.assertEqual([x['run_id'] for x in r.history(self.c,'p')],['run'])
        self.assertEqual(len(r.history(self.c,all_projects=True)),2)
        self.assertEqual(auth_policy.scope(self.c,'GET','/api/projects/p/routing'),('p','read'))
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/provider/routing/preview'),('','provider_routing_preview'))
    def test_actual_dispatcher_routes_and_no_fallback_after_transport_failure(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ,AI_COMPANY_DB=str(Path(d)/'routing.sqlite'),AI_PROVIDER='ollama',AI_PROVIDER_A='ollama',AI_PROVIDER_B='ollama',AI_MODEL_A='base-a',AI_MODEL_B='base-b',PYTHONPATH=str(root/'backend'),**config([candidate('a','chosen-a',('coding','structured')),candidate('fallback','other-a',quality=20)],[self.b]))
            script="""import server,auth_store,model_provider,model_routing
from unittest.mock import patch
server.init_db()
with server.db() as c:
    pid=server.create_project('Routing test','Synthetic fixture for routing dispatch','Web app',c)
    auth_store.create_user(c,'fixture','fixture-password-123')
    auth_store.grant(c,'fixture',pid,'owner')
result=server.enqueue_coding(pid,'fixture','Implement a synthetic web coding feature')
seen=[]
def failed(lane,*a,**k):
    seen.append(lane.model)
    raise model_provider.ProviderError('fixture transport failure')
with patch.object(model_provider,'chat',side_effect=failed):
    assert server.dispatch_one()
with server.db() as c:
    task=server.agent_queue.get(c,pid,result['queue_id'])
    decision=model_routing.history(c,pid)[0]['decision']
    assert task['status']=='dead' and decision['selected']['A']['model']=='chosen-a'
    assert seen==['chosen-a'],seen
    assert c.execute('SELECT COUNT(*) FROM ai_usage').fetchone()[0]==1
"""
            subprocess.run([sys.executable,'-c',script],env=env,check=True,timeout=20)
