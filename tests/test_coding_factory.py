"""AI Coding Factory safety and persistence tests (no model or GitHub required)."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import coding_factory as cf
import server


class ValidateTests(unittest.TestCase):
    def test_valid(self):
        p = cf.validate_proposal({'summary': 'safe', 'files': [{'path':'src/main.dart','content':'void main() {}'}]})
        self.assertEqual(p['total_bytes'], 14)
        self.assertEqual(len(p['files'][0]['sha256']), 64)

    def test_escape(self):
        for path in ('../main.py', 'src/../main.py', '/etc/passwd', 'src\\foo.py',
                     '.github/workflows/test.yml', '.env', 'src/.env', 'src/../x.py',
                     'src//x.py', 'C:/x.js', 'src/.hidden.py', 'build/main.js',
                     'src/foo.sh', 'foo.PY/other'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                cf.safe_path(path)

    def test_fail_closed_bad_proposal(self):
        for source in ('not json', '{}', '{"files":[]}', '{"files":{}}',
                       '{"files":[{"path":"src/a.py","content":34}]}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                cf.validate_proposal(source)

    def test_casefold_duplicates(self):
        with self.assertRaises(ValueError):
            cf.validate_proposal({'files':[{'path':'src/A.js','content':'a'}, {'path':'src/a.js','content':'b'}]})

    def test_large_content(self):
        with self.assertRaises(ValueError):
            cf.validate_proposal({'files':[{'path':'src/a.js','content':'x'*18001}]})

    def test_review_malformed_blocked(self):
        def invalid_model(*args):
            return '{"verdict":"APPROVE","score":"100","feedback":"looks fine"}'
        prop = cf.validate_proposal({'files':[{'path':'src/index.js','content':'export default 1'}]})
        with self.assertRaises(ValueError):
            cf.review_proposal(invalid_model, {'name':'P'}, 'feature', prop, 'A', 'B')

    def test_review_under_threshold(self):
        def model(*args):return '{"verdict":"APPROVE","score":79,"feedback":"missing tests"}'
        prop = cf.validate_proposal({'files':[{'path':'src/a.js','content':'x'}]})
        self.assertEqual(cf.review_proposal(model, {'name':'P'}, 'feature', prop, 'A', 'B')['verdict'], 'REQUEST_CHANGES')


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = server.DB_PATH
        server.DB_PATH = Path(self.tmp.name) / 'test.sqlite'
        server.init_db()
        with server.db() as c:
            self.pid = server.create_project('Coding Test', 'Valid testing project for AI coding', 'Web', c)

    def tearDown(self):
        server.DB_PATH = self.orig
        self.tmp.cleanup()

    def run_job(self, model=None, repair=None):
        def runner(jid, pid):
            cf.work(server.db, server.LOCK, jid, pid, model, server.now, server.log, server.get_preceding, repair=repair)
        # Make thread deterministic for tests.
        with patch.object(cf.threading, 'Thread') as thread:
            t = thread.return_value
            jid = cf.begin(server.db, server.LOCK, self.pid, 'Create a small well tested example function', server.uid, server.now, server.log, runner)
            t.start.assert_called_once()
        runner(jid,self.pid)
        with server.db() as c:
            return cf.detail(c,jid)

    def test_demo_exports_reviewed_zip(self):
        job = self.run_job()
        self.assertEqual(job['status'],'ready')
        self.assertEqual(job['review_a']['reviewer'],'A')
        self.assertEqual(job['review_a']['author'],'B')
        self.assertEqual(job['review_b']['reviewer'],'B')
        self.assertEqual(job['review_b']['author'],'A')
        self.assertFalse(job['manifest']['executed'])
        with server.db() as c:
            data = cf.export_zip(c, job['id'])
            listed = cf.list_jobs(c, self.pid)
            self.assertEqual(listed[0]['status'],'ready')
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('src/app_a.js', z.namelist())
            self.assertIn('ORBIT_REVIEW_MANIFEST.json',z.namelist())
            self.assertIn('DEMO ONLY',z.read('src/app_a.js').decode())

    def test_reject_dup_jobs(self):
        with server.db() as c:
            c.execute('INSERT INTO coding_jobs(id,project_id,spec,status,created_at,updated_at) VALUES(?,?,?,?,?,?)', ('active',self.pid,'hello','generating',server.now(),server.now()))
        with self.assertRaises(ValueError):
            cf.begin(server.db,server.LOCK,self.pid,'Implement data validation for login form',server.uid,server.now,server.log,lambda *args:None)

    def test_reject_short_spec(self):
        with self.assertRaises(ValueError):
            cf.begin(server.db,server.LOCK,self.pid,'test',server.uid,server.now,server.log,lambda *args:None)

    def test_failed_review_blocks_zip(self):
        calls = []
        def model(system, prompt, lane):
            calls.append((system,prompt,lane))
            if 'code reviewer' in system:
                return '{"verdict":"REQUEST_CHANGES","score":52,"feedback":"Missing validation"}'
            return json.dumps({'summary':lane,'files':[{'path':'src/main.py','content':'print(123)'}]})
        job = self.run_job(model)
        self.assertEqual(job['status'],'needs_revision')
        self.assertEqual([v[2] for v in calls],['A','B','A','B'])
        self.assertNotIn('print(123)',calls[1][1]) # B does not see proposal A
        with server.db() as c,self.assertRaises(ValueError):
            cf.export_zip(c,job['id'])

    def test_repair_reuses_passing_lane_and_rechecks_both(self):
        calls=[]
        a=cf.validate_proposal({'files':[{'path':'main.py','content':'# A prior private code'}]})
        b=cf.validate_proposal({'files':[{'path':'main.py','content':'# B prior private code'}]})
        repair={'A':{'proposal':a,'reuse':True,'feedback':''},
                'B':{'proposal':b,'reuse':False,'feedback':'NameError'}}
        def model(system,prompt,lane):
            calls.append((system,prompt,lane))
            if 'code reviewer' in system:
                return '{"verdict":"APPROVE","score":90,"feedback":"Reviewed"}'
            return json.dumps({'files':[{'path':'main.py','content':'# B repaired'}]})
        j=self.run_job(model,repair=repair)
        self.assertEqual(j['status'],'ready')
        self.assertEqual([x[2] for x in calls],['B','A','B'])
        self.assertIn('NameError',calls[0][1])
        self.assertIn('B prior private code',calls[0][1])
        self.assertNotIn('A prior private code',calls[0][1])
        self.assertEqual(j['proposal_a'],a)
        self.assertEqual(j['manifest']['repair_reused_lanes'],['A'])

    def test_corrupt_manifest(self):
        job = self.run_job()
        with server.db() as c:
            obj=job['proposal_a'];obj['files'][0]['content']='altered'
            c.execute('UPDATE coding_jobs SET proposal_a=? WHERE id=?',(json.dumps(obj),job['id']))
        with server.db() as c, self.assertRaises(ValueError):
            cf.export_zip(c,job['id'])

    def test_unknown_project_and_job(self):
        with self.assertRaises(ValueError):
            cf.begin(server.db,server.LOCK,'unrecognized-id','Implement data validation for login form',server.uid,server.now,server.log,lambda *args:None)
        with server.db() as c,self.assertRaises(ValueError):
            cf.detail(c,'missing')


if __name__=='__main__': unittest.main()
