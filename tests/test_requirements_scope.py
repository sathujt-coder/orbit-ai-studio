import copy
import json
import unittest
from test_product_requirements import document
from test_requirements_discovery import model_document
import requirements_scope as sc
import requirements_discovery as discovery

IDEA='Save and list links in isolated projects. Existing membership is provided.'
CONTRACT=dict(rules=[
    dict(id='SC-1',kind='functional',required=True,evidence='Save and list links',matches=[['save'],['link','links']]),
    dict(id='SC-2',kind='nonfunctional',required=True,evidence='isolated projects',matches=[['project'],['isolation','cannot']])],
    forbidden=['registration','manage projects'],nonblocking_questions=['How many users?'])

class ScopeContractTests(unittest.TestCase):
    def test_exact_evidence_and_contract_shape(self):
        c=sc.validate(IDEA,CONTRACT)
        self.assertTrue(sc.assess(document(),c)['passed'])
        for edit in (lambda x:x['rules'][0].update(evidence='Not in source'),
                     lambda x:x['rules'][1].update(id='SC-1'),
                     lambda x:x['rules'][1].update(required=False),
                     lambda x:x['rules'][0].update(matches=[['!!!']])):
            x=copy.deepcopy(CONTRACT);edit(x)
            with self.assertRaises(ValueError):sc.validate(IDEA,x)
        with self.assertRaises(ValueError):sc.validate(IDEA,None)

    def test_false_approval_targeted_repair_and_fresh_review(self):
        calls=[]
        def call(lane,phase,system,user,schema):
            calls.append((lane,phase,json.loads(user)))
            if schema is discovery.REVIEW_SCHEMA:
                return json.dumps(dict(blocking=[],feedback=['Looks fine']))
            raw=model_document()
            if phase=='requirements_synthesis':
                extra=copy.deepcopy(raw['functional'][0])
                extra['description']='User registration'
                extra['acceptance']=['Users register']
                extra['story']['goal']='Register account'
                raw['functional'].append(extra)
                raw['open_questions']=['How many users?']
            return json.dumps(raw)
        e=discovery.discover(call,IDEA,scope_contract=CONTRACT)
        self.assertTrue(e['false_approval_detected'])
        self.assertTrue(e['scope_recheck'])
        self.assertEqual(calls[-1][:2],('B','requirements_scope_recheck'))
        self.assertEqual(e['scope_repair']['removed_requirement_ids'],['REQ-2'])
        self.assertEqual(e['scope_repair']['deferred_questions'],['How many users?'])
        self.assertEqual(e['initial_final_review']['document']['open_questions'],['How many users?'])
        self.assertEqual(len(e['document']['requirements']),2)
        self.assertTrue(e['scope_findings']['passed'])
        self.assertTrue(e['ready_for_human_review'])

    def test_no_op_and_missing_required_scope_fail_closed(self):
        calls=[]
        def call(lane,phase,system,user,schema):
            calls.append(phase)
            if schema is discovery.REVIEW_SCHEMA:
                return json.dumps(dict(blocking=[],feedback=['Looks fine']))
            raw=model_document()
            raw['functional'][0]['description']='Registration'
            raw['functional'][0]['acceptance']=['Register account']
            raw['open_questions']=['Which provider is authorized?']
            return json.dumps(raw)
        e=discovery.discover(call,IDEA,scope_contract=CONTRACT)
        self.assertEqual(calls.count('requirements_quality_revision'),1)
        self.assertTrue(e['no_op_repair'])
        self.assertTrue(e['false_approval_detected'])
        self.assertFalse(e['scope_findings']['passed'])
        self.assertFalse(e['ready_for_human_review'])
        self.assertEqual(e['document']['open_questions'],['Which provider is authorized?'])
        self.assertFalse(e['scope_repair']['changed'])

    def test_unknown_question_and_story_scope_checked(self):
        d=document()
        d['open_questions']=['Unresolved authorization']
        d['stories'][0]['goal']='Manage projects'
        c=sc.validate(IDEA,CONTRACT)
        candidate,repair=sc.targeted_repair(d,c)
        self.assertFalse(repair['changed'])
        self.assertFalse(repair['after']['passed'])
        self.assertEqual(candidate['open_questions'],d['open_questions'])
        self.assertTrue(any(i['code']=='forbidden_requirement' for i in repair['before']['issues']))

    def test_forbidden_metadata_not_silently_removed(self):
        d=document();d['scope'].append('Registration')
        c=sc.validate(IDEA,CONTRACT)
        candidate,repair=sc.targeted_repair(d,c)
        self.assertEqual(candidate,d)
        self.assertFalse(repair['after']['passed'])
        self.assertTrue(any(i['code']=='forbidden_metadata' for i in repair['after']['issues']))

