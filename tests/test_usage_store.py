import json,sqlite3,sys,tempfile,threading,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model_provider as mp
import usage_store as u
import auth_policy,auth_store,auth_http

class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'usage.db';self.lock=threading.RLock()
        with self.db() as c:u.ensure_schema(c)
        self.lane=mp.Lane('A','ollama',mp.DEFAULT_URL,'local-model','private-key')
    def tearDown(self):self.tmp.cleanup()
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path)
        try:
            with c:yield c
        finally:c.close()
    def call(self,project='p',purpose='code_generate'):
        return u.tracked_chat(self.db,self.lock,self.lane,'private prompt','private user',project_id=project,agent_id='dev-A',purpose=purpose,run_id='job')
    def event(self,**kwargs):
        return dict(mp.token_usage({'prompt_eval_count':12,'eval_count':8},True),status='ok',elapsed_ms=9,**kwargs)
    def test_token_normalization(self):
        self.assertEqual(mp.token_usage({'prompt_eval_count':12,'eval_count':8},True)['total_tokens'],20)
        self.assertEqual(mp.token_usage({'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10}},False)['coverage'],'complete')
        self.assertEqual(mp.token_usage({'usage':{'total_tokens':8}},False)['coverage'],'partial')
        self.assertEqual(mp.token_usage({'usage':{'prompt_tokens':True,'completion_tokens':-3}},False)['coverage'],'unknown')
        self.assertEqual(mp.token_usage({'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':11}},False)['coverage'],'inconsistent')
        self.assertIsNone(mp.token_usage({},True)['total_tokens'])
    def test_records_success_and_failed_response_with_usage(self):
        def good(*args,usage_observer,**kwargs):usage_observer(self.event());return 'private response'
        def fail(*args,usage_observer,**kwargs):
            event=self.event();event['status']='output_error';usage_observer(event);raise mp.OutputError('bad response')
        with patch.object(mp,'chat',side_effect=good):self.assertEqual(self.call(),'private response');self.call('other')
        with patch.object(mp,'chat',side_effect=fail):
            with self.assertRaises(mp.OutputError):self.call()
        with self.db() as c:
            d=u.summary(c,'p')
            self.assertEqual(d['totals']['requests'],2)
            self.assertEqual(d['totals']['failed_calls'],1)
            self.assertEqual(d['totals']['total_tokens'],40)
            self.assertEqual(u.summary(c,None,all_projects=True)['totals']['requests'],3)
            raw=json.dumps(c.execute('SELECT * FROM ai_usage').fetchall())
            for secret in ('private prompt','private user','private response','private-key'):self.assertNotIn(secret,raw)
    def test_unknown_and_pending_and_duplicate_completion(self):
        with self.db() as c:pending=u.start(c,self.lane,'p','dev-A','coding')
        def fail(*args,usage_observer,**kwargs):
            usage_observer(dict(mp.token_usage(None,True),status='provider_error',elapsed_ms=1));raise mp.ProviderError('down')
        with patch.object(mp,'chat',side_effect=fail):
            with self.assertRaises(mp.ProviderError):self.call()
        with self.db() as c:
            d=u.summary(c,'p')['totals']
            self.assertEqual(d['pending_calls'],1);self.assertEqual(d['unknown_calls'],2);self.assertIsNone(d['total_tokens'])
            u.finish(c,pending,self.event())
            with self.assertRaises(RuntimeError):u.finish(c,pending,self.event())
    def test_demo_rejected_and_period_filter(self):
        with self.db() as c:
            with self.assertRaises(ValueError):u.start(c,mp.load_config({})['A'],'p','dev-A','coding')
            ident=u.start(c,self.lane,'p','dev-A','coding');u.finish(c,ident,self.event())
            c.execute('UPDATE ai_usage SET started_at=100')
            self.assertEqual(u.summary(c,'p',1,now=100000)['totals']['requests'],0)
            self.assertEqual(u.summary(c,'p',7,now=100000)['totals']['requests'],1)
            with self.assertRaises(ValueError):u.summary(c,'p',999)
    def test_access_scope(self):
        with self.db() as c:
            auth_store.ensure_schema(c);c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)');c.executemany('INSERT INTO projects VALUES(?)',[('p',),('other',)])
            auth_store.create_user(c,'viewer','fixture-password-123');auth_store.grant(c,'viewer','p','viewer')
            token=auth_store.login(c,'viewer','fixture-password-123')
            h={'Cookie':auth_http.COOKIE+'='+token}
            with patch.dict('os.environ',{'ORBIT_PROVIDER_ADMINS':'operator'}):
                self.assertEqual(auth_policy.check(c,'GET','/api/projects/p/usage','',{},h,8787)[0],200)
                self.assertEqual(auth_policy.check(c,'GET','/api/projects/other/usage','',{},h,8787)[0],403)
                self.assertEqual(auth_policy.check(c,'GET','/api/provider/usage','',{},h,8787)[0],403)
