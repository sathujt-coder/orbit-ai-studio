"""P6.2d.10: system acceptance, synthetic transport only.

Real engine, SQLite storage, queue, usage ledger and replay; no network or
model capability claims. Browser acceptance separately exercises HTTP/RBAC.
"""
import json
import unittest
from dataclasses import replace
import test_wbs_decomposition as fixtures
import agent_queue as q
import decomposition_jobs as dj
import wbs_decomposition as d
import work_breakdown as w
import project_planning as pp
import model_provider as mp

class PlanningSystemAcceptance(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.DurableDecompositionTests()
        self.h.setUp()
        self.addCleanup(self.h.tearDown)
        self.c=self.h.c
        self.lanes=self.h.lanes

    def state(self, identifier):
        return q.get(self.c,'p',identifier)

    def unchanged(self):
        self.assertEqual(w.latest(self.c,'p')['digest'],self.h.base['digest'])
        self.assertIsNone(pp.latest(self.c,'p'))
        self.assertIsNone(dj.latest(self.c,'q'))
        self.assertEqual(list(self.c.execute('PRAGMA foreign_key_check')),[])

    def finish(self,identifier,row,snap,transport,model):
        evidence=d.run(transport,snap['source'],snap['document'])
        self.h.ledger(identifier,evidence,model)
        result=dj.persist(self.c,'p',identifier,evidence,model,'t')
        q.boundary(self.c,row,result,9999999999,'t')
        return evidence

    def test_success_requires_human_review_and_never_adopts(self):
        identifier,row,snap=self.h.claimed()
        record=[]
        self.finish(identifier,row,snap,fixtures.synthetic(snap['document'],record),self.lanes['A'])
        state=dj.latest(self.c,'p')
        self.assertTrue(state['ready'])
        self.assertEqual(state['workflow']['next_action'],'human_review')
        self.assertEqual(state['workflow']['model_qualification'],'not_assessed')
        self.assertFalse(state['workflow']['automatic_adoption'])
        self.assertEqual(len(record),2)
        self.unchanged()

    def test_quality_block_stops_dependency_and_explicit_model_replacement(self):
        identifier,row,snap=self.h.claimed()
        dependent=q.enqueue(self.c,'p','pipeline','owner',0,self.lanes,mode='next',
                            dependency_id=identifier)
        calls=[]
        def broken(*args):
            calls.append(args[0])
            return '{}'
        self.finish(identifier,row,snap,broken,self.lanes['A'])
        self.assertEqual(calls,['wbs_decompose','wbs_decompose_repair'])
        failed=dj.latest(self.c,'p')
        self.assertFalse(failed['ready'])
        self.assertEqual(self.state(identifier)['reason'],'quality_gate')
        self.assertEqual(failed['workflow']['next_action'],'operator_review')
        self.assertTrue(failed['workflow']['operator_retry_available'])
        self.assertFalse(failed['workflow']['automatic_fallback'])
        self.assertIsNone(q.claim(self.c,9999999999,'t'))
        self.assertEqual(self.state(dependent)['reason'],'dependency_failed')
        self.unchanged()
        # Operator explicitly submits another job using new configured local model.
        new_lanes=dict(self.lanes,A=replace(self.lanes['A'],model='replacement-fixture'))
        retry=dj.enqueue(self.c,'p','owner',1,new_lanes,self.h.body,retry_of=identifier)
        self.assertNotEqual(retry,identifier)
        claimed=q.claim(self.c,9999999999,'t')
        self.assertEqual(claimed['id'],retry)
        self.assertEqual(claimed['retry_of'],identifier)
        self.assertEqual(claimed['provider_revision'],1)
        self.assertNotEqual(claimed['provider_fingerprint'],row['provider_fingerprint'])
        same=dj.checked_input(self.c,'p',retry)
        self.assertEqual(same,snap)
        self.finish(retry,claimed,same,fixtures.synthetic(same['document'],[]),new_lanes['A'])
        self.assertEqual(dj.latest(self.c,'p')['model']['model'],'replacement-fixture')
        self.assertTrue(dj.latest(self.c,'p')['ready'])
        self.assertEqual(self.state(identifier)['status'],'dead')
        self.assertEqual(self.state(dependent)['status'],'dead')
        self.unchanged()

    def test_bounded_repair_recovers_without_unapproved_fallback(self):
        identifier,row,snap=self.h.claimed()
        record=[]
        evidence=self.finish(identifier,row,snap,fixtures.synthetic(snap['document'],record,True),self.lanes['A'])
        self.assertTrue(evidence['ready'])
        self.assertEqual(len(record),3)
        self.assertTrue(dj.latest(self.c,'p')['ready'])
        self.assertEqual(dj.latest(self.c,'p')['model']['model'],self.lanes['A'].model)
        self.unchanged()

    def test_provider_refusal_is_not_format_repair_or_automatic_fallback(self):
        identifier,row,snap=self.h.claimed()
        calls=[]
        def unavailable(*args):
            calls.append(args[0])
            raise mp.ProviderError('synthetic provider outage')
        with self.assertRaises(mp.ProviderError):
            d.run(unavailable,snap['source'],snap['document'])
        # Exercise the queue's same terminal failure transition as dispatch_one.
        q.fail(self.c,row,'execution_failed',9999999999,'t')
        self.assertEqual(calls,['wbs_decompose'])
        self.assertIsNone(q.claim(self.c,9999999999,'t'))
        state=dj.latest(self.c,'p')
        self.assertFalse(state['ready'])
        self.assertIsNone(state['evidence'])
        self.assertEqual(state['workflow']['next_action'],'operator_review')
        self.unchanged()

    def test_stale_source_disallows_retry_and_requires_new_draft(self):
        identifier,row,snap=self.h.claimed()
        self.finish(identifier,row,snap,lambda *args:'{}',self.lanes['A'])
        self.h.helper.seed(v=1)
        state=dj.latest(self.c,'p')
        self.assertTrue(state['stale'])
        self.assertFalse(state['ready'])
        self.assertEqual(state['workflow']['next_action'],'refresh_source')
        self.assertFalse(state['workflow']['operator_retry_available'])
        current=w.view(self.c,'p')['current']
        with self.assertRaises(ValueError):
            dj.enqueue(self.c,'p','owner',0,self.lanes,dict(wbs_version=current['version'],
                wbs_digest=current['digest'],confirmation='RUN AI DECOMPOSITION'),retry_of=identifier)

    def test_unverified_usage_and_remote_fallback_fail_closed(self):
        identifier,row,snap=self.h.claimed()
        evidence=d.run(fixtures.synthetic(snap['document'],[]),snap['source'],snap['document'])
        result=dj.persist(self.c,'p',identifier,evidence,self.lanes['A'],'t')
        q.boundary(self.c,row,result,9999999999,'t')
        self.assertFalse(dj.latest(self.c,'p')['ready'])
        self.assertEqual(dj.latest(self.c,'p')['workflow']['next_action'],'operator_review')
        remote=dict(self.lanes,A=replace(self.lanes['A'],base_url='https://example.com/v1'))
        with self.assertRaises(ValueError):
            dj.enqueue(self.c,'p','owner',1,remote,self.h.body,retry_of=identifier)
        with self.assertRaises(PermissionError):
            dj.enqueue(self.c,'p','viewer',0,self.lanes,self.h.body,retry_of=identifier)
        self.unchanged()

if __name__=='__main__':
    unittest.main()
