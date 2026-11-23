from pathlib import Path
import hashlib
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import coding_factory
import web_candidate_selection as selection

class CandidateSelectionTests(unittest.TestCase):
    def setUp(self):
        a = coding_factory.validate_proposal({'summary':'A','files':[
            {'path':'src/a.js','content':'export const a = 1;'},
            {'path':'a.test.js','content':'const {test}=require("node:test");test("a",()=>{});'}]})
        b = coding_factory.validate_proposal({'summary':'B','files':[
            {'path':'src/b.js','content':'export const b = 2;'},
            {'path':'b.test.js','content':'const {test}=require("node:test");test("b",()=>{});'}]})
        self.job = {'id':'job123', 'project_id':'project1', 'status':'ready',
                    'proposal_a':a,'proposal_b':b,
                    'review_a':{'reviewer':'A','author':'B','verdict':'APPROVE','score':90},
                    'review_b':{'reviewer':'B','author':'A','verdict':'APPROVE','score':91},
                    'manifest':{'mode':'model','selected':'A','files':[
                        {'path':f['path'],'sha256':f['sha256']} for f in a['files']]}}
        self.report={'job_id':'job123','gate':'PASS','verdict':'passed',
                     'approval':'local_cli_explicit','sandbox':{'runtime':'docker'},
                     'lanes':{}}
        for lane, proposal in (('A',a),('B',b)):
            self.report['lanes'][lane]={'status':'passed','sha256':selection._digest(proposal['files']),
                 'steps':[{'step':'javascript_tests','executed':True,'passed':True,'test_count':2}]}

    def test_both_candidates_compared(self):
        result=selection.compare(self.job,self.report)
        self.assertEqual(set(result['candidates']),{'A','B'})
        self.assertEqual(result['status'],'awaiting_techlead_decision')

    def test_techlead_can_choose_b(self):
        result=selection.decide(self.job,self.report,selected='B',techlead='Human Lead',
          rationale='Candidate B offers a clearer public interface and safer validation.',
          confirmation='SELECT DEV-B job123')
        self.assertEqual(result['selected'],'B')
        self.assertFalse(result['publish_allowed'])
        self.assertFalse(result['production_approved'])

    def test_requires_explicit_confirmation(self):
        with self.assertRaises(PermissionError):
            selection.decide(self.job,self.report,selected='A',techlead='Human Lead',
              rationale='A is preferable due to its simpler API and test coverage.',confirmation='YES')

    def test_failed_b_blocks_all_selection(self):
        self.report['lanes']['B']['status']='failed'
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_missing_lane_blocks(self):
        del self.report['lanes']['B']
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_mismatched_hash_blocks(self):
        self.report['lanes']['B']['sha256']='0'*64
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_zero_tests_blocks(self):
        self.report['lanes']['A']['steps'][0]['test_count']=0
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_nonexecuted_step_blocks(self):
        self.report['lanes']['A']['steps'][0]['executed']=False
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_wrong_job_blocks(self):
        self.report['job_id']='different'
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_demo_job_blocks(self):
        self.job['manifest']['mode']='demo'
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_untrusted_provenance_blocks(self):
        self.report['approval']='demo'
        with self.assertRaises(ValueError):
            selection.compare(self.job,self.report)

    def test_unsupported_selected_lane_blocks(self):
        with self.assertRaises(ValueError):
            selection.decide(self.job,self.report,selected='C',techlead='Human Lead',
              rationale='This is an adequate and reasoned comparison for selection.',
              confirmation='SELECT DEV-C job123')

    def test_weak_rationale_blocks(self):
        with self.assertRaises(ValueError):
            selection.decide(self.job,self.report,selected='A',techlead='Human Lead',
              rationale='Looks fine',confirmation='SELECT DEV-A job123')

if __name__=='__main__':
    unittest.main()
