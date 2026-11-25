import copy,json,sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import product_requirements as pr
import project_planning as pp
import planning_discovery as pd
import planning_scope as ps
import planning_jobs as pj
import agent_queue as q
import auth_store
import model_provider as mp

def document():
    return dict(problem='Readers need to save and retrieve links securely',goals=['Save and list links'],users=['Readers'],
        scope=['Web link storage and listing in existing projects'],out_of_scope=['Mobile','Sharing','Registration','Project management'],
        assumptions=['Authenticated project membership is provided'],open_questions=[],
        requirements=[
            dict(id='REQ-1',kind='functional',description='Save URL in own project',priority='must',acceptance=['A saved URL is persisted']),
            dict(id='REQ-2',kind='functional',description='List saved links in own project',priority='must',acceptance=['Saved URL appears in list']),
            dict(id='REQ-3',kind='nonfunctional',description='Enforce project isolation',priority='must',acceptance=['Unauthorized cross-project read is denied'])],
        stories=[dict(id='US-1',actor='Reader',goal='Save and retrieve own links securely',benefit='Find links later',requirements=['REQ-1','REQ-2','REQ-3'])])
def extra():
    return dict(forbidden=['register','sign up','create projects'],rules=[
        dict(requirement='REQ-1',kind='implement',evidence='Save URL in own project',matches=[['save','persist','store'],['url','urls']]),
        dict(requirement='REQ-1',kind='verify',evidence='A saved URL is persisted',matches=[['saved','persisted','saving','persists'],['url','urls']]),
        dict(requirement='REQ-2',kind='implement',evidence='List saved links in own project',matches=[['list','display'],['url','urls','links']]),
        dict(requirement='REQ-2',kind='verify',evidence='Saved URL appears in list',matches=[['list','displayed'],['url','urls']]),
        dict(requirement='REQ-3',kind='implement',evidence='Enforce project isolation',matches=[['isolation','unauthorized'],['project','projects']]),
        dict(requirement='REQ-3',kind='verify',evidence='Unauthorized cross-project read is denied',matches=[['unauthorized','denied'],['project','projects']])])
def source():
    d=document()
    return dict(version=1,digest=pp.digest(d),document=d,approved_by='reviewer',approved_at='t',scope_contract=extra())
def raw_a():
    # Exact failing titles and other task content from artifact 14979053586.
    return dict(objective='Implement URL saving and listing functionality for authenticated project members',work=[
        dict(requirement='REQ-1',implement='Create a URL input field and a save button in the project management interface',verify='Test that a saved URL is persisted in the database'),
        dict(requirement='REQ-2',implement='Display a list of saved URLs in the project management interface',verify='Test that saved URLs appear in the list'),
        dict(requirement='REQ-3',implement="Implement project isolation by checking the project ID of the saved URL against the authenticated user's project ID",verify='Test that unauthorized cross-project read is denied')])
def raw_b():
    return dict(objective='Create work items based on the provided requirements',work=[
        dict(requirement='REQ-1',implement='Implement a function to save URLs in the database for the authenticated project member',verify='Test saving a URL and ensure it persists in the database'),
        dict(requirement='REQ-2',implement="Create a function to fetch and display saved URLs in the project member's list",verify="Verify that the saved URLs are correctly displayed in the project member's list"),
        dict(requirement='REQ-3',implement='Develop a mechanism to prevent unauthorized access to saved URLs across different projects',verify='Ensure that unauthorized users cannot access saved URLs from other projects')])
def replacements():
    return [dict(target='TASK-1',title='Save URL in existing project storage'),
        dict(target='TASK-3',title='Display saved URLs for the existing project')]
def patch_reply(patches):
    return json.dumps({p['target']:p['title'] for p in patches})
def discover(patches=None):
    def call(lane,phase,*args):
        if phase=='planning_scope_repair':return patch_reply(replacements() if patches is None else patches)
        return json.dumps(raw_a() if lane=='A' else raw_b())
    return pd.discover(call,source())

