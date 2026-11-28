import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import studio_workflow as sw

class StudioWorkflowTests(unittest.TestCase):
    def test_missing_prd_and_unbound_coding(self):
        import sqlite3
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;self.addCleanup(c.close)
        c.executescript("""CREATE TABLE agent_queue(id,project_id,coding_job_id,kind,status,dependency_id,retry_of);
        CREATE TABLE coding_verifications(id,project_id,job_id,verdict,report_json,created_at);
        CREATE TABLE studio_work_packages(project_id,adoption_version,package_id,snapshot,digest,actor,created_at);
        CREATE TABLE studio_coding_bindings(job_id,project_id);
        INSERT INTO agent_queue VALUES('foreign','q','j','coding','succeeded',NULL,NULL);
        INSERT INTO coding_verifications VALUES('foreign','q','j','passed','{}','t');""")
        with patch.object(sw.product_requirements,'view',return_value={'current':None}),patch.object(sw.project_planning,'current_input',return_value=None),patch.object(sw.work_breakdown,'view',return_value={'current':None,'adoption':{'current':None,'status':'blocked','stale':False,'reason':'missing','binding':None}}),patch.object(sw.agent_queue,'view',return_value={'tasks':[]}),patch.object(sw.coding_factory,'list_jobs',return_value=[{'id':'j','status':'ready'}]),patch.object(sw.coding_factory,'detail',return_value={'project_id':'p','manifest':{'mode':'demo'}}):
            result=sw.view(c,'p')
            self.assertEqual(result['next_checkpoint'],'APPROVE_PRD')
            self.assertFalse(result['execution_authorized'])
            self.assertFalse(result['automatic_dispatch'])
            job=result['coding_jobs'][0]
            self.assertEqual(job['planning_binding'],'NOT_RECORDED')
            self.assertIsNone(job['queue'])
            self.assertIsNone(job['verification'])
            self.assertFalse(job['execution_authorized'])
    def test_adopted_bundle_is_not_execution_authority(self):
        prd={'version':2,'digest':'prd','approved_at':'t','approved_by':'owner'}
        adoption={'version':3,'digest':'adopt','bundle_digest':'bundle','review_id':'review','evidence_digest':'evidence'}
        w={'current':{'version':4,'digest':'wbs'},'adoption':{'current':adoption,'status':'adopted','stale':False,'reason':None,'binding':{'bundle_digest':'bundle'}}}
        with patch.object(sw.product_requirements,'view',return_value={'current':prd}),patch.object(sw.project_planning,'current_input',return_value=prd),patch.object(sw.work_breakdown,'view',return_value=w),patch.object(sw.agent_queue,'view',return_value={'tasks':[]}),patch.object(sw.coding_factory,'list_jobs',return_value=[]):
            result=sw.view(None,'p')
            self.assertEqual(result['requirements']['approved']['digest'],'prd')
            self.assertEqual(result['planning']['adoption']['bundle_digest'],'bundle')
            self.assertEqual(result['next_checkpoint'],'WORK_PACKAGE_BINDING_REQUIRED')
            self.assertFalse(result['execution_authorized'])
            w['adoption'].update(status='stale',stale=True)
            self.assertEqual(sw.view(None,'p')['next_checkpoint'],'ADOPT_PLANNING')
