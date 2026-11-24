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
    def do_GET(self):
        self.server.received.append((self.path,self.headers.get('Authorization'),None))
        raw=json.dumps({'data':[{'id':'local-model'},{'id':'cloud-model'},{'id':'local-model'}]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.received.append((self.path,self.headers.get('Authorization'),body))
        if self.server.redirect:
            self.send_response(307)
            self.send_header('Location',self.server.redirect)
            self.end_headers()
            return
        default={'done':True,'done_reason':'stop','message':{'content':'{"ok":true}'}} if self.path=='/api/chat' else {'choices':[{'message':{'content':'ORBIT_READY'}}]}
        result=json.dumps(getattr(self.server,'response_override',None) or default).encode()
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

    def test_ollama_native_structured(self):
        lane=mp.load_config(dict(self.env,AI_PROVIDER_A='ollama'))['A']
        schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}
        self.assertEqual(json.loads(mp.chat(lane,'system','user',schema=schema,max_tokens=128)),{'ok':True})
        path,key,body=self.servers[0].received[0]
        self.assertEqual(path,'/api/chat')
        self.assertEqual(body['format'],schema)
        self.assertEqual(body['options'],{'temperature':0,'num_predict':128})
        self.assertEqual(key,'Bearer fixture-a')

    def test_repair_sampling_native_only(self):
        lane=mp.load_config(dict(self.env,AI_PROVIDER_A='ollama'))['A']
        schema={'type':'object'}
        mp.chat(lane,'s','u',schema=schema,repair_temperature=0.25,max_tokens=128)
        self.assertEqual(self.servers[0].received[0][2]['options']['temperature'],0.25)
        with self.assertRaises(ValueError):mp.chat(lane,'s','u',schema=schema,repair_temperature=0.9)

    def test_list_models_and_runtime_context(self):
        from dataclasses import replace
        lane=replace(mp.load_config(dict(self.env,AI_PROVIDER_A='ollama'))['A'],context_window=4096,max_tokens=512,temperature=0.2)
        self.assertEqual(mp.list_models(lane),['local-model'])
        self.assertEqual(self.servers[0].received[0][:2],('/v1/models','Bearer fixture-a'))
        mp.chat(lane,'s','u',runtime_settings=True)
        self.assertEqual(self.servers[0].received[1][2]['options'],{'temperature':0.2,'num_predict':512,'num_ctx':4096})

    def test_usage_observer_reports_actual_http_metadata(self):
        events=[]
        lane=mp.load_config(self.env)['A']
        self.servers[0].response_override={'choices':[{'message':{'content':'ORBIT_READY'}}],
            'usage':{'prompt_tokens':11,'completion_tokens':4,'total_tokens':15}}
        self.assertEqual(mp.chat(lane,'s','u',usage_observer=events.append),'ORBIT_READY')
        self.assertEqual(len(events),1)
        self.assertEqual((events[0]['input_tokens'],events[0]['output_tokens'],events[0]['total_tokens'],events[0]['status']),(11,4,15,'ok'))
        self.servers[0].response_override={'choices':[{'finish_reason':'length','message':{'content':'{}'}}],
            'usage':{'prompt_tokens':12,'completion_tokens':7,'total_tokens':19}}
        with self.assertRaises(mp.OutputError):mp.chat(lane,'s','u',schema={'type':'object'},usage_observer=events.append)
        self.assertEqual((events[1]['status'],events[1]['total_tokens']),('output_error',19))
        self.servers[0].response_override=None
        mp.chat(lane,'s','u',usage_observer=events.append)
        self.assertEqual(events[2]['coverage'],'unknown')
        self.assertIsNone(events[2]['total_tokens'])
        self.servers[0].redirect=self.url(1)+'/chat/completions'
        with self.assertRaises(mp.ProviderError):mp.chat(lane,'s','u',usage_observer=events.append)
        self.assertEqual((events[3]['status'],events[3]['coverage']),('provider_error','unknown'))
        self.assertEqual(len(events),4)
    def test_native_usage_observer(self):
        events=[]
        lane=mp.load_config(dict(self.env,AI_PROVIDER_A='ollama'))['A']
        self.servers[0].response_override={'done':True,'done_reason':'stop','message':{'content':'{}'},
            'prompt_eval_count':20,'eval_count':9}
        mp.chat(lane,'s','u',schema={'type':'object'},usage_observer=events.append)
        self.assertEqual((events[0]['source'],events[0]['total_tokens']),('ollama_native',29))
