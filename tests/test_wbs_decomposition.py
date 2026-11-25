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

def wire_output(doc,schema):
    ids=list(dict.fromkeys(key.rsplit('.',1)[0] for key in schema['required']))
    values=d.flatten(output(doc,ids))
    return {key:values[key] for key in schema['required']}

def synthetic(doc,record,broken=False):
    def call(phase,system,user,schema):
        ids=list(dict.fromkeys(key.rsplit('.',1)[0] for key in schema['required']))
        record.append((phase,ids,json.loads(user)))
        patch=wire_output(doc,schema)
        if broken and len(record)==1:patch[ids[0]+'.action']='Create project management interface'
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
            record.append(phase);patch=wire_output(self.doc,schema)
            for key in patch:
                if key.endswith('.action'):patch[key]='Create project management interface'
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
            self.assertEqual(payload['targets'][0]['retained_fields'],['output'])
            self.assertNotIn(initial['D-1.1']['output'],json.dumps(payload))
            self.assertIn('save',payload['targets'][0]['required_exact_terms'])
            def call(phase,system,user,schema):
                record.append((phase,schema))
                if len(record)==1:return json.dumps(d.flatten(initial))
                # Repair test outputs are synthetic and only use schema-authorized fields.
                return json.dumps(wire_output(doc,schema))
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
        with self.assertRaises(ValueError):d.decode(json.dumps(d.flatten(ARTIFACT_PATCHES['A'][1])),list(fields),fields)
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


# Exact PM titles and model patches from artifact 14998801172.
# The historical nested patch is converted losslessly to the new flat wire.
ARTIFACT_14998801172={
    'A':[
        {'D-1.1':dict(action='Save URL in own project',output='Persisted URL',evidence='Persisted URL test assertion'),
         'D-1.2':dict(action='Save URL in own project',output='Persisted URL',evidence='Persisted URL test assertion'),
         'D-2.1':dict(action='List saved links in own project',output='Listed URLs',evidence='Listed URLs test assertion')},
        {'D-1.1':dict(action='Save URL',output='Persisted URL test assertion'),
         'D-1.2':dict(action='Save URL',output='Persisted URL test assertion',evidence='Persisted URL test assertion'),
         'D-2.1':dict(action='List saved links',output='Listed URLs test assertion')}],
    'B':[
        {'D-1.1':dict(action='Save URL in own project',output='Persisted URL in own project',evidence='Persisted URL retrieval test assertion'),
         'D-1.2':dict(action='Verify saved URL in own project',output='Persisted URL in own project',evidence='Persisted URL visibility test assertion'),
         'D-2.1':dict(action='List saved links in own project',output='List of saved links displayed',evidence='Saved link list retrieval test assertion')},
        {'D-1.1':dict(action='Save URL in own project'),
         'D-1.2':dict(output='Verify saved URL in own project'),
         'D-2.1':dict(action='List saved links in own project')}]}
ARTIFACT_PM={
    'A':("Implement URL saving and listing features for existing projects",[
        ("Create a function to save URLs in the user's project","Save URL in own project"),
        ("Develop a function to list saved URLs in the user's project","Verify URLs are displayed correctly in the list"),
        ("Implement project isolation to prevent unauthorized access to other projects","Ensure unauthorized users cannot access other projects")]),
    'B':("Implement URL storage and project isolation",[
        ("Save URL in own project","A saved URL is persisted"),
        ("List saved links in own project","A saved URL appears in list"),
        ("Enforce project isolation","Unauthorized cross-project read is denied")])}

