"""Synthetic transport tests for P6.2d. Never real AI evidence."""
import copy,json,sqlite3,sys,unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_work_breakdown as fixture
import work_breakdown as w
import wbs_decomposition as d
import decomposition_jobs as dj
import planning_discovery as pd
import project_planning as pp
import product_requirements as pr
import model_provider as mp
import agent_queue as q
import usage_store,auth_policy

def source():
    doc=fixture.document()
    return dict(document=doc,proposal=pd.parse(json.dumps(fixture.raw('A')),dict(document=doc)),
        policy=dict(forbidden=doc['out_of_scope'],rules=[]),requirements_version=1,requirements_digest=pp.digest(doc),
        queue_id='pm',lane='A',proposal_digest='fixture')

def output(doc,ids):
    return {pid:{k:p[k] for k in w.DETAIL_FIELDS} for pid,p in d.packages(fixture.detail(doc)).items() if pid in ids}

def synthetic(doc,record,broken=False):
    def call(phase,system,user,schema):
        ids=schema['required'];record.append((phase,ids,json.loads(user)))
        patch=output(doc,ids)
        if broken and len(record)==1:patch[ids[0]]['action']='Create project management interface'
        return json.dumps(patch)
    return call

class DecompositionTests(unittest.TestCase):
    def setUp(self):self.src=source();self.doc=w.skeleton(self.src)
    def test_generation_and_exact_provenance(self):
        record=[];e=d.run(synthetic(self.doc,record),self.src,self.doc)
        self.assertTrue(e['ready']);self.assertEqual(e['call_count'],2)
        self.assertEqual(e['candidate'],fixture.detail(self.doc))
        self.assertEqual(e['analysis']['criterion_count'],3)
        self.assertTrue(all(p[k] is None for p in d.packages(self.doc).values() for k in w.DETAIL_FIELDS))
        self.assertFalse(e['semantic_reviewed']);self.assertTrue(d.gate(e,self.src,self.doc)['ready'])
    def test_targeted_repair_keeps_unflagged_packages(self):
        record=[];e=d.run(synthetic(self.doc,record,True),self.src,self.doc)
        self.assertTrue(e['ready']);self.assertEqual(e['call_count'],3)
        self.assertEqual(record[1][:2],('wbs_decompose_repair',['D-1.1']))
        self.assertEqual(e['candidate'],fixture.detail(self.doc))
    def test_invalid_json_and_exact_schema(self):
        ids=['D-1.1']
        for bad in ('{','[]','{"D-1.1":{},"D-1.1":{}}','{}',json.dumps({'D-1.1':{'action':'a','output':'b','evidence':'c','depends_on':[]}})):
            with self.assertRaises(ValueError):d.decode(bad,ids)
        record=[]
        def call(*args):record.append(args);return '{}'
        e=d.run(call,self.src,self.doc)
        self.assertFalse(e['ready']);self.assertEqual(len(record),2)
    def test_noop_scope_failure_and_no_third_call(self):
        record=[]
        def call(phase,system,user,schema):
            record.append(phase);patch=output(self.doc,schema['required'])
            for p in patch.values():p['action']='Create project management interface'
            return json.dumps(patch)
        e=d.run(call,self.src,self.doc)
        self.assertFalse(e['ready']);self.assertEqual(len(record),2);self.assertFalse(e['repair_audit_valid'])
    def test_provider_and_admission_failure_not_replayed(self):
        for error in (ValueError('stale'),mp.ProviderError('offline')):
            calls=[]
            def call(*args):calls.append(args);raise error
            with self.assertRaises(type(error)):d.run(call,self.src,self.doc)
            self.assertEqual(len(calls),1)
    def test_tamper_audit_and_blank_guard(self):
        e=d.run(synthetic(self.doc,[]),self.src,self.doc)
        for change in (lambda x:x['history'][0]['attempts'][0]['request'].update(schema_digest='bad'),
                       lambda x:x['candidate']['deliverables'][0]['packages'][0].update(action='Different action text'),
                       lambda x:x.update(base_digest='bad')):
            bad=copy.deepcopy(e);change(bad)
            with self.assertRaises(ValueError):d.gate(bad,self.src,self.doc)
        with self.assertRaises(ValueError):d.run(synthetic(self.doc,[]),self.src,fixture.detail(self.doc))

