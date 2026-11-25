"""WBS gate and exact provenance regression; no inference provider calls."""
import copy,json,sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import product_requirements as pr
import project_planning as pp
import planning_discovery as pd
import planning_jobs as pj
import work_breakdown as w
import agent_queue as q
import auth_store,auth_policy,model_provider as mp
from test_planning_scope import document

# Actual final PM titles/objectives from artifact 14988175113.
def raw(lane):
    a=lane=='A'
    return dict(objective='Implement URL saving and listing functionality in existing projects' if a else 'Implement URL storage and project isolation',
        work=[
        dict(requirement='REQ-1',implement='Save URL in own project',verify='Ensure URLs are saved securely and persist in the database' if a else 'A saved URL is persisted'),
        dict(requirement='REQ-2',implement='List saved links in own project',verify='Ensure URLs are listed correctly and accessible to the user' if a else 'Saved URL appears in list'),
        dict(requirement='REQ-3',implement="Implement project isolation to prevent unauthorized access to other projects' URLs" if a else 'Enforce project isolation',
             verify='Enforce project isolation' if a else 'Unauthorized cross-project read is denied')])

def detail(doc):
    # Human-authored fixture design, not AI output or executed verification.
    rows=[
        ('Add a save handler using the authenticated project identifier','Project scoped URL storage handler','Database write integration test record'),
        ('Test saving and retrieving a URL after reconnecting to storage','Persistence test with a fresh storage connection','Stored URL and project identifier assertion'),
        ('Fetch saved links filtered by authenticated project identifier','Project filtered saved URL query','Query implementation review record'),
        ('Verify the saved URL appears in the current project list','List retrieval integration test case','Expected URL compared with returned list'),
        ('Apply project isolation to link reads using authorized membership','Project membership authorization guard','Authorization implementation review checklist'),
        ('Test unauthorized read of another project URL and assert denial','Cross project negative access test','Denied response and absence of foreign URL')]
    out=copy.deepcopy(doc)
    for p,values in zip([p for d in out['deliverables'] for p in d['packages']],rows):
        p.update(zip(w.DETAIL_FIELDS,values))
    return out

class WbsTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row;self.c.execute('PRAGMA foreign_keys=ON')
        self.c.executescript("CREATE TABLE projects(id TEXT PRIMARY KEY);INSERT INTO projects VALUES('p'),('q');")
        auth_store.ensure_schema(self.c);pr.ensure_schema(self.c);pp.ensure_schema(self.c);q.ensure_schema(self.c);pj.ensure_schema(self.c);w.ensure_schema(self.c)
        for user,role in [('owner','owner'),('reviewer','reviewer'),('viewer','viewer'),('developer','developer')]:
            auth_store.create_user(self.c,user,'wbs-fixture-password');auth_store.grant(self.c,user,'p',role)
        self.lanes=mp.load_config(dict(AI_PROVIDER='ollama',AI_MODEL_A='a',AI_MODEL_B='b'))
        self.row=self.new_prd(0)
    def tearDown(self):self.c.close()
    def new_prd(self,v,doc=None):
        row=pr.save(self.c,'p','owner',dict(expected_version=v,document=doc or document()),'t')['current']
        return pr.approve(self.c,'p','reviewer',dict(version=row['version'],digest=row['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS'),'t')['current']
    def run_pm(self,scope=None):
        i=pj.enqueue(self.c,'p','owner',0,self.lanes,'t',version=self.row['version'],digest=self.row['digest'],scope_contract=scope)
        row=q.claim(self.c,9999999999,'t');src=pj.checked_input(self.c,'p',i)
        e=pd.discover(lambda lane,*args:json.dumps(raw(lane)),src)
        result=pj.persist(self.c,'p',i,e,self.lanes,'t');q.boundary(self.c,row,result,9999999999,'t')
        self.assertTrue(pj.latest(self.c,'p')['ready'])
        return i
    def seed(self,lane='A',v=0,actor='owner',**kw):
        src=w.view(self.c,'p')['sources'][lane]
        return w.save(self.c,'p',actor,dict(src,expected_version=v,confirmation='CREATE WBS DRAFT',**kw),'t',seed=True)
    def save(self,d,v=1,actor='developer',**kw):
        src=w.view(self.c,'p')['sources']['A'];body=dict(src,expected_version=v,document=d);body.update(kw)
        return w.save(self.c,'p',actor,body,'t')
    def test_resource_estimates_revision_and_cpm(self):
        self.run_pm();v=self.seed();r=w.resource_estimates
        self.assertFalse(v['dependency_graph']['timing_ready'])
        doc=v['resource_estimates']['draft'];p=v['current']
        body=dict(expected_version=0,wbs_version=p['version'],wbs_digest=p['digest'],
                  document=doc,confirmation='SAVE RESOURCE ESTIMATES')
        with self.assertRaises(PermissionError):r.save(self.c,'p','viewer',body,'t',v)
        for item in doc['packages']:item.update(effort_minutes=30,role='QA' if item['id'].endswith('.2') else 'Dev')
        doc['packages'][0]['effort_minutes']=True
        with self.assertRaises(ValueError):r.save(self.c,'p','owner',body,'t',v)
        doc['packages'][0]['effort_minutes']=None
        partial=r.save(self.c,'p','owner',body,'t',v)
        self.assertFalse(partial['analysis']['ready'])
        self.assertIsNone(partial['analysis']['total_effort_minutes'])
        self.assertIsNone(partial['analysis']['dependency_graph']['critical_path_minutes'])
        doc['packages'][0]['effort_minutes']=30
        with self.assertRaises(ValueError):r.save(self.c,'p','owner',body,'t',v)
        body['expected_version']=1
        ready=r.save(self.c,'p','developer',body,'t',v)
        self.assertTrue(ready['analysis']['ready'])
        self.assertEqual(ready['analysis']['total_effort_minutes'],180)
        self.assertEqual(ready['analysis']['known_effort_by_role'],{'Dev':90,'QA':90})
        self.assertEqual(w.view(self.c,'p')['dependency_graph']['critical_path_minutes'],60)
        self.assertEqual(w.view(self.c,'p')['current']['digest'],p['digest'])
        newer=self.save(detail(p['document']))
        self.assertTrue(newer['resource_estimates']['stale'])
        self.assertIsNone(newer['resource_estimates']['analysis'])
        self.assertFalse(newer['dependency_graph']['timing_ready'])
        body['expected_version']=2
        with self.assertRaises(ValueError):r.save(self.c,'p','owner',body,'t',newer)
        self.assertIsNone(r.view(self.c,'q',None,False)['current'])
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/planning/wbs/estimates'),('p','write'))

    def test_sprint_schedule_capacity_dependency_milestone_and_staleness(self):
        self.run_pm();v=self.seed();r=w.resource_estimates;s=w.sprint_schedule
        self.assertIsNone(v['sprint_schedule']['draft'])
        p=v['current'];doc=v['resource_estimates']['draft']
        for item in doc['packages']:item.update(effort_minutes=30,role='QA' if item['id'].endswith('.2') else 'Dev')
        body=dict(expected_version=0,wbs_version=p['version'],wbs_digest=p['digest'],document=doc,confirmation='SAVE RESOURCE ESTIMATES')
        r.save(self.c,'p','owner',body,'t',v);v=w.view(self.c,'p')
        schedule=v['sprint_schedule']['draft']
        schedule['sprints']=[dict(id='S1',start='2026-12-01',end='2026-12-07',capacity={'Dev':90,'QA':90}),
            dict(id='S2',start='2026-12-08',end='2026-12-14',capacity={'Dev':90,'QA':90})]
        for item in schedule['assignments']:item['sprint']='S2' if item['id'].endswith('.2') else 'S1'
        schedule['milestones']=[dict(id='M1',title='All packages',sprint='S2',packages=[x['id'] for x in schedule['assignments']])]
        payload=dict(v['sprint_schedule']['source'],expected_version=0,document=schedule,confirmation='SAVE SPRINT SCHEDULE')
        with self.assertRaises(PermissionError):s.save(self.c,'p','viewer',payload,'t',v)
        bad=copy.deepcopy(schedule);bad['sprints'][1]['start']='2026-12-07'
        with self.assertRaises(ValueError):s.analyze(bad,v)
        bad=copy.deepcopy(schedule);bad['assignments'][0]['sprint']='S2';bad['assignments'][1]['sprint']='S1'
        bad['sprints'][0]['capacity']['QA']=0;bad['milestones'][0]['sprint']='S1'
        codes={x['code'] for x in s.analyze(bad,v)[1]['issues']}
        self.assertTrue({'dependency_order','capacity_exceeded','milestone_dependency'}<=codes)
        ready=s.save(self.c,'p','developer',payload,'t',v)
        self.assertTrue(ready['analysis']['ready']);self.assertFalse(ready['analysis']['execution_authorized'])
        self.assertEqual(ready['analysis']['loads']['S1']['Dev'],90)
        with self.assertRaises(ValueError):s.save(self.c,'p','owner',payload,'t',v)
        body['expected_version']=1;r.save(self.c,'p','owner',body,'t',v)
        fresh=w.view(self.c,'p');self.assertTrue(fresh['sprint_schedule']['stale'])
        self.assertIsNone(fresh['sprint_schedule']['analysis'])
        with self.assertRaises(ValueError):s.save(self.c,'p','owner',payload,'t',fresh)
        self.assertIsNone(w.view(self.c,'q')['sprint_schedule']['current'])
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/planning/wbs/schedule'),('p','write'))

    def test_cross_review_strict_dual_gate(self):
        review=w.planning_review
        good=dict(verdict='APPROVE',score=80,feedback='Concrete review evidence',checks={k:True for k in review.DIMENSIONS})
        self.assertTrue(review.gate({'A':good,'B':good}))
        for change in [dict(score=79),dict(score=True),dict(verdict='REQUEST_CHANGES'),dict(checks={**good['checks'],'schedule':False}),dict(feedback='')]:
            self.assertFalse(review.gate({'A':good,'B':{**good,**change}}))
        self.assertFalse(review.gate({'A':good}))
        with self.assertRaises(ValueError):review.parse('{"score":80,"score":100}')
        self.run_pm();v=self.seed()
        self.assertFalse(v['cross_review']['input_ready'])
        self.assertFalse(v['cross_review']['quality_ready'])
        self.assertFalse(v['cross_review']['execution_authorized'])
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/planning/wbs/review'),('p','write'))

    def test_adoption_blocked_without_current_review_and_project_approval(self):
        self.run_pm();v=self.seed();a=w.planning_adoption
        self.assertFalse(v['adoption']['can_adopt'])
        body=dict(expected_version=0,bundle_digest='bad',review_id='bad',evidence_digest='bad',confirmation='APPROVE AND ADOPT PLANNING BUNDLE')
        with self.assertRaises(PermissionError):a.adopt(self.c,'p','developer',body,'t',v)
        with self.assertRaises(ValueError):a.adopt(self.c,'p','reviewer',body,'t',v)
        self.assertIsNone(a.latest(self.c,'p'))
        self.assertIsNone(a.latest(self.c,'q'))
        self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/planning/wbs/adopt'),('p','approve'))

    def test_no_pm_no_wbs_and_separate_plan(self):
        self.assertEqual(w.view(self.c,'p')['sources'],{})
        with self.assertRaises(ValueError):w.current_source(self.c,'p','A')
        self.run_pm();view=self.seed()
        self.assertTrue(view['analysis']['structure_ready']);self.assertFalse(view['decomposition_ready'])
        self.assertEqual(view['analysis']['deliverable_count'],3);self.assertEqual(view['analysis']['package_count'],6)
        self.assertEqual(view['analysis']['criterion_count'],3)
        self.assertEqual(len(view['analysis']['issues']),18)
        self.assertIsNone(pp.latest(self.c,'p'));self.assertIsNone(w.latest(self.c,'q'))
        self.assertEqual(list(self.c.execute('PRAGMA foreign_key_check')),[])
    def test_exact_multiple_criteria_and_dependencies(self):
        self.run_pm();src=w.current_source(self.c,'p','A')
        src['document']['requirements'][0]['acceptance'].append('A saved URL survives restart')
        d=w.skeleton(src);a=w.assess(d,src)
        self.assertEqual(a['package_count'],7)
        self.assertEqual(a['traceability']['REQ-1/AC-2'],dict(requirement='REQ-1',criterion='A saved URL survives restart',implement=['D-1.1'],verify=['D-1.3']))
        self.assertEqual(d['deliverables'][0]['packages'][2]['depends_on'],['D-1.1'])
    def test_artifact_generic_titles_do_not_pass(self):
        self.run_pm();v=self.seed();d=copy.deepcopy(v['current']['document'])
        for group in d['deliverables']:
            for p in group['packages']:
                for key in w.DETAIL_FIELDS:p[key]=p['source_title']
        a=self.save(d)['analysis']
        self.assertFalse(a['detail_ready'])
        self.assertIn(dict(package='D-3.2',field='action',code='verification_action_required'),a['issues'])
        self.assertTrue(any(i['code']=='requirement_or_proposal_restatement' for i in a['issues']))
    def test_complete_details_and_exact_traceability(self):
        self.run_pm();v=self.seed();d=detail(v['current']['document'])
        saved=self.save(d);self.assertTrue(saved['decomposition_ready'])
        self.assertEqual(saved['current']['version'],2);self.assertEqual(saved['analysis']['issues'],[])
        self.assertFalse(saved['analysis']['semantic_reviewed'])
        self.assertIsNone(pp.latest(self.c,'p'));self.assertEqual(len(saved['history']),2)
        self.assertEqual(saved['analysis']['traceability']['REQ-3/AC-1']['verify'],['D-3.2'])
    def test_tampering_rejected(self):
        self.run_pm();d=self.seed()['current']['document']
        for change in (lambda x:x['deliverables'].pop(),
                       lambda x:x['deliverables'][0]['acceptance'][0].update(text='changed'),
                       lambda x:x['deliverables'][0]['packages'][1].update(criteria=['REQ-2/AC-1']),
                       lambda x:x['deliverables'][0]['packages'][1].update(depends_on=[]),
                       lambda x:x['deliverables'][0]['packages'][0].update(source_task='TASK-99'),
                       lambda x:x['deliverables'][0]['packages'][0].update(effort_minutes=30)):
            bad=copy.deepcopy(d);change(bad)
            with self.assertRaises(ValueError):self.save(bad)
        self.assertEqual(w.latest(self.c,'p')['version'],1)
    def test_detail_gate_scope_duplicates_and_text(self):
        self.run_pm();d=detail(self.seed()['current']['document'])
        p=d['deliverables'][0]['packages'][0];p['action']='Create project management interface';p['output']='{"bad": true}'
        p['evidence']=d['deliverables'][1]['packages'][0]['evidence']
        a=self.save(d)['analysis'];codes={x['code'] for x in a['issues']}
        self.assertFalse(a['detail_ready']);self.assertTrue({'forbidden_scope','structured_text_contamination','duplicate_detail'}<=codes)
    def test_rbac_stale_version_digest_and_source(self):
        self.run_pm()
        for actor in ('reviewer','viewer'):
            with self.assertRaises(PermissionError):self.seed(actor=actor)
        d=self.seed()['current']['document']
        for kw in (dict(expected_version=0),dict(proposal_digest='bad'),dict(queue_id='bad'),dict(requirements_version=True),dict(lane='B')):
            with self.assertRaises(ValueError):self.save(d,**kw)
        self.row=self.new_prd(1)
        self.assertTrue(w.view(self.c,'p')['stale']);self.assertFalse(w.view(self.c,'p')['decomposition_ready'])
        self.run_pm();self.assertTrue(w.view(self.c,'p')['stale'])
        self.assertEqual(self.seed(v=1)['current']['version'],2)
    def test_new_discovery_and_corrupt_wbs_invalidate(self):
        self.run_pm();self.seed();self.run_pm()
        self.assertTrue(w.view(self.c,'p')['stale'])
        self.seed(v=1);self.c.execute("UPDATE work_breakdowns SET digest='bad' WHERE version=2")
        self.assertTrue(w.view(self.c,'p')['stale']);self.assertFalse(w.view(self.c,'p')['decomposition_ready'])
    def test_routes(self):
        for suffix in ('/wbs','/wbs/seed'):
            self.assertEqual(auth_policy.scope(self.c,'POST','/api/projects/p/planning'+suffix),('p','write'))
        self.assertIsNone(auth_policy.scope(self.c,'POST','/api/projects/p/planning/wbs/approve'))

    def test_dependency_graph_is_structural_and_source_bound(self):
        self.run_pm()
        view=self.seed()
        graph=view['dependency_graph']
        self.assertEqual(graph['node_count'],6)
        self.assertEqual(graph['edge_count'],3)
        self.assertEqual(graph['layers'],[['D-1.1','D-2.1','D-3.1'],['D-1.2','D-2.2','D-3.2']])
        self.assertFalse(graph['timing_ready'])
        self.assertIsNone(graph['critical_path'])
        self.assertFalse(view['decomposition_ready'])
        self.assertEqual(self.save(detail(view['current']['document']))['dependency_graph'],graph)
        self.row=self.new_prd(1)
        stale=w.view(self.c,'p')
        self.assertTrue(stale['stale'])
        self.assertIsNone(stale['dependency_graph'])
        self.assertFalse(stale['decomposition_ready'])