class FlatTechnicalProtocolTests(unittest.TestCase):
    def artifact(self,lane):
        from test_planning_repair import fixture_source
        import planning_scope as ps
        src=source();approved=fixture_source()
        src['lane']=lane
        src['policy']=ps.contract(src['document'],approved['scope_contract'])
        objective,titles=ARTIFACT_PM[lane]
        raw=dict(objective=objective,work=[dict(requirement=req['id'],implement=t[0],verify=t[1])
            for req,t in zip(src['document']['requirements'],titles)])
        src['proposal']=pd.parse(json.dumps(raw),dict(document=src['document']))
        return src,w.skeleton(src)
    def test_exact_flat_schema_and_role_contracts(self):
        src,doc=self.artifact('A')
        ids=d.batches(doc)[0]
        body,shape,meta=d.request(src,doc,ids)
        keys=[pid+'.'+k for pid in ids for k in w.DETAIL_FIELDS]
        self.assertEqual(shape['required'],keys);self.assertEqual(meta['keys'],keys)
        self.assertEqual(set(shape['properties']),set(keys));self.assertFalse(shape['additionalProperties'])
        self.assertTrue(all(x['type']=='string' and x['maxLength']==159 for x in shape['properties'].values()))
        self.assertIn('Imperative technical change',shape['properties']['D-1.1.action']['description'])
        self.assertIn('Begin Test, Verify or Check',shape['properties']['D-1.2.action']['description'])
        self.assertIn('verification artifact',shape['properties']['D-1.2.output']['description'])
        self.assertIn('expected observable',shape['properties']['D-1.2.evidence']['description'].casefold())
        ctx=json.loads(body);self.assertEqual(ctx['wire'],d.WIRE)
        self.assertNotIn(ARTIFACT_PM['A'][1][0][0],body)
        self.assertEqual(ctx['targets'][0]['description'],src['document']['requirements'][0]['description'])
        self.assertEqual(ctx['targets'][0]['required_exact_terms'],['save','url'])
        self.assertEqual(meta['prompt_digest'],pp.digest(d.RULES))
        self.assertLessEqual(meta['context_bytes'],d.MAX_CONTEXT_BYTES)
    def test_flat_decoder_rejects_nested_duplicate_and_unauthorized_fields(self):
        ids=['D-1.1'];fields={'D-1.1':['action']};good={'D-1.1.action':'Add a handler for URL storage'}
        self.assertEqual(d.decode(json.dumps(good),ids,fields),{'D-1.1':{'action':good['D-1.1.action']}})
        for raw in ('{"D-1.1.action":"first","D-1.1.action":"second"}',
                    json.dumps({'D-1.1':{'action':good['D-1.1.action']}}),
                    json.dumps(dict(good,**{'D-1.1.output':'Unauthorized output'})),
                    json.dumps({'D-1.1.action':{'value':'bad'}}),
                    json.dumps({'D-1.1.action':''}),json.dumps({'D-1.1.action':'x'*160})):
            with self.subTest(raw=raw),self.assertRaises(ValueError):d.decode(raw,ids,fields)
    def test_historical_failed_repairs_are_still_blocked(self):
        for lane in 'AB':
            with self.subTest(lane=lane):
                src,doc=self.artifact(lane);calls=[]
                def call(phase,system,user,schema):
                    patch=d.flatten(ARTIFACT_14998801172[lane][len(calls)])
                    calls.append(phase)
                    self.assertEqual(set(patch),set(schema['required']))
                    return json.dumps(patch)
                e=d.run(call,src,doc)
                self.assertFalse(e['ready']);self.assertFalse(e['repair_audit_valid'])
                self.assertEqual(len(calls),2);self.assertEqual(len(e['history']),1)
                initial,repaired=e['history'][0]['attempts']
                self.assertEqual(len(initial['issues_after']),10 if lane=='A' else 3)
                self.assertGreaterEqual(len(repaired['issues_after']),11 if lane=='A' else 3)
                self.assertEqual(repaired['convergence']['lost_scope_groups'],[])
                self.assertFalse(repaired['convergence']['passed'])
                self.assertTrue(any(x['code']=='output_role_confusion' for x in repaired['issues_after']))
    def test_duplicate_diagnostics_and_field_specific_instructions(self):
        src,doc=self.artifact('B');ids=d.batches(doc)[0]
        before=d.apply(doc,ARTIFACT_14998801172['B'][0],src)
        issues=d.local_issues(before,src,ids)
        duplicate=next(x for x in issues if x['code']=='duplicate_detail')
        self.assertEqual(duplicate,dict(package='D-1.2',field='output',code='duplicate_detail',
            conflicts_with=dict(package='D-1.1',field='output')))
        fields=d.repair_fields(ids,issues)
        self.assertEqual(fields,{'D-1.1':['action'],'D-1.2':['output'],'D-2.1':['action']})
        body,shape,meta=d.request(src,before,list(fields),issues,fields)
        self.assertEqual(shape['required'],['D-1.1.action','D-1.2.output','D-2.1.action'])
        ctx=json.loads(body);target=next(x for x in ctx['targets'] if x['id']=='D-1.2')
        entry=target['field_contracts']['D-1.2.output']
        self.assertEqual(entry['conflicts_with'],[dict(key='D-1.1.output')])
        self.assertIn('duplicate_detail',entry['fix']);self.assertIn('verification artifact',shape['properties']['D-1.2.output']['description'])
        self.assertIn('action',target['retained_fields'])
        self.assertNotIn('Persisted URL in own project',body)
        self.assertNotIn('used_details',ctx)
    def test_synthetic_exact_field_repairs_preserve_retained_model_text(self):
        for lane in 'AB':
            with self.subTest(lane=lane):
                src,doc=self.artifact(lane);calls=[]
                def call(phase,system,user,schema):
                    calls.append(phase)
                    if len(calls)==1:return json.dumps(d.flatten(ARTIFACT_14998801172[lane][0]))
                    return json.dumps(wire_output(doc,schema))
                e=d.run(call,src,doc)
                self.assertTrue(e['ready'],e['analysis']['issues'])
                self.assertEqual(e['call_count'],3);self.assertEqual(e['max_calls'],4)
                repair=e['history'][0]['attempts'][1]
                self.assertTrue(repair['convergence']['passed'])
                self.assertEqual(repair['convergence']['lost_scope_groups'],[])
                self.assertTrue(repair['convergence']['unchanged_unflagged'])
                self.assertEqual(set(repair['patch']),set(repair['request']['keys']))
                for pid,values in ARTIFACT_14998801172[lane][0].items():
                    for key,value in values.items():
                        if pid+'.'+key not in repair['patch']:
                            self.assertEqual(d.packages(e['candidate'])[pid][key],value)
                self.assertTrue(d.gate(e,src,doc)['ready'])
    def test_role_confusion_and_wire_provenance_tampering(self):
        src,doc=self.artifact('B')
        bad=d.apply(doc,{'D-1.1':dict(action='Test URL persistence using a fresh connection',
            output='Verify URL persistence in storage',evidence='Expected stored URL identifier assertion')},src)
        codes={x['code'] for x in d.local_issues(bad,src,['D-1.1'])}
        self.assertTrue({'implementation_action_required','output_role_confusion'}<=codes)
        e=d.run(synthetic(doc,[]),src,doc);self.assertTrue(e['ready'])
        for change in (lambda x:x.update(wire='legacy'),
                       lambda x:x['history'][0]['attempts'][0]['request'].update(prompt_digest='forged'),
                       lambda x:x['history'][0]['attempts'][0]['request'].update(keys=['D-1.1.action']),
                       lambda x:x['history'][0]['attempts'][0]['patch'].update({'D-99.1.action':'forged'})):
            bad=copy.deepcopy(e);change(bad)
            with self.assertRaises(ValueError):d.gate(bad,src,doc)