class ConvergenceTests(unittest.TestCase):
    def contract(self):
        return sc.validate(IDEA,dict(CONTRACT,
            deferred_metric_subjects=['projects per user','users'],
            problem_source='Save and list links'))

    def test_metric_policy_is_opt_in_and_never_defers_decisions(self):
        plain=sc.validate(IDEA,CONTRACT)
        c=self.contract()
        q='What is the average number of projects per user?'
        self.assertEqual(sc.classify_question(q,plain),'unresolved_decision')
        self.assertEqual(sc.classify_question(q,c),'descriptive_metric')
        self.assertEqual(sc.classify_question('How many users?',c),'explicitly_deferred')
        for q in ('What is the maximum number of projects per user?',
                  'How many projects per user are allowed?',
                  'How many projects per user may access private links?',
                  'What is the average number of organizations per user?',
                  'Which provider is authorized?'):
            self.assertEqual(sc.classify_question(q,c),'unresolved_decision')
        with self.assertRaises(ValueError):
            sc.validate(IDEA,dict(CONTRACT,deferred_metric_subjects=['maximum users']))
        with self.assertRaises(ValueError):
            sc.validate(IDEA,dict(CONTRACT,problem_source='Not in source'))
        d=document();d['open_questions']=['What is the average number of projects per user?']
        audit=sc.assess(d,c)
        self.assertFalse(audit['passed'])
        self.assertEqual(sc.hard_issues(audit),[])
        self.assertTrue(sc.targeted_repair(d,c)[1]['after']['passed'])

    def test_renumber_and_order_do_not_count_as_semantic_repair(self):
        before=document();before['open_questions']=['Which provider is authorized?']
        after=copy.deepcopy(before)
        for i,r in enumerate(after['requirements']):
            r['id']='REQ-'+str(90+i)
        after['stories'][0]['id']='US-92'
        after['stories'][0]['requirements']=['REQ-91','REQ-90']
        after['requirements'].reverse()
        self.assertEqual(sc.semantic_digest(before),sc.semantic_digest(after))
        progress=sc.convergence(before,after,self.contract(),dict(blocking=['Unknown']),dict(blocking=[]))
        self.assertTrue(progress['no_op'])
        self.assertFalse(progress['passed'])
        after['problem']='Different description'
        progress=sc.convergence(before,after,self.contract(),dict(blocking=[]),dict(blocking=[]))
        self.assertFalse(progress['no_op'])
        self.assertFalse(progress['passed'])

    def test_recover_save_action_from_existing_draft_not_fabrication(self):
        c=self.contract()
        draft=discovery.parse_document(json.dumps(model_document()))
        bad=copy.deepcopy(draft)
        bad['problem']="The candidate's proposal does not provide a clear definition of a project."
        bad['goals']=['Define a clear definition of a project']
        bad['scope']=['Define a clear definition of a project']
        bad['requirements'][0]['description']='A saved link appears in the list'
        bad['requirements'][0]['acceptance']=['A saved link appears in the list']
        bad['open_questions']=['What is the average number of projects per user?']
        audit=sc.assess(bad,c)
        self.assertIn('REQ-1',audit['unsupported'])
        repaired,repair=sc.targeted_repair(bad,c,alternatives={'B':draft})
        self.assertTrue(repair['changed'])
        self.assertTrue(repair['after']['passed'])
        self.assertEqual(repaired['problem'],c['problem_source'])
        self.assertEqual(set(repair['metadata_replaced']),{'goals','scope'})
        self.assertEqual(repair['restored_requirements'][0]['source_lane'],'B')
        self.assertEqual(repair['restored_requirements'][0]['source_requirement_id'],'REQ-1')
        self.assertTrue(any(r['description']==draft['requirements'][0]['description'] for r in repaired['requirements']))
        self.assertEqual(repaired['open_questions'],[])
        self.assertTrue(sc.convergence(bad,repaired,c,dict(blocking=[]),dict(blocking=[]))['passed'])
        self.assertFalse(sc.targeted_repair(bad,c)[1]['after']['passed'])

    def test_final_false_approval_and_preserved_unresolved_question(self):
        calls=[]
        def call(lane,phase,system,user,schema):
            calls.append(phase)
            if schema is discovery.REVIEW_SCHEMA:
                return json.dumps(dict(blocking=['Resolve authorization'] if phase=='requirements_final_review' else [],feedback=['Fixture']))
            raw=model_document()
            if phase=='requirements_synthesis':
                raw['open_questions']=['Which provider is authorized?']
            if phase=='requirements_quality_revision':
                # Renumbering/reordering is not meaningful. Deleting the question
                # cannot create a passing document either.
                raw['open_questions']=[]
            return json.dumps(raw)
        e=discovery.discover(call,IDEA,scope_contract=self.contract())
        self.assertEqual([r['phase'] for r in e['review_audit']],
            ['requirements_cross_review','requirements_cross_review','requirements_final_review','requirements_quality_recheck'])
        self.assertFalse(e['review_audit'][-2]['false_approval'])
        self.assertTrue(e['review_audit'][-1]['false_approval'])
        self.assertTrue(e['false_approval_detected'])
        self.assertEqual(e['document']['open_questions'],['Which provider is authorized?'])
        self.assertEqual(e['quality_revision']['preserved_questions'],['Which provider is authorized?'])
        self.assertTrue(e['no_op_repair'])
        self.assertFalse(e['convergence']['passed'])
        self.assertFalse(e['ready_for_human_review'])

    def test_new_defect_and_lost_required_scope_are_not_convergence(self):
        c=self.contract();before=document()
        before['open_questions']=['Which provider is authorized?','Who approves?']
        after=copy.deepcopy(before)
        after['open_questions']=[]
        after['requirements'][0]['description']='A saved link appears'
        after['requirements'][0]['acceptance']=['A saved link appears']
        p=sc.convergence(before,after,c,dict(blocking=[]),dict(blocking=[]))
        self.assertFalse(p['passed'])
        self.assertIn('SC-1',p['lost_required_scope'])
        self.assertTrue(p['new_issues'])

    def test_convergence_rejects_silent_deletion_even_if_otherwise_clean(self):
        before=document();before['open_questions']=['Which provider is authorized?']
        after=copy.deepcopy(before);after['open_questions']=[]
        p=sc.convergence(before,after,self.contract(),dict(blocking=[]),dict(blocking=[]))
        self.assertFalse(p['passed'])
        self.assertEqual(p['unresolved_questions_removed'],before['open_questions'])
