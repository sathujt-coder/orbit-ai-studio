import copy,json,sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from test_product_requirements import document
import product_requirements as pr
import project_planning as pp
import planning_discovery as pd
import planning_jobs as pj
import agent_queue as q
import auth_store
import auth_policy
import model_provider as mp
import model_routing

def fixture():
    return dict(objective='Deliver approved links',work=[
        dict(requirement='REQ-1',implement='Persist link',verify='Test saved link listing'),
        dict(requirement='REQ-2',implement='Enforce project isolation',verify='Test unauthorized read denial')])
def source():
    doc=document()
    return dict(version=1,digest=pp.digest(doc),document=doc,approved_by='reviewer',approved_at='t')

class DiscoveryTests(unittest.TestCase):
    def test_independence_and_backend_graph(self):
        calls=[]
        def call(lane,phase,system,user,schema):
            calls.append((lane,phase,user,schema));return json.dumps(fixture())
        e=pd.discover(call,source())
        self.assertEqual(len(calls),2);self.assertEqual(calls[0][2],calls[1][2])
        self.assertEqual(json.loads(calls[0][2]),pd.packet(source()))
        self.assertTrue(e['structurally_ready']);self.assertFalse(e['semantic_reviewed'])
        for doc in e['proposals'].values():
            self.assertEqual(pp.analyze(doc,document())['task_count'],4)
            self.assertTrue(all(t['effort_minutes'] is None for t in doc['tasks']))
    def test_invalid_mappings_and_titles(self):
        for change in (lambda d:d['work'].pop(),lambda d:d['work'][0].update(requirement='REQ-2'),
                lambda d:d['work'][0].update(requirement='REQ-999'),lambda d:d['work'][0].update(verify='Persist link'),
                lambda d:d['work'][0].update(implement='implement'),lambda d:d['work'][0].update(effort_minutes=10)):
            raw=fixture();change(raw)
            with self.assertRaises(ValueError):pd.parse(json.dumps(raw),pd.packet(source()))
    def test_bounded_repair_and_partial_failure(self):
        calls=[]
        def call(lane,phase,*args):
            calls.append((lane,phase))
            return json.dumps(fixture()) if lane=='A' and phase.endswith('repair') else '{}'
        e=pd.discover(call,source());self.assertEqual(len(calls),4)
        self.assertEqual(set(e['proposals']),{'A'});self.assertFalse(e['structurally_ready'])
    def test_provider_failure_never_replayed(self):
        calls=[]
        def call(*args):calls.append(args);raise mp.ProviderError('offline')
        with self.assertRaises(mp.ProviderError):pd.discover(call,source())
        self.assertEqual(len(calls),1)
    def test_source_gate(self):
        for change in (dict(digest='bad'),dict(approved_at=None)):
            with self.assertRaises(ValueError):pd.packet(dict(source(),**change))
        self.assertTrue(model_routing.classify('pm','planning',10)['structured'])
        self.assertEqual(model_routing.classify('pm','planning',10)['min_context'],8192)

class PlanningQueueTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.execute('PRAGMA foreign_keys=ON')
        self.c.executescript("CREATE TABLE projects(id TEXT PRIMARY KEY); INSERT INTO projects VALUES('p'),('q');")
        auth_store.ensure_schema(self.c);pr.ensure_schema(self.c);pp.ensure_schema(self.c);q.ensure_schema(self.c);pj.ensure_schema(self.c)
        auth_store.create_user(self.c,'owner','fixture-password-123');auth_store.grant(self.c,'owner','p','owner')
        self.lanes=mp.load_config(dict(AI_PROVIDER='ollama',AI_MODEL_A='a',AI_MODEL_B='b'))
        self.row=pr.save(self.c,'p','owner',dict(expected_version=0,document=document()),'t')['current']
    def tearDown(self):self.c.close()
    def approve(self):
        self.row=pr.approve(self.c,'p','owner',dict(version=self.row['version'],digest=self.row['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS'),'t')['current']
    def add(self,**kw):
        return pj.enqueue(self.c,'p','owner',0,self.lanes,'t',version=self.row['version'],digest=self.row['digest'],**kw)
    def evidence(self):
        return pd.discover(lambda *args:json.dumps(fixture()),source())
    def test_queue_gate_and_no_adoption(self):
        with self.assertRaises(ValueError):self.add()
        self.approve();i=self.add()
        with self.assertRaises(ValueError):self.add()
        row=q.claim(self.c,9999999999,'t')
        result=pj.persist(self.c,'p',i,self.evidence(),self.lanes,'t')
        q.boundary(self.c,row,result,9999999999,'t')
        self.assertTrue(pj.latest(self.c,'p')['ready']);self.assertIsNone(pp.latest(self.c,'p'))
        self.assertIsNone(pj.latest(self.c,'q'))
        self.assertEqual(q.get(self.c,'p',i)['status'],'succeeded')
        pr.save(self.c,'p','owner',dict(expected_version=1,document=document()),'t')
        self.assertFalse(pj.latest(self.c,'p')['ready']);self.assertTrue(pj.latest(self.c,'p')['stale'])
    def test_stale_or_revoked_execution_blocked(self):
        self.approve();i=self.add();q.claim(self.c,9999999999,'t')
        self.c.execute("DELETE FROM auth_memberships WHERE user_id='owner'")
        with self.assertRaises(PermissionError):pj.checked_input(self.c,'p',i)
        auth_store.grant(self.c,'owner','p','owner')
        pr.save(self.c,'p','owner',dict(expected_version=1,document=document()),'t')
        with self.assertRaises(ValueError):pj.persist(self.c,'p',i,self.evidence(),self.lanes,'t')
    def test_partial_and_invalid_evidence(self):
        self.approve();i=self.add();row=q.claim(self.c,9999999999,'t');e=self.evidence()
        e['proposals']['A']['tasks'][0]['effort_minutes']=5
        with self.assertRaises(ValueError):pj.persist(self.c,'p',i,e,self.lanes,'t')
        e=self.evidence();del e['proposals']['B']
        result=pj.persist(self.c,'p',i,e,self.lanes,'t');q.boundary(self.c,row,result,9999999999,'t')
        self.assertFalse(pj.latest(self.c,'p')['ready']);self.assertEqual(q.get(self.c,'p',i)['status'],'dead')
    def test_queue_migration_preserves_existing_rows_and_foreign_keys(self):
        # Recreate the previous CHECK in an isolated database, with child references.
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        c.execute('CREATE TABLE projects(id TEXT PRIMARY KEY)');c.execute("INSERT INTO projects VALUES('p')")
        auth_store.ensure_schema(c);auth_store.create_user(c,'owner','fixture-password-123');auth_store.grant(c,'owner','p','owner')
        q.ensure_schema(c)
        sql=c.execute("SELECT sql FROM sqlite_master WHERE name='agent_queue'").fetchone()[0]
        c.commit();c.execute('PRAGMA foreign_keys=OFF');c.execute('DROP TABLE agent_queue')
        c.execute(sql.replace(",'planning'",""));c.commit();c.execute('PRAGMA foreign_keys=ON')
        i=q.enqueue(c,'p','requirements','owner',0,self.lanes,now=100)
        c.execute('CREATE TABLE old_child(id TEXT REFERENCES agent_queue(id))');c.execute('INSERT INTO old_child VALUES(?)',(i,));c.commit()
        q.ensure_schema(c)
        self.assertEqual(q.get(c,'p',i)['kind'],'requirements');self.assertEqual(c.execute('SELECT id FROM old_child').fetchone()[0],i)
        self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])
        self.assertEqual(c.execute('PRAGMA foreign_keys').fetchone()[0],1)
        q.enqueue(c,'p','planning','owner',0,self.lanes,now=101);c.close()
    def test_routes(self):
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/planning/discover'),('p','write'))
        self.assertIsNone(auth_policy.scope(self.c,'POST','/api/projects/p/planning/adopt'))
