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
        patch={pid:{k:v for k,v in values.items() if k in schema['properties'][pid]['required']} for pid,values in output(doc,ids).items()}
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
            record.append(phase);patch={pid:{k:v for k,v in values.items() if k in schema['properties'][pid]['required']} for pid,values in output(self.doc,schema['required']).items()}
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


# Original model text from artifact 14990478494, not a provider substitute in CI.
ARTIFACT_PATCHES={
    'A':[
        {'D-1.1':dict(action='Implement URL saving',evidence='Database records',output='Persisted URL in own project'),
         'D-1.2':dict(action='Verify URL persistence',evidence='Database records',output='Persisted URL appears in list'),
         'D-2.1':dict(action='Implement URL listing',evidence='Database records',output='Saved URL appears in list')},
        {'D-1.1':dict(action='Implement URL persistence',evidence='URL stored in project database',output='Persisted URL in own project'),
         'D-1.2':dict(action='Verify URL persistence',evidence='URL listed in project view',output='URL appears in project list'),
         'D-2.1':dict(action='Implement URL listing',evidence='URLs displayed in project view',output='List saved URLs in project')}],
    'B':[
        {'D-1.1':dict(action='implement',evidence='URL persistence record',output='URL saved in project'),
         'D-1.2':dict(action='verify',evidence='URL persistence verification report',output='URL persistence confirmed'),
         'D-2.1':dict(action='implement',evidence='List of saved links',output='Saved links displayed')},
        {'D-1.1':dict(action='Implement URL persistence in own project',evidence='Saved URL appears in project list',output='Persisted URL saved in project'),
         'D-1.2':dict(action='Verify URL persistence in own project',evidence='URL is persisted in project',output='URL persists in project'),
         'D-2.1':dict(action='Implement saved URL list display',evidence='Saved URLs appear in project list',output='Saved URLs displayed in project list')}]
}

