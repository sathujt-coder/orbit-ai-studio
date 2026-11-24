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