# Exact flat patches from artifact 15001222052 (SHA256
# 0eae6d5f900f548b406e288d3718a759e7feb6730ca65b1c73510d4d3d47d7ea).
# Historical output only; never supply these as real provider responses.
ARTIFACT_15001222052={
    'A':[
        {"D-1.1.action":"Validate URL and save it to the user's project","D-1.1.evidence":"URL validation test record","D-1.1.output":"URL validation function","D-1.2.action":"Test saving URL in the user's project","D-1.2.evidence":"Expected URL saving without errors","D-1.2.output":"Save URL integration test","D-2.1.action":"Retrieve and display saved URLs in the user's project","D-2.1.evidence":"URL retrieval test record","D-2.1.output":"URL retrieval function"},
        {"D-2.2.action":"Test list saved links in own project","D-2.2.evidence":"Expected list saved links without errors","D-2.2.output":"List saved links integration test","D-3.1.action":"Implement project isolation to prevent unauthorized access to other projects","D-3.1.evidence":"Project isolation review record","D-3.1.output":"Project isolation implementation record","D-3.2.action":"Test unauthorized cross-project read is denied","D-3.2.evidence":"Expected unauthorized cross-project read denial","D-3.2.output":"Unauthorized cross-project read integration test"},
        {"D-3.1.action":"Implement project isolation guard"}],
    'B':[
        {"D-1.1.action":"Validate file size using the upload handler","D-1.1.evidence":"Oversized file rejection test record","D-1.1.output":"Upload size validation function","D-1.2.action":"Test upload with an oversized file","D-1.2.evidence":"Expected rejection without stored file","D-1.2.output":"Upload boundary integration test","D-2.1.action":"Fetch saved URLs from storage","D-2.1.evidence":"Saved URL retrieval test result","D-2.1.output":"Saved URL retrieval function"},
        {"D-1.1.action":"Validate file size using the upload handler","D-1.2.action":"Test upload with an oversized file"}]}