class Artifact14990478494Tests(unittest.TestCase):
    def setUp(self):
        import planning_scope as ps
        from test_planning_repair import fixture_source
        src=fixture_source();self.src=source()
        self.src['policy']=ps.contract(self.src['document'],src['scope_contract'])
        self.ids=['D-1.1','D-1.2','D-2.1']
    def base(self,lane):
        self.src['lane']=lane
        reqs=self.src['document']['requirements']
        raw=dict(objective='Implement URL saving and listing features in existing projects' if lane=='A' else 'Implement URL storage and project isolation',
            work=[dict(requirement=r['id'],implement=r['description'],verify=r['acceptance'][0]) for r in reqs])
        self.src['proposal']=pd.parse(json.dumps(raw),dict(document=self.src['document']))
        return w.skeleton(self.src)
    def test_exact_historical_missing_groups_still_block(self):
        # Artifact 14990478494, SHA256 d4d93e556ab460afa3d1bf193b8add9bbcea206aa9c63aa24819d4a90e64e424.
        # A uses "persistence", which satisfies neither verification group.
        # B uses "persisted" and "persists", satisfying only the wider group.
        expected={
            'A':[
                dict(package='D-1.1',field='details',code='missing_scope_evidence',
                    requirement='REQ-1',criterion='Save URL in own project',
                    missing_groups=[['save','store','persist','saving','storing','persisting','insert']]),
                dict(package='D-1.2',field='details',code='missing_scope_evidence',
                    requirement='REQ-1',criterion='A saved URL is persisted',
                    missing_groups=[['save','saved','persist','persisted','saving','persists','storage'],
                                    ['save','saved','persist','saving','storage']])],
            'B':[
                dict(package='D-1.1',field='details',code='missing_scope_evidence',
                    requirement='REQ-1',criterion='Save URL in own project',
                    missing_groups=[['save','store','persist','saving','storing','persisting','insert']]),
                dict(package='D-1.2',field='details',code='missing_scope_evidence',
                    requirement='REQ-1',criterion='A saved URL is persisted',
                    missing_groups=[['save','saved','persist','saving','storage']])]}
        for lane in 'AB':
            with self.subTest(lane=lane):
                doc=self.base(lane)
                before=d.apply(doc,ARTIFACT_PATCHES[lane][0],self.src)
                after=d.apply(before,ARTIFACT_PATCHES[lane][1],self.src)
                issues=d.local_issues(after,self.src,self.ids)
                missing=[x for x in issues if x['code']=='missing_scope_evidence']
                self.assertEqual(missing,expected[lane])
                self.assertFalse(w.assess(after,self.src)['detail_ready'])
                self.assertTrue(any(x['code']=='action_lacks_specificity' or x['code']=='action_missing_technical_anchor' for x in d.local_issues(before,self.src,self.ids)))
    def test_exact_terms_and_field_level_repair_of_both_artifact_lanes(self):
        for lane in 'AB':
            doc=self.base(lane);record=[]
            initial=ARTIFACT_PATCHES[lane][0]
            before=d.apply(doc,initial,self.src)
            issues=d.local_issues(before,self.src,self.ids)
            fields=d.repair_fields(self.ids,issues)
            payload=d.context(self.src,before,list(fields),issues,fields)
            self.assertEqual(fields['D-1.1'],['action','evidence'])
            self.assertNotIn('output',fields['D-1.1'])
            self.assertEqual(payload['targets'][0]['retained']['output'],initial['D-1.1']['output'])
            self.assertIn('save',payload['targets'][0]['required_exact_terms'])
            def call(phase,system,user,schema):
                record.append((phase,schema))
                if len(record)==1:return json.dumps(initial)
                full=output(doc,schema['required'])
                # Repair test outputs are synthetic and only use schema-authorized fields.
                return json.dumps({pid:{k:values[k] for k in schema['properties'][pid]['required']} for pid,values in full.items()})
            e=d.run(call,self.src,doc)
            self.assertTrue(e['ready'],e['analysis']['issues'])
            self.assertEqual(e['call_count'],3)
            self.assertEqual(e['history'][0]['attempts'][1]['request']['fields'],fields)
            self.assertTrue(e['history'][0]['attempts'][1]['convergence']['passed'])
            for pid in fields:
                for k in w.DETAIL_FIELDS:
                    if k not in fields[pid]:self.assertEqual(d.packages(e['candidate'])[pid][k],initial[pid][k])
    def test_unflagged_field_and_forged_convergence_blocked(self):
        doc=self.base('A')
        before=d.apply(doc,ARTIFACT_PATCHES['A'][0],self.src)
        issues=d.local_issues(before,self.src,self.ids);fields=d.repair_fields(self.ids,issues)
        with self.assertRaises(ValueError):d.decode(json.dumps(ARTIFACT_PATCHES['A'][1]),list(fields),fields)
        complete=d.apply(doc,output(doc,self.ids),self.src)
        audit=d.convergence(before,complete,self.src,self.ids,fields)
        self.assertFalse(audit['unchanged_unflagged']);self.assertFalse(audit['passed'])
        src=source();blank=w.skeleton(src)
        e=d.run(synthetic(blank,[],True),src,blank)
        e['history'][0]['attempts'][1]['convergence']['after_issues']=42
        with self.assertRaises(ValueError):d.gate(e,src,blank)
    def test_shared_constraints_audit_previously_satisfied_group_loss(self):
        import planning_constraints as pc
        doc=self.base('A')
        before=d.apply(doc,{'D-1.2':dict(action='Test persisted URL after reopening database',
            output='Fresh connection test report',evidence='Expected database row identifier assertion')},self.src)
        fields={'D-1.2':['action']}
        ctx=d.context(self.src,before,list(fields),d.local_issues(before,self.src,list(fields)),fields)
        self.assertEqual(ctx['targets'][0]['required_exact_terms'],['save','url'])
        after=d.apply(before,{'D-1.2':dict(action='Test URL persistence after reopening database')},self.src)
        audit=d.convergence(before,after,self.src,list(fields),fields)
        self.assertFalse(audit['passed']);self.assertTrue(audit['unchanged_unflagged'])
        self.assertEqual(audit['lost_scope_groups'],[
            dict(package='D-1.2',requirement='REQ-1',kind='verify',evidence='A saved URL is persisted',
                 lost_groups=[['save','saved','persist','persisted','saving','persists','storage']])])
        self.assertEqual(pc.required_exact_terms([['cross project','isolation'],['project']],''),['cross project'])
        self.assertEqual(pc.required_exact_terms([['cross project','isolation'],['project']],'Cross-project'),[])
        self.assertEqual(pc.missing_groups('persistence',[['persist']]),[['persist']])
    def test_technical_specificity_and_exact_word_matching(self):
        self.assertIn('action_missing_technical_anchor',w.technical_codes('action','Implement URL persistence in own project'))
        self.assertIn('action_lacks_specificity',w.technical_codes('action','Verify URL persistence'))
        self.assertIn('evidence_lacks_specificity',w.technical_codes('evidence','Database records'))
        self.assertEqual(w.technical_codes('action','Add a save handler using authenticated project identifiers'),[])
        self.assertEqual(w.technical_codes('evidence','Stored URL and project identifier assertion'),[])
        self.assertEqual(w.missing_groups('URL persisted and stored',dict(matches=[['persist','store']])),[['persist','store']])
