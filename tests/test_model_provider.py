"""Real localhost HTTP protocol tests, not actual model inference."""
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import model_provider as mp

class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.received.append((self.path,self.headers.get('Authorization'),body))
        if self.server.redirect:
            self.send_response(307)
            self.send_header('Location',self.server.redirect)
            self.end_headers()
            return
        result=json.dumps({'choices':[{'message':{'content':'ORBIT_READY'}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(result)))
        self.end_headers()
        self.wfile.write(result)

class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.servers=[]
        for _ in range(2):
            s=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
            s.received=[];s.redirect=None
            t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
            self.servers.append(s)
        self.env={'AI_PROVIDER':'openai-compatible','AI_MODEL_A':'model-a','AI_MODEL_B':'model-b',
            'AI_BASE_URL_A':self.url(0),'AI_BASE_URL_B':self.url(1),'AI_API_KEY_A':'fixture-a','AI_API_KEY_B':'fixture-b'}
    def url(self,i):return 'http://127.0.0.1:'+str(self.servers[i].server_port)+'/v1'
    def tearDown(self):
        for s in self.servers:s.shutdown();s.server_close()
    def test_separate_real_http_routes(self):
        lanes=mp.load_config(self.env)
        result=mp.probe(lanes)
        self.assertTrue(result['both_responded'])
        for i,k in enumerate(('a','b')):
            path,key,body=self.servers[i].received[0]
            self.assertEqual((path,key,body['model']),('/v1/chat/completions','Bearer fixture-'+k,'model-'+k))
            self.assertEqual(body['max_tokens'],64)
        self.assertNotIn('fixture-a',repr(lanes))
        self.assertNotIn('fixture-b',json.dumps(mp.public_config(lanes)))
    def test_no_shared_key_leak(self):
        e=dict(self.env,AI_BASE_URL=self.url(0),AI_API_KEY='shared')
        del e['AI_API_KEY_A'];del e['AI_API_KEY_B']
        lanes=mp.load_config(e)
        self.assertEqual(lanes['A'].api_key,'shared')
        self.assertEqual(lanes['B'].api_key,'')
    def test_redirect_refused(self):
        self.servers[0].redirect=self.url(1)+'/chat/completions'
        with self.assertRaisesRegex(mp.ProviderError,'HTTP 307'):
            mp.chat(mp.load_config(self.env)['A'],'test','test')
        self.assertEqual(self.servers[1].received,[])
    def test_reject_insecure_or_credential_url(self):
        for url in ('http://example.com/v1','https://user:secret@example.com/v1','https://example.com/v1?key=secret'):
            with self.assertRaises(ValueError):mp.load_config(dict(self.env,AI_BASE_URL_A=url))
    def test_demo_and_distinct_gate(self):
        self.assertEqual(mp.mode(mp.load_config({})),'demo')
        with self.assertRaises(ValueError):mp.require_distinct_real(mp.load_config({}))
        with self.assertRaises(ValueError):mp.require_distinct_real(mp.load_config(dict(self.env,AI_MODEL_B='model-a')))
        with self.assertRaises(ValueError):mp.load_config(dict(self.env,AI_PROVIDER_A='demo'))
    def test_mixed_real_providers(self):
        lanes=mp.load_config(dict(self.env,AI_PROVIDER_A='ollama'))
        self.assertEqual(mp.mode(lanes),'split')
        self.assertEqual(mp.public_config(lanes)['lanes']['A']['provider'],'ollama')