class ContaminationCompletenessTests(unittest.TestCase):
    def artifact(self,lane):
        # Prior artifact and this artifact have identical PM titles.
        return FlatTechnicalProtocolTests().artifact(lane)
    def first_b(self):
        src,doc=self.artifact('B');ids=d.batches(doc)[0]
        initial=ARTIFACT_15001222052['B'][0]
        candidate=d.apply(doc,d.decode(json.dumps(initial),ids),src)
        issues=d.local_issues(candidate,src,ids);fields=d.repair_fields(ids,issues)
        return src,doc,ids,candidate,issues,fields
    def test_example_free_prompt_and_all_six_field_diagnostics(self):
        src,doc,ids,candidate,issues,fields=self.first_b()
        self.assertEqual(fields,{'D-1.1':list(w.DETAIL_FIELDS),'D-1.2':list(w.DETAIL_FIELDS)})
        flagged=[x for x in issues if x['code']=='example_contamination']
        self.assertEqual({(x['package'],x['field']) for x in flagged},
            {(pid,k) for pid in ('D-1.1','D-1.2') for k in w.DETAIL_FIELDS})
        self.assertEqual(len(issues),8)
        self.assertFalse(w.assess(candidate,src)['detail_ready'])
        body,shape,meta=d.request(src,candidate,list(fields),issues,fields)
        self.assertEqual(shape['required'],[pid+'.'+k for pid in fields for k in fields[pid]])
        self.assertEqual(meta['example_policy'],w.EXAMPLE_POLICY)
        for phrase in w.RETIRED_EXAMPLES:
            self.assertNotIn(phrase.casefold(),(d.RULES+body+json.dumps(shape)).casefold())
        for target in json.loads(body)['targets']:
            self.assertEqual(target['retained_fields'],[])
            for k,entry in target['field_contracts'].items():
                self.assertIn('example_contamination',entry['fix'])
                self.assertEqual(entry['min_words'],w.MIN_DETAIL_WORDS[k.rsplit('.',1)[1]])
                self.assertEqual(entry['max_chars'],159)
    def test_normalized_embedded_example_and_narrow_nonmatch(self):
        for phrase in w.RETIRED_EXAMPLES:
            with self.subTest(phrase=phrase):
                self.assertTrue(w.example_contaminated(phrase.upper()))
                self.assertTrue(w.example_contaminated('Planned: '+phrase.replace(' ','-')+' for review'))
        self.assertFalse(w.example_contaminated('Validate URL using the authenticated project handler'))
        self.assertFalse(w.example_contaminated('Upload a URL import configuration'))
        self.assertFalse(w.example_contaminated(None))
    def test_old_action_only_repair_is_rejected_without_third_call(self):
        src,doc,ids,candidate,issues,fields=self.first_b();calls=[]
        def call(phase,system,user,schema):
            calls.append(phase);return json.dumps(ARTIFACT_15001222052['B'][len(calls)-1])
        e=d.run(call,src,doc)
        self.assertFalse(e['ready']);self.assertEqual(len(calls),2)
        repair=e['history'][0]['attempts'][1]
        self.assertFalse(repair['valid'])
        self.assertEqual(repair['diagnostic']['code'],'detail_target_mismatch')
        self.assertEqual(set(repair['diagnostic']['missing']),{
            'D-1.1.output','D-1.1.evidence','D-1.2.output','D-1.2.evidence'})
        self.assertEqual(e['candidate'],candidate)
    def test_all_six_field_echo_repair_still_fails_noop(self):
        src,doc,ids,candidate,issues,fields=self.first_b();calls=[]
        def call(phase,system,user,schema):
            calls.append(phase)
            return json.dumps({k:ARTIFACT_15001222052['B'][0][k] for k in schema['required']})
        e=d.run(call,src,doc);self.assertFalse(e['ready']);self.assertEqual(len(calls),2)
        repair=e['history'][0]['attempts'][1]
        self.assertTrue(repair['convergence']['no_op'])
        self.assertFalse(repair['convergence']['passed'])
        self.assertEqual(repair['convergence']['after_issues'],8)
    def test_a_short_repair_preserves_full_constraints_and_blocks(self):
        src,doc=self.artifact('A');calls=[]
        def call(phase,system,user,schema):
            calls.append((phase,json.loads(user),schema))
            return json.dumps(ARTIFACT_15001222052['A'][len(calls)-1])
        e=d.run(call,src,doc)
        self.assertFalse(e['ready']);self.assertEqual(len(calls),3)
        self.assertEqual(e['history'][0]['attempts'][0]['issues_after'],[])
        self.assertEqual(calls[2][2]['required'],['D-3.1.action'])
        contract=calls[2][1]['targets'][0]['field_contracts']['D-3.1.action']
        self.assertEqual(contract['min_words'],5);self.assertEqual(contract['target_words'],[8,14])
        self.assertIn('Imperative technical change',calls[2][2]['properties']['D-3.1.action']['description'])
        repair=e['history'][1]['attempts'][1]
        self.assertEqual((repair['convergence']['before_issues'],repair['convergence']['after_issues']),(2,1))
        self.assertEqual(repair['issues_after'],[dict(package='D-3.1',field='action',code='action_lacks_specificity')])
    def test_successful_synthetic_repairs_preserve_every_unflagged_field(self):
        for lane in 'AB':
            with self.subTest(lane=lane):
                src,doc=self.artifact(lane);calls=[]
                def call(phase,system,user,schema):
                    calls.append(phase)
                    if lane=='A' and len(calls)<=2:return json.dumps(ARTIFACT_15001222052['A'][len(calls)-1])
                    if lane=='B' and len(calls)==1:return json.dumps(ARTIFACT_15001222052['B'][0])
                    return json.dumps(wire_output(doc,schema))
                e=d.run(call,src,doc)
                self.assertTrue(e['ready'],e['analysis']['issues'])
                self.assertEqual(e['call_count'],3);self.assertEqual(e['max_calls'],4)
                self.assertEqual(e['example_policy'],w.EXAMPLE_POLICY)
                self.assertFalse(any(w.example_contaminated(v) for v in d.flatten({
                    pid:{k:pkg[k] for k in w.DETAIL_FIELDS} for pid,pkg in d.packages(e['candidate']).items()}).values()))
                repair=e['history'][1 if lane=='A' else 0]['attempts'][1]
                self.assertTrue(repair['convergence']['passed'])
                self.assertTrue(repair['convergence']['unchanged_unflagged'])
                self.assertEqual(repair['convergence']['lost_scope_groups'],[])
                initial=ARTIFACT_15001222052[lane][1 if lane=='A' else 0]
                final=d.flatten({pid:{k:pkg[k] for k in w.DETAIL_FIELDS} for pid,pkg in d.packages(e['candidate']).items()})
                for key,value in initial.items():
                    if key not in repair['patch']:self.assertEqual(final[key],value)
                self.assertTrue(d.gate(e,src,doc)['ready'])
                for change in (lambda x:x.update(example_policy='legacy'),
                    lambda x:x['history'][0]['attempts'][0]['request'].update(example_policy='forged')):
                    bad=copy.deepcopy(e);change(bad)
                    with self.assertRaises(ValueError):d.gate(bad,src,doc)
    def test_incomplete_target_mapping_cannot_leak_contaminated_context(self):
        src,doc,ids,candidate,issues,fields=self.first_b()
        with self.assertRaises(ValueError):d.request(src,candidate,['D-1.1','D-1.2'],issues,
            {'D-1.1':['action'],'D-1.2':['action']})
        with self.assertRaises(ValueError):d.request(src,candidate,['D-2.1'])


