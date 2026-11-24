"""Trusted handwritten HTTP fixtures + real Docker, NOT real LLM inference."""
import json,os,subprocess,sys,tempfile,threading,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'tools')]
import server,model_provider,coding_factory as cf,verification_factory as vf
import p4_e2e
from unittest.mock import patch

def proposal(lane):
    code='def add(a,b):\n    return a+b\n' if lane=='A' else 'def add(a,b):\n    result=a+b\n    return result\n'
    return {'summary':'Trusted fixture '+lane,'files':[{'path':'main.py','content':code},
        {'path':'test_main.py','content':'import unittest\nfrom main import add\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2,3),5)\n        self.assertEqual(add(-1,1),0)\n'}]}
class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.calls.append(body)
        lane=self.server.lane
        if body['model']!='fixture-'+lane:
            self.send_error(400);return
        if len(self.server.calls)==1:reply=proposal(lane)
        else:reply={'verdict':'APPROVE','score':90,'feedback':'Trusted fixture review only'}
        raw=json.dumps({'choices':[{'message':{'content':json.dumps(reply)}}]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class P4Tests(unittest.TestCase):
    def test_fixture_pipeline(self):
        servers=[]
        try:
            for lane in 'AB':
                s=ThreadingHTTPServer(('127.0.0.1',0),Fixture);s.lane=lane;s.calls=[]
                threading.Thread(target=s.serve_forever,daemon=True).start();servers.append(s)
            env={'AI_PROVIDER':'openai-compatible','AI_MODEL_A':'fixture-A','AI_MODEL_B':'fixture-B',
                'AI_BASE_URL_A':'http://127.0.0.1:'+str(servers[0].server_port)+'/v1',
                'AI_BASE_URL_B':'http://127.0.0.1:'+str(servers[1].server_port)+'/v1'}
            lanes=model_provider.load_config(env)
            with tempfile.TemporaryDirectory() as tmp,patch.object(server,'DB_PATH',Path(tmp)/'fixture.sqlite'):
                server.init_db()
                pid=server.list_projects()[0]['id']
                done=threading.Event()
                def worker(jid,pid):
                    try:cf.work(server.db,server.LOCK,jid,pid,lambda sy,u,l:model_provider.chat(lanes[l],sy,u),server.now,server.log,server.get_preceding)
                    finally:done.set()
                jid=cf.begin(server.db,server.LOCK,pid,'Implement addition for a Web backend module',server.uid,server.now,server.log,worker)
                self.assertTrue(done.wait(30))
                with server.db() as c:
                    j=p4_e2e.require_job(c,jid)
                    self.assertEqual(j['status'],'ready')
                    self.assertEqual(p4_e2e.state(c,j)['stage'],'awaiting_sandbox')
                    self.assertEqual([len(s.calls) for s in servers],[2,2])
                    self.assertNotIn('Trusted fixture B',servers[0].calls[0]['messages'][1]['content'])
                    self.assertNotIn('Trusted fixture A',servers[1].calls[0]['messages'][1]['content'])
                    self.assertIn('result=a+b',servers[0].calls[1]['messages'][1]['content'])
                    self.assertIn('return a+b',servers[1].calls[1]['messages'][1]['content'])
                    with self.assertRaises(PermissionError):vf.verify_job(j,approval='wrong')
                    # Only trusted fixed fixture content is run in CI; never external model output.
                    image=os.getenv('ORBIT_P4_FIXTURE_IMAGE')
                    if image:
                        report=vf.verify_job(j,python_image=image,approval='RUN SANDBOX '+jid,timeout=45)
                    else:
                        from test_verification_factory import FakeDocker,PY_IMG
                        report=vf.verify_job(j,python_image=PY_IMG,approval='RUN SANDBOX '+jid,runner=FakeDocker())
                    self.assertEqual(report['gate'],'PASS')
                    ref=vf.store_report(c,report)
                    entry=p4_e2e.latest(c,jid)
                    self.assertEqual(p4_e2e.state(c,j)['stage'],'awaiting_techlead')
                    with self.assertRaises(ValueError):p4_e2e.prepare(c,j,entry)
                    with self.assertRaises(PermissionError):p4_e2e.select(c,j,entry,selected='B',techlead='Fixture Lead',rationale='Fixture both candidates passed checks.',confirmation='wrong')
                    d=p4_e2e.select(c,j,entry,selected='B',techlead='Fixture Lead',rationale='Fixture both candidates passed checks.',confirmation='SELECT DEV-B '+jid)
                    self.assertEqual(d['verification_id'],ref)
                    bundle,_=p4_e2e.prepare(c,j,entry)
                    self.assertEqual(bundle['selected'],'B')
                    self.assertTrue(all('/candidate-B/' in f['path'] or f['path'].endswith('/VERIFICATION.json') for f in bundle['files']))
                    self.assertEqual(p4_e2e.state(c,j)['stage'],'draft_pr_preflight_ready')
                    vf.store_report(c,report)
                    with self.assertRaises(ValueError):p4_e2e.prepare(c,j,p4_e2e.latest(c,jid))
                    print('P4 TRUSTED FIXTURE E2E PASS; real Docker='+str(bool(image))+'; real inference=False; GitHub writes=False')
        finally:
            for s in servers:s.shutdown();s.server_close()

if __name__=='__main__':unittest.main()
