"""Regression guard for the frozen historical record; not a release authorization engine."""
import json
import unittest
from pathlib import Path

class PlanningReadinessBaseline(unittest.TestCase):
    def test_frozen_p62j_evidence_and_separate_readiness(self):
        root=Path(__file__).resolve().parents[1]
        data=json.loads((root/'docs/planning-readiness-baseline.json').read_text())
        self.assertEqual(data['baseline_head'],'f68a9292ab0561fa4687c0d6e786df0e82c87a2d')
        self.assertEqual(data['baseline_merge'],'8051c702aa6dd57d9a45221613e8cfba00aa069c')
        self.assertEqual(data['system']['status'],'PASS')
        self.assertEqual(data['system']['transport'],'isolated_synthetic_fixture')
        self.assertEqual((data['system']['python_passed'],data['system']['python_total']),(394,394))
        self.assertEqual((data['system']['chromium_passed'],data['system']['chromium_total']),(19,19))
        self.assertEqual(data['system']['artifact_id'],15020564581)
        self.assertEqual(data['model']['offline_artifact_id'],15023621149)
        self.assertEqual(data['model']['benchmark_artifact_id'],15024177161)
        for key in ('status','real_ai_acceptance','qualification'):
            self.assertEqual(data['model'][key],'BLOCK')
        self.assertEqual(data['model']['qualified_models'],[])
        self.assertEqual(data['model']['cross_review'],'NOT_REACHED')
        self.assertEqual(data['model']['adoption'],'NOT_REACHED')
        self.assertEqual(data['production'],dict(status='BLOCK',release_authorized=False))
        self.assertEqual(data['development'],dict(next_phase='P6.3',allowed=True,scope='development_only',
            automatic_adoption=False,execution_authorized=False,merge_authorized=False))
