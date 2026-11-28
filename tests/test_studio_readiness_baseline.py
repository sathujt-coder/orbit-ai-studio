"""Frozen historical evidence guard, never release authorization."""
import json
import unittest
from pathlib import Path

class StudioReadinessBaseline(unittest.TestCase):
    def test_frozen_system_evidence(self):
        root=Path(__file__).resolve().parents[1]
        data=json.loads((root/'docs/studio-readiness-baseline.json').read_text())
        self.assertEqual(data['schema'],'orbit.studio-readiness-baseline.v1')
        self.assertEqual(data['baseline_head'],'00e502934e8f98cbc92383b7a225b99df408035c')
        self.assertEqual(data['baseline_merge'],'d91ce77d09e74831e5b25554c6ce9eb5caebb5fb')
        system=data['system']
        self.assertEqual((system['status'],system['run_id'],system['artifact_id']),('PASS',45738996567,15080780154))
        self.assertEqual(system['transport'],'isolated_synthetic_inference_and_sandbox_fixture')
        for key,count in [('python',416),('general_browser_js',22),('planning_chromium',3),('jobs',11)]:
            self.assertEqual(system[key],dict(passed=count,total=count))
        self.assertEqual(set(data['coverage']),{'legacy_handoff','adopted_work_package_binding','coding_queue_submission','sqlite_trigger_rollback','qa_receipt_ui','stale_verification_rejection','http_rbac_csrf','recovery_function'})
        self.assertEqual(set(data['coverage'].values()),{'PASS'})

    def test_development_is_not_release_authority(self):
        root=Path(__file__).resolve().parents[1]
        data=json.loads((root/'docs/studio-readiness-baseline.json').read_text())
        self.assertEqual(data['production'],dict(status='BLOCK',release_authorized=False))
        self.assertEqual(data['development'],dict(next_phase='P6.3',requires_current_sg7_ci_pass=True,scope='development_only',automatic_adoption=False,automatic_dispatch=False,execution_authorized=False,merge_authorized=False))
        for key in ('real_ai_acceptance','qualification'):
            self.assertEqual(data['model'][key],'NOT_ASSESSED')
        self.assertTrue(data['model']['prior_planning_production_block'])
        self.assertEqual(data['limitations'],dict(real_bound_workflow_docker='NOT_ASSESSED',full_http_server_restart='NOT_ASSESSED',criterion_semantic_correctness='NOT_ASSESSED',dependent_package_execution='BLOCK',bound_job_retry='BLOCK',mobile_project_switch='NOT_ASSESSED'))
