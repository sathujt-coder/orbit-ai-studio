"""P6.2b.3 regression from artifact 14982719177; synthetic inference only."""
import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import planning_discovery as pd
import planning_scope as ps
import project_planning as pp
import product_requirements as pr
import model_provider as mp
from test_planning_scope import source

def artifact_a():
    return dict(objective='Implement and verify the functionality for saving and listing links in own projects while enforcing project isolation.',work=[
        dict(requirement='REQ-1',implement='Create a form in the project management interface where readers can input and save URLs. Ensure that the URL is stored securely in the database.',
             verify='Check that the URL is correctly stored in the database and can be retrieved later.'),
        dict(requirement='REQ-2',implement='Develop a list view in the project management interface where readers can view all saved links. Ensure that the list is displayed correctly and that links are a',
             verify='Check that the list view displays all saved links correctly and that links are displayed as expected.'),
        dict(requirement='REQ-3',implement='Implement project isolation by adding authorization checks to ensure that only links saved in the current project can be accessed. Deny unauthorized access to a',
             verify='Check that unauthorized access to links from other projects is denied.')])

def artifact_b():
    return dict(objective='{"id": "WI-1", "description": "Save URL in own project", "acceptance": "A saved URL is persisted", "implementation": "Implement functionality to save URLs in a',
        work=[
            dict(requirement='REQ-1',implement='Implement the functionality to save URLs in the project storage system.',
                 verify='Verify that a saved URL is persisted in the project storage system and can be retrieved later.'),
            dict(requirement='REQ-2',implement='Implement the functionality to list saved URLs in the project.',
                 verify='Verify that saved URLs appear in the list of saved links in the project.'),
            dict(requirement='REQ-3',implement='Implement the functionality to enforce project isolation and deny unauthorized cross-project read access.',
                 verify='Verify that unauthorized cross-project read access is denied and only project members can access their own saved links.')])

REPAIRS={
    'A':{'TASK-1':'Save URLs in existing project storage','TASK-2':'Test that saved URLs persist in storage',
         'TASK-3':'Display the list of saved URLs in the existing project','TASK-5':'Enforce project isolation and deny unauthorized link access'},
    'B':{'objective':'Deliver secure URL saving and listing within existing projects'}
}

def fixture_source():
    # The artifact's exact original scope contract, plus the two new AND
    # vocabulary constraints; the independent smoke regex remains unchanged.
    src=source()
    src['scope_contract']=dict(forbidden=['register','sign up','create projects'],rules=[
        dict(requirement='REQ-1',kind='implement',evidence='Save URL in own project',matches=[['save','store','persist','saving','storing','persisting','insert'],['url','urls','link','links']]),
        dict(requirement='REQ-1',kind='verify',evidence='A saved URL is persisted',matches=[['save','saved','persist','persisted','saving','persists','storage'],['url','urls','link','links'],['save','saved','persist','saving','storage']]),
        dict(requirement='REQ-2',kind='implement',evidence='List saved links in own project',matches=[['list','display','retrieve','view','listing','retrieval','show','fetch'],['url','urls','link','links']]),
        dict(requirement='REQ-2',kind='verify',evidence='Saved URL appears in list',matches=[['list','listed','listing','display','displayed','retrieve','view','fetch'],['url','urls','link','links'],['list','listed','listing','display','retrieve','view','fetch']]),
        dict(requirement='REQ-3',kind='implement',evidence='Enforce project isolation',matches=[['isolation','isolate','authorization','unauthorized','access','deny','restrict','security'],['project','projects']]),
        dict(requirement='REQ-3',kind='verify',evidence='Unauthorized cross-project read is denied',matches=[['isolation','unauthorized','denied','deny','cannot','restrict','access'],['project','projects']])])
    return src

def run(override=None):
    calls=[]
    def call(lane,phase,system,user,schema):
        calls.append((lane,phase,user,schema))
        if phase=='planning_scope_repair':
            return override if override is not None and lane=='A' else json.dumps(REPAIRS[lane])
        return json.dumps(artifact_a() if lane=='A' else artifact_b())
    return pd.discover(call,fixture_source()),calls

