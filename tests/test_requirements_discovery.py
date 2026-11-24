import json
import unittest
from test_product_requirements import document
import requirements_discovery as discovery

class DiscoveryTests(unittest.TestCase):
    def test_independent_and_cross_review(self):
        calls=[]
        def call(lane,phase,system,user,schema):
            data=json.loads(user);calls.append((lane,phase,data))
            if schema is discovery.REVIEW_SCHEMA:
                return json.dumps(dict(blocking=[],feedback=['Review fixture']))
            return json.dumps(document())
        result=discovery.discover(call,'Save links')
        self.assertEqual([(a,b) for a,b,_ in calls],[('A','requirements_proposal'),('B','requirements_proposal'),('A','requirements_cross_review'),('B','requirements_cross_review'),('A','requirements_synthesis'),('B','requirements_final_review')])
        self.assertEqual(calls[0][2],calls[1][2])
        self.assertEqual(set(calls[2][2]),{'idea','candidate'})
        self.assertTrue(result['ready_for_human_review'])
    def test_reject_invalid_candidate(self):
        with self.assertRaises(ValueError):
            discovery.discover(lambda *args:'{}','Save links')
    def test_final_review_blocks(self):
        def call(lane,phase,system,user,schema):
            if schema is discovery.REVIEW_SCHEMA:
                return json.dumps(dict(blocking=['Missing isolation'] if phase=='requirements_final_review' else [],feedback=['Review fixture']))
            return json.dumps(document())
        self.assertFalse(discovery.discover(call,'Save links')['ready_for_human_review'])
    def test_open_questions_block(self):
        def call(lane,phase,system,user,schema):
            if schema is discovery.REVIEW_SCHEMA:return json.dumps(dict(blocking=[],feedback=['Review fixture']))
            d=document();d['open_questions']=['Unresolved']
            return json.dumps(d)
        self.assertFalse(discovery.discover(call,'Save links')['ready_for_human_review'])
