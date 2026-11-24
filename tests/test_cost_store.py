import sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model_provider as mp
import usage_store as u
import cost_store as cst
import auth_store,auth_policy,auth_http

class CostTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');u.ensure_schema(self.c);auth_store.ensure_schema(self.c)
        self.env={'ORBIT_PROVIDER_ADMINS':'operator','ORBIT_PROVIDER_ENDPOINTS':'[{"provider":"openai-compatible","url":"https://example.com/v1"},{"provider":"openai-compatible","url":"https://other.example/v1"}]'}
        self.initial=mp.load_config({})
        self.lane=mp.Lane('A','openai-compatible','https://example.com/v1','model-x','key')
        auth_store.create_user(self.c,'owner','fixture-password-123');auth_store.create_user(self.c,'viewer','fixture-password-123')
        self.c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)');self.c.executemany('INSERT INTO projects VALUES(?)',[('p',),('other',)])
        auth_store.grant(self.c,'owner','p','owner');auth_store.grant(self.c,'viewer','p','viewer')
    def tearDown(self):self.c.close()
    def rate(self,i='2.500001',o='10',expected=0,active=True):
        return cst.save_rate(self.c,'operator',{'provider':self.lane.provider,'url':self.lane.base_url,'model':self.lane.model,
            'input_usd_per_million':i,'output_usd_per_million':o,'expected_id':expected,'active':active,'confirmation':'APPLY AI RATE'},self.env,self.initial)
    def call(self,lane=None,project='p',i=1000,o=2000,coverage='complete',status='ok'):
        ident=u.start(self.c,lane or self.lane,project,'dev-A','code_generate','job')
        if status!='pending':u.finish(self.c,ident,{'elapsed_ms':1,'status':status,'input_tokens':i,'output_tokens':o,'total_tokens':i+o if i is not None and o is not None else None,'coverage':coverage,'source':'openai_usage'})
        return ident
    def test_exact_price_and_snapshot(self):
        first=self.rate()['id'];self.call()
        second=self.rate('4','12',first)['id'];self.call()
        result=cst.summary(self.c,'p')['totals']
        self.assertEqual(result['total_usd'],'0.050500001000')
        self.assertEqual(result['known_calls'],2)
        self.assertEqual(cst.rates_view(self.c,self.env,self.initial)['rates'][0]['id'],second)
        with self.assertRaises(ValueError):self.rate(expected=first)
    def test_missing_price_legacy_unknown_and_pending(self):
        legacy=self.call();self.c.execute('DELETE FROM ai_cost_basis WHERE usage_id=?',(legacy,))
        self.call();self.rate();self.call(i=None,coverage='partial');self.call(status='pending')
        t=cst.summary(self.c,'p')['totals']
        self.assertEqual((t['unknown_calls'],t['legacy_calls'],t['unpriced_calls'],t['pending_calls']),(4,1,1,1))
        self.assertIsNone(t['total_usd'])
    def test_local_zero_and_remote_ollama_unknown(self):
        self.call(mp.Lane('A','ollama',mp.DEFAULT_URL,'qwen',''))
        self.call(mp.Lane('A','ollama','https://remote.example/v1','qwen',''))
        t=cst.summary(self.c,'p')['totals']
        self.assertEqual(t['total_usd'],'0.000000000000');self.assertEqual(t['local_assumed_zero_calls'],1);self.assertEqual(t['unknown_calls'],1)
    def test_endpoint_isolation_disable_and_failed_billable(self):
        first=self.rate()['id'];self.call(status='output_error')
        self.call(mp.Lane('A','openai-compatible','https://other.example/v1','model-x','key'))
        self.rate(None,None,first,False);self.call()
        t=cst.summary(self.c,'p')['totals']
        self.assertEqual(t['total_usd'],'0.022500001000');self.assertEqual(t['unknown_calls'],2)
    def test_budget_scope_revision_and_month(self):
        body={'revision':0,'monthly_limit_usd':'0.020000','confirmation':'APPLY AI BUDGET'}
        with self.assertRaises(PermissionError):cst.save_budget(self.c,'p','viewer',body)
        cst.save_budget(self.c,'p','owner',body)
        self.rate();self.call()
        self.assertEqual(cst.summary(self.c,'p')['budget']['status'],'limit_reached_known')
        with self.assertRaises(ValueError):cst.save_budget(self.c,'p','owner',body)
        self.call(project='other')
        self.assertEqual(cst.summary(self.c,'p')['totals']['requests'],1)
        self.assertEqual(cst.summary(self.c,None,all_projects=True)['totals']['requests'],2)
        self.c.execute('UPDATE ai_usage SET started_at=1')
        self.assertEqual(cst.summary(self.c,'p')['budget']['known_spend_usd'],'0.000000000000')
    def test_price_validation_and_authorization(self):
        for v in ('-1','NaN','1e3','0.0000001',1.0):
            with self.assertRaises(ValueError):self.rate(v)
        token=auth_store.login(self.c,'viewer','fixture-password-123');h={'Cookie':auth_http.COOKIE+'='+token}
        with patch.dict('os.environ',{'ORBIT_PROVIDER_ADMINS':'operator'}):
            self.assertEqual(auth_policy.check(self.c,'GET','/api/projects/p/cost','',{},h,8787)[0],200)
            self.assertEqual(auth_policy.check(self.c,'GET','/api/projects/other/cost','',{},h,8787)[0],403)
            self.assertEqual(auth_policy.check(self.c,'GET','/api/provider/rates','',{},h,8787)[0],403)
            self.assertEqual(auth_policy.check(self.c,'GET','/api/provider/cost','',{},h,8787)[0],403)
            h.update(Origin='http://127.0.0.1:8787',**{'X-ORBIT-CSRF':auth_http.csrf_for(token)})
            self.assertEqual(auth_policy.check(self.c,'POST','/api/projects/p/budget','',{},h,8787)[0],403)
