import json,sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import provider_settings as ps
import model_provider as mp
import auth_policy,auth_store,auth_http
class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.initial=mp.load_config({})
        self.env={'ORBIT_PROVIDER_ADMINS':'operator','ORBIT_PROVIDER_ENDPOINTS':json.dumps([{'provider':'openai-compatible','url':'https://api.example.com/v1','key_env':'ORBIT_PROVIDER_KEY_TEST'}]),'ORBIT_PROVIDER_KEY_TEST':'secret-fixture'}
        self.form={k:dict(ps.lane_form(v),provider='ollama',url=mp.DEFAULT_URL,model='model-'+k) for k,v in self.initial.items()}
    def tearDown(self):self.c.close()
    def body(self):return {'revision':0,'lanes':self.form,'confirmation':'APPLY AI SETTINGS'}
    def test_persistence_and_revision(self):
        self.form['B'].update(provider='openai-compatible',url='https://api.example.com/v1')
        result=ps.save(self.c,'operator',self.body(),self.env,self.initial)
        self.assertEqual(result['revision'],1)
        self.assertEqual(result['mode'],'split')
        self.assertTrue(result['lanes']['B']['key_configured'])
        self.assertNotIn('secret-fixture',json.dumps(result))
        self.assertNotIn('secret-fixture',self.c.execute('SELECT config FROM provider_settings').fetchone()[0])
        self.assertEqual(ps.load(self.c,self.env,self.initial)[1]['B'].api_key,'secret-fixture')
        with self.assertRaises(ValueError):ps.save(self.c,'operator',self.body(),self.env,self.initial)
    def test_url_and_admin_denied(self):
        with self.assertRaises(PermissionError):ps.save(self.c,'project-owner',self.body(),self.env,self.initial)
        self.form['B']['url']='https://169.254.169.254/v1'
        with self.assertRaises(PermissionError):ps.save(self.c,'operator',self.body(),self.env,self.initial)
    def test_duplicate_mixed_demo_and_secret_input(self):
        self.form['B']['model']=self.form['A']['model']
        with self.assertRaises(ValueError):ps.validate(self.form,self.env,self.initial)
        self.form['B']['model']='model-B';self.form['B']['provider']='demo'
        with self.assertRaises(ValueError):ps.validate(self.form,self.env,self.initial)
        self.form['B']['provider']='ollama';self.form['B']['api_key']='no'
        with self.assertRaises(ValueError):ps.validate(self.form,self.env,self.initial)
    def test_revoked_endpoint_fails_closed(self):
        self.form['B'].update(provider='openai-compatible',url='https://api.example.com/v1')
        ps.save(self.c,'operator',self.body(),self.env,self.initial)
        with self.assertRaises(PermissionError):ps.load(self.c,{},self.initial)
    def test_network_confirmation_and_no_outbound_on_bad_url(self):
        with patch.object(mp,'probe') as probe:
            with self.assertRaises(ValueError):ps.network_action({'lanes':self.form},self.env,self.initial,'probe')
            self.form['B']['url']='https://evil.example/v1'
            with self.assertRaises(PermissionError):ps.network_action({'lanes':self.form,'confirmation':'TEST AI CONNECTION'},self.env,self.initial,'probe')
            probe.assert_not_called()
    def test_policy_is_global_not_project_owner(self):
        auth_store.ensure_schema(self.c)
        auth_store.create_user(self.c,'operator','fixture-password-123')
        auth_store.create_user(self.c,'project-owner','fixture-password-123')
        with patch.dict('os.environ',{'ORBIT_PROVIDER_ADMINS':'operator'}):
            for user,expected in [('operator',200),('project-owner',403)]:
                token=auth_store.login(self.c,user,'fixture-password-123')
                import hashlib
                headers={'Cookie':'orbit_session='+token}
                self.assertEqual(auth_policy.check(self.c,'GET','/api/provider/settings','',{},headers,8787)[0],expected)
