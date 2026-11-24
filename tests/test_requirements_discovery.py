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

class CollaborationTests(unittest.TestCase):
    def fixture(self,blocking=False):
        calls=[]
        def call(lane,phase,system,user,schema):
            data=json.loads(user)
            calls.append((lane,phase,data))
            if schema is discovery.RESEARCH_SCHEMA:
                return json.dumps(dict(audience=['Readers'],needs=['Save links'],hypotheses=[],unknowns=[]))
            if schema is discovery.BA_SCHEMA:
                return json.dumps(dict(workflows=['Save and list'],business_rules=['Project access'],edge_cases=['Denied read'],unknowns=[]))
            if schema in (discovery.REVIEW_SCHEMA,discovery.BRIEF_REVIEW_SCHEMA):
                return json.dumps(dict(blocking=['Unresolved access'] if blocking and phase=='requirements_final_review' else [],feedback=['Review fixture']))
            return json.dumps(document())
        return call,calls
    def test_department_order_and_independence(self):
        call,calls=self.fixture()
        result=discovery.collaborate(call,'Save links')
        self.assertEqual(len(calls),14)
        for offset,department in ((0,'research'),(4,'ba')):
            self.assertEqual([(x[0],x[1]) for x in calls[offset:offset+4]],
                [('A',department+'_proposal'),('B',department+'_proposal'),('A',department+'_cross_review'),('B',department+'_cross_review')])
            self.assertEqual(calls[offset][2],calls[offset+1][2])
            self.assertIn('candidate',calls[offset+2][2])
            self.assertNotIn('candidate',calls[offset][2])
        self.assertEqual(calls[4][2]['research'],result['collaboration']['research'])
        self.assertEqual(calls[8][2],calls[9][2])
        self.assertEqual(calls[8][2]['department_handoffs'],result['collaboration'])
        self.assertEqual(calls[-1][2]['department_handoffs'],result['collaboration'])
        self.assertTrue(result['ready_for_human_review'])
    def test_review_gate_and_invalid_handoff(self):
        call,_=self.fixture(True)
        self.assertFalse(discovery.collaborate(call,'Save links')['ready_for_human_review'])
        with self.assertRaises(ValueError):
            discovery.collaborate(lambda *args:'{}','Save links')
        with self.assertRaises(ValueError):
            discovery.parse_brief(json.dumps(dict(audience=['x'*241],needs=['x'],hypotheses=[],unknowns=[])),discovery.RESEARCH_SCHEMA)

class RepairTests(unittest.TestCase):
    def test_missing_nonfunctional_is_repaired_once(self):
        calls=[]
        def call(lane,phase,system,user,schema):
            calls.append((lane,phase,json.loads(user)))
            if schema is discovery.REVIEW_SCHEMA:
                return json.dumps(dict(blocking=[],feedback=['Review fixture']))
            d=document()
            if lane=='A' and phase=='requirements_proposal':
                d['requirements'][1]['kind']='functional'
            return json.dumps(d)
        result=discovery.discover(call,'Save links')
        self.assertTrue(result['ready_for_human_review'])
        self.assertEqual(len(calls),7)
        self.assertEqual(calls[1][:2],('A','requirements_proposal_repair'))
        self.assertIn('Both functional and nonfunctional',calls[1][2]['validation_error'])
    def test_invalid_repair_fails_closed_and_no_provider_retry(self):
        calls=[]
        def invalid(*args):
            calls.append(args);return '{}'
        with self.assertRaises(discovery.InvalidDocument):discovery.discover(invalid,'Save links')
        self.assertEqual(len(calls),2)
        calls.clear()
        def unavailable(*args):
            calls.append(args);raise discovery.mp.ProviderError('offline')
        with self.assertRaises(discovery.mp.ProviderError):discovery.discover(unavailable,'Save links')
        self.assertEqual(len(calls),1)