class DurableDecompositionTests(unittest.TestCase):
    def setUp(self):
        self.helper=fixture.WbsTests();self.helper.setUp()
        self.c=self.helper.c;dj.ensure_schema(self.c);usage_store.ensure_schema(self.c)
        self.helper.run_pm();self.base=self.helper.seed()['current'];self.lanes=self.helper.lanes
        self.body=dict(wbs_version=self.base['version'],wbs_digest=self.base['digest'],confirmation='RUN AI DECOMPOSITION')
    def tearDown(self):self.helper.tearDown()
    def enqueue(self,actor='owner',**kw):
        return dj.enqueue(self.c,'p',actor,0,self.lanes,dict(self.body,**kw))
    def claimed(self):
        i=self.enqueue();row=q.claim(self.c,9999999999,'t');return i,row,dj.checked_input(self.c,'p',i)
    def evidence(self,snap):
        return d.run(synthetic(snap['document'],[]),snap['source'],snap['document'])
    def ledger(self,i,e,model):
        for b in e['history']:
            for a in b['attempts']:
                uid=usage_store.start(self.c,model,'p','wbs-A',a['phase'],i)
                usage_store.finish(self.c,uid,dict(elapsed_ms=1,status='ok',input_tokens=12,output_tokens=20,total_tokens=32,coverage='complete',source='synthetic_test'))
    def test_persist_requires_ledger_and_never_overwrites(self):
        i,row,snap=self.claimed();e=self.evidence(snap);self.ledger(i,e,self.lanes['A'])
        result=dj.persist(self.c,'p',i,e,self.lanes['A'],'t');q.boundary(self.c,row,result,9999999999,'t')
        state=dj.latest(self.c,'p');self.assertTrue(state['ready']);self.assertEqual(state['evidence']['origin'],'model_generated')
        self.assertEqual(w.latest(self.c,'p')['digest'],self.base['digest']);self.assertIsNone(pp.latest(self.c,'p'))
        self.assertIsNone(dj.latest(self.c,'q'));self.assertEqual(list(self.c.execute('PRAGMA foreign_key_check')),[])
        self.helper.seed(v=1);self.assertTrue(dj.latest(self.c,'p')['stale']);self.assertFalse(dj.latest(self.c,'p')['ready'])
    def test_missing_ledger_blocks(self):
        i,row,snap=self.claimed();e=self.evidence(snap)
        self.assertEqual(dj.persist(self.c,'p',i,e,self.lanes['A'],'t'),'needs_revision')
        q.boundary(self.c,row,'needs_revision',9999999999,'t')
        self.assertFalse(dj.latest(self.c,'p')['ready'])
    def test_rbac_version_provider_and_revocation(self):
        for actor in ('viewer','reviewer'):
            with self.assertRaises(PermissionError):self.enqueue(actor)
        with self.assertRaises(ValueError):self.enqueue(wbs_digest='bad')
        with self.assertRaises(ValueError):dj.local_lane(dict(self.lanes,A=replace(self.lanes['A'],base_url='https://example.com/v1')),'A')
        with self.assertRaises(ValueError):dj.local_lane(dict(self.lanes,A=replace(self.lanes['A'],api_key='secret')),'A')
        i,row,snap=self.claimed();self.c.execute("DELETE FROM auth_memberships WHERE user_id='owner'")
        with self.assertRaises(PermissionError):dj.checked_input(self.c,'p',i)
    def test_routes(self):
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/planning/wbs/decompose'),('p','write'))
        self.assertIsNone(auth_policy.scope(self.c,'POST','/api/projects/p/planning/wbs/decompose/adopt'))

class QueueMigrationTests(unittest.TestCase):
    def test_planning_schema_migrates_with_child_references(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)');c.execute("INSERT INTO projects VALUES('p')")
        import auth_store
        auth_store.ensure_schema(c);auth_store.create_user(c,'owner','fixture-password-123');auth_store.grant(c,'owner','p','owner')
        q.ensure_schema(c)
        sql=c.execute("SELECT sql FROM sqlite_master WHERE name='agent_queue'").fetchone()[0]
        c.commit();c.execute('PRAGMA foreign_keys=OFF');c.execute('DROP TABLE agent_queue')
        c.execute(sql.replace(",'decomposition'",""));c.commit();c.execute('PRAGMA foreign_keys=ON')
        lanes=mp.load_config(dict(AI_PROVIDER='ollama',AI_MODEL_A='a',AI_MODEL_B='b'))
        i=q.enqueue(c,'p','planning','owner',0,lanes,now=100)
        c.execute('CREATE TABLE old_child(id TEXT REFERENCES agent_queue(id))');c.execute('INSERT INTO old_child VALUES(?)',(i,));c.commit()
        q.ensure_schema(c)
        self.assertEqual(q.get(c,'p',i)['kind'],'planning');self.assertEqual(c.execute('SELECT id FROM old_child').fetchone()[0],i)
        self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])
        q.enqueue(c,'p','decomposition','owner',0,lanes,now=101);c.close()