# Exact historical v5 flat patches from artifact 15002647325,
# SHA256 71f6f053467d6aee6480960478c4aa554daedf9dd844cdb43c4017b047acbdc6.
# These are regression inputs only, not actual acceptance transport.
ARTIFACT_15002647325={
    'A':[
        {"D-1.1.action":"Save URL in own project","D-1.1.evidence":"Review record","D-1.1.output":"Saved URL record",
         "D-1.2.action":"Test list saved links","D-1.2.evidence":"Test report","D-1.2.output":"Test case",
         "D-2.1.action":"List saved links","D-2.1.evidence":"State check","D-2.1.output":"Listed URLs"},
        {"D-1.1.action":"Write new technical detail; do not repeat the approved requirement, acceptance sentence or source title.",
         "D-1.1.evidence":"Replace the short or generic phrase with a specific subject and method or artifact.",
         "D-1.2.action":"Write 8–14 meaningful words with operation, object and technical method; never fewer than 5.",
         "D-1.2.evidence":"State the expected observable result or assertion tied to the criterion, with subject and condition; 4+ words. Not an executed result.",
         "D-1.2.output":"Name the concrete implementation artifact to produce: component, handler, query, configuration or equivalent; noun phrase, 3+ words, not an action or assertion",
         "D-2.1.action":"Write 8–14 meaningful words with operation, object and technical method; never fewer than 5.",
         "D-2.1.evidence":"State the expected observable result or assertion tied to the criterion, with subject and condition; 4+ words. Not an executed result.",
         "D-2.1.output":"Name the concrete implementation artifact to produce: component, handler, query, configuration or equivalent; noun phrase, 3+ words, not an action or assertion"}],
    'B':[
        {"D-1.1.action":"Test/Verify/Check: Execute query to check saved URL persistence",
         "D-1.1.evidence":"Test/Verify/Check: URL persistence state record",
         "D-1.1.output":"Test/Verify/Check: Review saved URL persistence state",
         "D-1.2.action":"Test/Verify/Check: Execute query to verify saved URL visibility",
         "D-1.2.evidence":"Test/Verify/Check: URL visibility test record",
         "D-1.2.output":"Test/Verify/Check: URL visibility test result",
         "D-2.1.action":"Test/Verify/Check: Execute query to list saved URLs",
         "D-2.1.evidence":"Test/Verify/Check: Saved URLs list test record",
         "D-2.1.output":"Test/Verify/Check: Saved URLs list test result"},
        {"D-1.1.action":"Include save handler in URL persistence logic",
         "D-2.1.action":"Implement URL retrieval function for display"},
        {"D-2.2.action":"Test/Verify/Check: Execute query to verify saved URL visibility",
         "D-2.2.evidence":"Test/Verify/Check: URL visibility test record",
         "D-2.2.output":"Test/Verify/Check: URL visibility test result",
         "D-3.1.action":"Implement URL retrieval function for display",
         "D-3.1.evidence":"Test/Verify/Check: Saved URLs list test record",
         "D-3.1.output":"Test/Verify/Check: Saved URLs list test result",
         "D-3.2.action":"Test/Verify/Check: Execute query to verify saved URL visibility",
         "D-3.2.evidence":"Test/Verify/Check: URL visibility test record",
         "D-3.2.output":"Test/Verify/Check: URL visibility test result"},
        {"D-2.2.action":"Test/Verify/Check: Execute query to verify saved URL visibility",
         "D-2.2.evidence":"Test/Verify/Check: URL persistence state record",
         "D-2.2.output":"Test/Verify/Check: URL visibility test result",
         "D-3.1.action":"Implement URL retrieval function for display",
         "D-3.1.evidence":"Test/Verify/Check: Saved URLs list test record",
         "D-3.1.output":"Test/Verify/Check: Saved URLs list test result",
         "D-3.2.action":"Test/Verify/Check: Execute query to verify saved URL visibility",
         "D-3.2.evidence":"Test/Verify/Check: URL persistence state record",
         "D-3.2.output":"Test/Verify/Check: URL visibility test result"}]}