class RepairTests(unittest.TestCase):
    def setUp(self):
        self.src=fixture_source();self.shared=pd.packet(self.src)
        self.a=pd.parse(json.dumps(artifact_a()),self.shared);self.b=pd.parse(json.dumps(artifact_b()),self.shared)
        self.findings=ps.assess(self.a,self.shared['document'],self.shared['planning_scope'])
    def test_actual_artifact_text_integrity(self):
        self.assertEqual(len(self.a['tasks'][2]['title']),160)
        self.assertEqual(len(self.a['tasks'][4]['title']),160)
        self.assertEqual(len(self.b['objective']),159)
        self.assertEqual(ps.targets(self.findings),['TASK-1','TASK-2','TASK-3','TASK-5'])
        b=ps.assess(self.b,self.shared['document'],self.shared['planning_scope'])
        self.assertEqual(ps.targets(b),['objective'])
        self.assertIn('structured_text_contamination',ps.content_codes(self.b['objective']))
        self.assertIn('text_at_length_boundary',ps.content_codes(self.a['tasks'][2]['title']))
        self.assertIn('suspected_incomplete_text',ps.content_codes(self.a['tasks'][4]['title']))
    def test_dynamic_schema_and_compact_context(self):
        schema=pd.repair_schema(self.findings)
        self.assertEqual(schema['required'],['TASK-1','TASK-2','TASK-3','TASK-5'])
        self.assertEqual(set(schema['properties']),set(schema['required']))
        self.assertFalse(schema['additionalProperties'])
        self.assertTrue(all(x['maxLength']==160 for x in schema['properties'].values()))
        payload=pd.repair_context(self.shared,self.a,self.findings)
        body=pr.canonical(payload)
        previous=pr.canonical(dict(self.shared,candidate=self.a,issues=self.findings['issues']))
        self.assertLess(len(body.encode()),len(previous.encode()))
        self.assertEqual([x['target'] for x in payload['targets']],schema['required'])
        self.assertNotIn('document',payload);self.assertNotIn('candidate',payload)
        self.assertNotIn(self.a['tasks'][3]['title'],body)
        self.assertNotIn(self.a['tasks'][2]['title'],body)
        self.assertEqual(payload['source_digest'],self.src['digest'])
        self.assertTrue(all('description' in x and 'acceptance' in x and 'match_groups' in x for x in payload['targets']))
    def test_four_calls_fix_both_lanes_and_preserve_good_tasks(self):
        e,calls=run()
        self.assertEqual([(x[0],x[1]) for x in calls],[('A','planning_proposal'),('A','planning_scope_repair'),('B','planning_proposal'),('B','planning_scope_repair')])
        self.assertEqual(calls[0][2],calls[2][2])
        self.assertEqual(calls[3][3]['required'],['objective'])
        self.assertTrue(e['scope_ready']);self.assertTrue(e['content_ready']);self.assertTrue(e['repair_audit_valid'])
        self.assertFalse(e['semantic_reviewed'])
        self.assertEqual(e['proposals']['B']['tasks'],self.b['tasks'])
        self.assertEqual(e['proposals']['A']['objective'],self.a['objective'])
        self.assertEqual([t for t in e['proposals']['A']['tasks'] if t['id'] in ('TASK-4','TASK-6')],[t for t in self.a['tasks'] if t['id'] in ('TASK-4','TASK-6')])
        for lane in 'AB':
            check=e['scope_convergence'][lane]
            self.assertTrue(check['passed']);self.assertGreater(check['before_issues'],0);self.assertEqual(check['after_issues'],0)
            self.assertTrue(check['unchanged_unflagged'])
    def test_exact_key_and_type_diagnostics(self):
        good=REPAIRS['A']
        cases=[('{','invalid_json'),('[]','patch_not_object'),
            ('{"TASK-1":"x","TASK-1":"y"}','duplicate_json_key'),
            (json.dumps({'TASK-1':'x'}),'patch_target_mismatch'),
            (json.dumps(dict(good,SECRET_UNTRUSTED_KEY='x')),'patch_target_mismatch'),
            (json.dumps({**good,'TASK-1':1}),'patch_title_not_string'),
            (json.dumps({**good,'TASK-1':' '}),'patch_title_empty'),
            (json.dumps({**good,'TASK-1':'x'*160}),'patch_title_too_long')]
        for raw,code in cases:
            with self.subTest(code=code):
                with self.assertRaises(pd.RepairError) as err:pd.decode_patch(raw,self.findings)
                self.assertEqual(err.exception.diagnostic['code'],code)
                self.assertNotIn('SECRET_UNTRUSTED_KEY',json.dumps(err.exception.diagnostic))
        self.assertEqual(pd.decode_patch(json.dumps(good),self.findings),[dict(target=k,title=good[k]) for k in sorted(good)])
    def test_failed_patch_is_audited_and_never_retried(self):
        e,calls=run('{"TASK-1":"x","TASK-1":"y"}')
        self.assertEqual(len(calls),4);self.assertFalse(e['scope_ready']);self.assertFalse(e['content_ready'])
        self.assertEqual(e['proposals']['A'],self.a)
        diagnostic=e['scope_repairs']['A']['diagnostic']
        self.assertEqual(diagnostic,dict(code='duplicate_json_key'))
        self.assertEqual(e['attempts']['A'][1]['diagnostic'],diagnostic)
        self.assertTrue(e['scope_convergence']['B']['passed'])
    def test_storage_gate_rechecks_schema_and_context(self):
        e,_=run()
        self.assertTrue(pd.quality_gate(e,self.src)['scope_ready'])
        for key in ('schema_digest','context_digest','context_bytes','targets'):
            tampered=copy.deepcopy(e);tampered['scope_repairs']['A']['request'][key]='wrong'
            self.assertFalse(pd.quality_gate(tampered,self.src)['scope_ready'])
        old=copy.deepcopy(e);del old['content_policy']
        self.assertFalse(pd.quality_gate(old,self.src)['scope_ready'])
        tampered=copy.deepcopy(e);tampered['proposals']['B']['objective']=artifact_b()['objective']
        self.assertFalse(pd.quality_gate(tampered,self.src)['scope_ready'])
    def test_content_controls_and_duplicate_titles(self):
        for bad in ('{"id":"x"}','[{"task":"x"}]','Save URL and','Save URL:','Save\nURL','Save URL (draft','x'*160):
            self.assertTrue(ps.content_codes(bad),bad)
        for clean in ('Save URLs in existing project storage','Kiểm tra quyền truy cập dự án','Enforce access control (RBAC)'):
            self.assertEqual(ps.content_codes(clean),[],clean)
        plan=copy.deepcopy(self.a);plan['tasks'][1]['title']=plan['tasks'][0]['title'].upper()
        self.assertIn(dict(target='TASK-2',code='duplicate_verification_title'),ps.content_findings(plan)['issues'])
    def test_admission_failure_not_replayed(self):
        for error in (ValueError('stale source'),mp.ProviderError('offline')):
            calls=[]
            def call(*args):calls.append(args);raise error
            with self.assertRaises(type(error)):pd.discover(call,self.src)
            self.assertEqual(len(calls),1)