class ScopeTests(unittest.TestCase):
    def test_exact_artifact_failure_and_targeted_repair(self):
        src=source();shared=pd.packet(src);policy=shared['planning_scope']
        a=pd.parse(json.dumps(raw_a()),shared);b=pd.parse(json.dumps(raw_b()),shared)
        findings=ps.assess(a,src['document'],policy)
        self.assertEqual(ps.targets(findings),['TASK-1','TASK-3'])
        self.assertTrue(ps.assess(b,src['document'],policy)['passed'])
        calls=[]
        def call(lane,phase,system,user,schema):
            calls.append((lane,phase,json.loads(user)))
            return patch_reply(replacements()) if phase=='planning_scope_repair' else json.dumps(raw_a() if lane=='A' else raw_b())
        e=pd.discover(call,src)
        self.assertEqual([(x[0],x[1]) for x in calls],[('A','planning_proposal'),('A','planning_scope_repair'),('B','planning_proposal')])
        self.assertEqual(calls[0][2],calls[2][2]);self.assertNotIn('candidate',calls[2][2])
        self.assertTrue(e['scope_ready']);self.assertFalse(e['semantic_reviewed'])
        self.assertEqual(e['proposals']['B'],b)
        progress=e['scope_convergence']['A']
        self.assertEqual((progress['before_issues'],progress['after_issues']),(2,0))
        self.assertTrue(progress['passed']);self.assertTrue(progress['unchanged_unflagged'])
        self.assertEqual([t for t in a['tasks'] if t['id'] not in ('TASK-1','TASK-3')],
                         [t for t in e['proposals']['A']['tasks'] if t['id'] not in ('TASK-1','TASK-3')])
    def test_forbidden_normalization_and_acceptance_mapping(self):
        shared=pd.packet(source());raw=raw_b()
        raw['objective']='PROJECT-management interface'
        raw['work'][0]['implement']='Add a search engine'
        plan=pd.parse(json.dumps(raw),shared)
        issues=ps.assess(plan,shared['document'],shared['planning_scope'])['issues']
        self.assertEqual({i['code'] for i in issues},{'forbidden_scope','missing_acceptance_evidence'})
        self.assertEqual(ps.targets(dict(issues=issues)),['TASK-1','objective'])
    def test_contract_must_be_grounded(self):
        for edit in (lambda x:x['rules'][0].update(evidence='invented'),
                     lambda x:x['rules'][0].update(requirement='REQ-999'),
                     lambda x:x['rules'][0].update(matches=[]),
                     lambda x:x['rules'].append(copy.deepcopy(x['rules'][0]))):
            policy=extra();edit(policy)
            with self.assertRaises(ValueError):ps.contract(document(),policy)
        self.assertIn('Project management',ps.contract(document(),dict(forbidden=[],rules=[]))['forbidden'])
    def test_noop_new_issue_and_unflagged_patch_blocked(self):
        for patches in ([dict(target='TASK-1',title=raw_a()['work'][0]['implement']),dict(target='TASK-3',title=raw_a()['work'][1]['implement'])],
                        [dict(target='TASK-1',title='Save URL with registration'),replacements()[1]],
                        [dict(target='TASK-2',title='Test saved URL'),replacements()[1]]):
            e=discover(patches);self.assertFalse(e['scope_ready'])
    def test_invalid_output_retry_cannot_add_third_call(self):
        calls=[]
        def call(lane,phase,*args):
            calls.append((lane,phase))
            return '{}' if phase=='planning_proposal' else json.dumps(raw_a())
        e=pd.discover(call,source())
        self.assertEqual(len(calls),4);self.assertFalse(e['scope_ready'])
        self.assertTrue(all(p!='planning_scope_repair' for _,p in calls))
    def test_storage_recomputes_flags_and_convergence(self):
        e=discover();self.assertTrue(e['scope_ready'])
        e['proposals']['A']['tasks'][0]['title']='Save URL in project management interface'
        e['scope_ready']=True
        self.assertFalse(pd.quality_gate(e,source())['scope_ready'])
        e=discover();e['scope_repairs']['A']['convergence']['after_issues']=99
        self.assertFalse(pd.quality_gate(e,source())['scope_ready'])
        e=discover();del e['scope_repairs']['A']
        self.assertFalse(pd.quality_gate(e,source())['scope_ready'])
    def test_stale_source_digest_rejected(self):
        e=discover();e['source_digest']='wrong'
        with self.assertRaises(ValueError):pd.quality_gate(e,source())

class StorageScopeTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.execute('PRAGMA foreign_keys=ON');self.c.executescript("CREATE TABLE projects(id TEXT PRIMARY KEY);INSERT INTO projects VALUES('p');")
        auth_store.ensure_schema(self.c);pr.ensure_schema(self.c);pp.ensure_schema(self.c);q.ensure_schema(self.c);pj.ensure_schema(self.c)
        auth_store.create_user(self.c,'owner','fixture-password-123');auth_store.grant(self.c,'owner','p','owner')
        row=pr.save(self.c,'p','owner',dict(expected_version=0,document=document()),'t')['current']
        self.row=pr.approve(self.c,'p','owner',dict(version=row['version'],digest=row['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS'),'t')['current']
        self.lanes=mp.load_config(dict(AI_PROVIDER='ollama',AI_MODEL_A='a',AI_MODEL_B='b'))
    def tearDown(self):self.c.close()
    def add(self,**kw):
        return pj.enqueue(self.c,'p','owner',0,self.lanes,'t',version=1,digest=self.row['digest'],**kw)
    def test_failed_scope_never_persisted_ready(self):
        i=self.add(scope_contract=extra());row=q.claim(self.c,9999999999,'t')
        e=discover([dict(target='TASK-1',title='Save URL in project management interface'),replacements()[1]])
        e['scope_ready']=True
        result=pj.persist(self.c,'p',i,e,self.lanes,'t');q.boundary(self.c,row,result,9999999999,'t')
        self.assertEqual(result,'needs_revision');self.assertFalse(pj.latest(self.c,'p')['ready'])
        self.assertEqual(q.get(self.c,'p',i)['status'],'dead');self.assertIsNone(pp.latest(self.c,'p'))
        with self.assertRaises(ValueError):self.add(scope_contract=dict(forbidden=[],rules=[]),retry_of=i)
        retry=self.add(retry_of=i)
        self.assertEqual(json.loads(pj.input_for(self.c,'p',retry)['snapshot'])['scope_contract'],extra())
    def test_read_rechecks_and_legacy_ready_is_blocked(self):
        i=self.add(scope_contract=extra());row=q.claim(self.c,9999999999,'t')
        result=pj.persist(self.c,'p',i,discover(),self.lanes,'t');q.boundary(self.c,row,result,9999999999,'t')
        self.assertTrue(pj.latest(self.c,'p')['ready'])
        e=discover();del e['scope_contract_digest']
        self.c.execute('UPDATE planning_runs SET evidence=? WHERE queue_id=?',(pr.canonical(e),i))
        self.assertFalse(pj.latest(self.c,'p')['ready'])