class IsolatedContextTests(unittest.TestCase):
    def artifact(self,lane):
        return FlatTechnicalProtocolTests().artifact(lane)
    def test_exact_historical_instruction_echo_a_is_blocked(self):
        src,doc=self.artifact('A');calls=[]
        def call(phase,system,user,schema):
            patch=ARTIFACT_15002647325['A'][len(calls)]
            calls.append((phase,user,schema))
            self.assertEqual(set(patch),set(schema['required']))
            return json.dumps(patch)
        e=d.run(call,src,doc)
        self.assertFalse(e['ready']);self.assertEqual(len(calls),2)
        self.assertEqual(len(e['history']),1)
        first,repair=e['history'][0]['attempts']
        self.assertEqual(len(first['issues_after']),11)
        self.assertEqual(len(repair['issues_after']),17)
        self.assertEqual({x['package']+'.'+x['field'] for x in repair['issues_after']
            if x['code']=='instruction_contamination'},set(ARTIFACT_15002647325['A'][1]))
        self.assertFalse(repair['convergence']['passed'])
        self.assertTrue(repair['convergence']['lost_scope_groups'])
        self.assertNotIn('Write new technical detail',calls[1][1])
    def test_exact_b_prefix_expands_all_nine_fields_and_rejects_old_repair(self):
        src,doc=self.artifact('B');calls=[]
        def call(phase,system,user,schema):
            calls.append((phase,user,schema))
            return json.dumps(ARTIFACT_15002647325['B'][len(calls)-1])
        e=d.run(call,src,doc)
        first,repair=e['history'][0]['attempts']
        self.assertEqual(len(first['issues_after']),12)
        self.assertEqual(len([x for x in first['issues_after'] if x['code']=='instruction_contamination']),9)
        self.assertEqual(set(calls[1][2]['required']),set(ARTIFACT_15002647325['B'][0]))
        self.assertFalse(repair['valid']);self.assertEqual(repair['diagnostic']['code'],'detail_target_mismatch')
        self.assertEqual(len(repair['diagnostic']['missing']),7)
        self.assertNotIn('Test/Verify/Check',calls[1][1])
        self.assertFalse(e['ready']);self.assertEqual(len(calls),2)
    def test_cross_batch_duplicate_gate_replays_exact_historical_b(self):
        src,doc=self.artifact('B')
        batches=d.batches(doc);candidate=doc
        for i,flat in enumerate(ARTIFACT_15002647325['B']):
            ids=list(dict.fromkeys(k.rsplit('.',1)[0] for k in flat))
            fields={pid:[k for k in w.DETAIL_FIELDS if pid+'.'+k in flat] for pid in ids}
            candidate=d.apply(candidate,d.decode(json.dumps(flat),ids,fields),src)
            if i>=2:
                issues=d.local_issues(candidate,src,batches[1])
                self.assertEqual(len([x for x in issues if x['code']=='duplicate_detail']),9)
                self.assertEqual(len([x for x in issues if x['code']=='missing_scope_evidence']),3)
                self.assertEqual(len([x for x in issues if x['code']=='instruction_contamination']),8)
                self.assertFalse(w.assess(candidate,src)['detail_ready'])
        # Never feed this contaminated historical first batch into a new call.
        with self.assertRaises(ValueError):d.request(src,candidate,batches[1])
    def test_isolation_retained_coverage_and_compact_diagnostics(self):
        src,doc=self.artifact('B');ids=d.batches(doc)[0]
        initial=d.apply(doc,d.decode(json.dumps(ARTIFACT_15002647325['B'][0]),ids),src)
        issues=d.local_issues(initial,src,ids);fields=d.repair_fields(ids,issues)
        body,shape,meta=d.request(src,initial,ids,issues,fields)
        ctx=json.loads(body)
        self.assertEqual(ctx['protocol'],d.CONTEXT_POLICY)
        self.assertNotIn('used_details',ctx)
        self.assertLess(meta['context_bytes'],3121)  # v5 B repair, only two targets
        for val in ARTIFACT_15002647325['B'][0].values():self.assertNotIn(val,body)
        for target in ctx['targets']:
            self.assertEqual(target['retained_fields'],[])
            self.assertEqual(target['retained_coverage'],[])
            for contract in target['field_contracts'].values():
                self.assertIn('instruction_contamination',contract['fix'])
                self.assertNotIn('instruction',contract)
        # Scope covered by retained fields is counted, without repeating their text.
        good=d.apply(doc,output(doc,ids),src)
        fields={'D-1.1':['action']}
        ctx=d.context(src,good,['D-1.1'],[],fields)
        target=ctx['targets'][0]
        self.assertEqual(target['retained_fields'],['output','evidence'])
        self.assertEqual(target['retained_coverage'],[1])
        self.assertEqual(target['required_exact_terms'],['save'])
        for k in ('output','evidence'):
            self.assertNotIn(d.packages(good)['D-1.1'][k],json.dumps(ctx))
    def test_second_batch_body_independent_of_prior_generated_text(self):
        src,doc=self.artifact('A');first,second=d.batches(doc)
        good=d.apply(doc,output(doc,first),src)
        changed=copy.deepcopy(good)
        d.packages(changed)['D-1.1']['output']='Alternative project URL database handler'
        body,shape,meta=d.request(src,good,second)
        other,other_shape,other_meta=d.request(src,changed,second)
        self.assertEqual((body,shape,meta),(other,other_shape,other_meta))
        self.assertLess(meta['context_bytes'],4733)  # historical v5 second generation
        for pkg in d.packages(good).values():
            for k in w.DETAIL_FIELDS:
                if pkg[k] is not None:self.assertNotIn(pkg[k],body)
        ctx=json.loads(body)
        self.assertEqual([t['id'] for t in ctx['targets']],second)
        self.assertEqual([t['requirement'] for t in ctx['targets']],['REQ-2','REQ-3','REQ-3'])
    def test_synthetic_bounded_repair_and_policy_replay(self):
        for lane in 'AB':
            with self.subTest(lane=lane):
                src,doc=self.artifact(lane);calls=[]
                def call(phase,system,user,schema):
                    calls.append((phase,user,schema))
                    if len(calls)==1:return json.dumps(ARTIFACT_15002647325[lane][0])
                    return json.dumps(wire_output(doc,schema))
                e=d.run(call,src,doc)
                self.assertTrue(e['ready'],e['analysis']['issues'])
                self.assertEqual(e['call_count'],3);self.assertEqual(e['max_calls'],4)
                self.assertTrue(e['history'][0]['attempts'][1]['convergence']['passed'])
                self.assertTrue(d.gate(e,src,doc)['ready'])
                for key in ('instruction_policy','context_policy'):
                    bad=copy.deepcopy(e);bad[key]='legacy'
                    with self.assertRaises(ValueError):d.gate(bad,src,doc)
                    bad=copy.deepcopy(e);bad['history'][0]['attempts'][0]['request'][key]='forged'
                    with self.assertRaises(ValueError):d.gate(bad,src,doc)
    def test_instruction_signatures_are_narrow_normalized_and_field_independent(self):
        for flat in ARTIFACT_15002647325['A'][1],ARTIFACT_15002647325['B'][0]:
            for text in flat.values():
                self.assertTrue(w.instruction_contaminated(text))
                self.assertTrue(w.instruction_contaminated(text.upper().replace(' ','-')))
        for text in ('Test saved URL retrieval in the project list',
                     'Implement a handler to check authorized project membership',
                     'Expected URL compared with returned list',
                     'Add a save handler using the authenticated project identifier'):
            self.assertFalse(w.instruction_contaminated(text))
        self.assertFalse(w.instruction_contaminated(None))