class Artifact14993296469Tests(unittest.TestCase):
    def setUp(self):
        self.src=fixture_source();self.shared=pd.packet(self.src)
        self.policy=self.shared['planning_scope']
        self.raw_a=dict(objective='Implement URL saving and listing features in existing projects',work=[
            dict(requirement='REQ-1',implement='Create a form for saving URLs in the project management interface',verify='Ensure URLs are persisted in the database'),
            dict(requirement='REQ-2',implement='Display a list of saved URLs in the project management interface',verify='Ensure URLs appear in the list'),
            dict(requirement='REQ-3',implement='Implement project isolation to prevent unauthorized access to other projects',verify='Ensure unauthorized cross-project reads are denied')])
        self.raw_b=dict(objective='Implement URL storage and project isolation',work=[
            dict(requirement='REQ-1',implement='Save URL in own project',verify='A saved URL is persisted'),
            dict(requirement='REQ-2',implement='List saved links in own project',verify='Saved URL appears in list'),
            dict(requirement='REQ-3',implement='Enforce project isolation',verify='Unauthorized cross-project read is denied')])
        self.bad={'TASK-1':'Save URL in own project','TASK-2':'Verify URL persistence','TASK-3':'List saved links in own project'}
        self.good=dict(self.bad,**{'TASK-2':'Verify saved URL is persisted in project storage'})
        self.before=pd.parse(json.dumps(self.raw_a),self.shared)
        self.findings=ps.assess(self.before,self.src['document'],self.policy)
    def test_historical_repair_loses_previously_satisfied_group(self):
        revised=ps.patch(self.before,pd.decode_patch(json.dumps(self.bad),self.findings),self.findings,self.src['document'])
        self.assertEqual([x['target'] for x in self.findings['issues']],['TASK-1','TASK-2','TASK-3'])
        result=ps.convergence(self.before,revised,self.src['document'],self.policy)
        self.assertEqual((result['before_issues'],result['after_issues']),(3,1))
        self.assertFalse(result['passed']);self.assertEqual(result['lost_scope_groups'],[
            dict(target='TASK-2',requirement='REQ-1',kind='verify',evidence='A saved URL is persisted',
                 lost_groups=[['save','saved','persist','persisted','saving','persists','storage']])])
    def test_shared_hints_cover_all_groups_and_preserve_alternatives(self):
        import planning_constraints as pc
        ctx=pd.repair_context(self.shared,self.before,self.findings)
        self.assertEqual(self.shared['required_exact_terms']['REQ-1']['verify'],['save','url'])
        target=next(x for x in ctx['targets'] if x['target']=='TASK-2')
        self.assertEqual(target['required_exact_terms'],['save','url'])
        self.assertEqual(len(target['match_groups']),3)
        self.assertEqual(target['missing_evidence'][0]['missing_groups'],[['save','saved','persist','saving','storage']])
        self.assertEqual(pc.missing_groups(' '.join(target['required_exact_terms']),target['match_groups']),[])
        self.assertEqual(pc.required_exact_terms(target['match_groups'],'A saved URL'),[])
        self.assertEqual(pc.required_exact_terms(target['match_groups'],'URL persistence'),['save'])
        self.assertTrue(ps.assess(pd.parse(json.dumps(self.raw_b),self.shared),self.src['document'],self.policy)['passed'])
    def test_bounded_repair_and_replayed_provenance(self):
        calls=[]
        def call(lane,phase,system,user,schema):
            calls.append((lane,phase,json.loads(user)))
            return json.dumps(self.good if phase=='planning_scope_repair' else self.raw_a if lane=='A' else self.raw_b)
        e=pd.discover(call,self.src)
        self.assertEqual(len(calls),3);self.assertTrue(e['scope_ready'])
        self.assertEqual(e['scope_convergence']['A']['lost_scope_groups'],[])
        self.assertEqual(e['scope_convergence']['A']['after_issues'],0)
        self.assertEqual(e['proposals']['A']['tasks'][3:],self.before['tasks'][3:])
        for key in ('constraint_policy','proposal_context_digest'):
            bad=copy.deepcopy(e);bad[key]='wrong'
            self.assertFalse(pd.quality_gate(bad,self.src)['scope_ready'])
        bad=copy.deepcopy(e);bad['scope_repairs']['A']['convergence']['lost_scope_groups']=['forged']
        self.assertFalse(pd.quality_gate(bad,self.src)['scope_ready'])
    def test_bad_patch_cannot_add_third_call(self):
        calls=[]
        def call(lane,phase,*args):
            calls.append((lane,phase))
            return json.dumps(self.bad if phase=='planning_scope_repair' else self.raw_a if lane=='A' else self.raw_b)
        e=pd.discover(call,self.src)
        self.assertFalse(e['scope_ready']);self.assertEqual(len(calls),3)
        self.assertTrue(e['scope_convergence']['A']['lost_scope_groups'])
