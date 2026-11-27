import copy
import unittest
import test_regression_quality_gate as fixtures
import automated_defect_detection as d
import regression_quality_gate as g

class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.RegressionGateTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def detect(self):
        f = self.f
        return d.evaluate('p','j',f.r,f.src,f.cases,f.targets,f.evaluate())

    def test_pass(self):
        self.assertEqual(self.detect()['state'],'NO_FINDINGS')

    def test_mismatch_and_repeat(self):
        self.f.setup_result(False)
        result = self.detect()
        self.assertEqual(result['state'],'DETECTED')
        self.assertEqual(result['findings'][0]['kind'],'ASSERTION_MISMATCH')
        self.assertEqual(result,self.detect())

    def test_tampered_receipt(self):
        self.f.run['digest']='bad'
        self.assertEqual(self.detect()['state'],'BLOCK')

    def test_stale_source(self):
        self.f.src=copy.deepcopy(self.f.src)
        self.f.src['git']['commit']='new'
        self.assertEqual(self.detect()['state'],'BLOCK')

    def test_cross_project(self):
        self.f.r['project_id']='other'
        self.assertEqual(self.detect()['state'],'BLOCK')

    def test_missing_priority(self):
        self.f.receipt=None
        self.assertEqual(self.detect()['state'],'BLOCK')

    def test_false_pass(self):
        self.f.setup_result(False)
        self.f.report['results'][0]['status']='PASS'
        self.assertEqual(self.detect()['state'],'BLOCK')

    def test_authorization(self):
        key=next(iter(d.FLAGS))
        self.f.r[key]=True
        self.assertEqual(self.detect()['state'],'BLOCK')

if __name__=='__main__':
    unittest.main()
