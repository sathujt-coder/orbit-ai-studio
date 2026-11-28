import copy
import unittest
import test_automated_defect_detection as fixtures
import defect_classification as c

class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DetectionTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
    def failed(self):
        self.f.f.setup_result(False)
        return self.f.detect()
    def classify(self,v):
        return c.classify('p','j',v)
    def resign(self,v):
        v['evidence_digest']=c.pp.digest({k:x for k,x in v.items() if k!='evidence_digest'})
        return v
    def test_functional(self):
        v=self.failed();r=self.classify(v)
        self.assertEqual(r['state'],'CLASSIFIED')
        self.assertEqual(r['items'][0]['domain'],'PRODUCT')
        self.assertEqual(r['items'][0]['severity'],'HIGH')
        self.assertFalse(r['items'][0]['impact_confirmed'])
        self.assertEqual(r['detection_digest'],v['evidence_digest'])
        self.assertEqual(r,self.classify(v))
    def test_execution(self):
        r=self.classify(self.f.nonexecuted('ERROR','DOCKER_UNAVAILABLE'))
        self.assertEqual(r['items'][0]['domain'],'EXECUTION')
    def test_coverage(self):
        r=self.classify(self.f.nonexecuted('NOT_EXECUTED','TOTAL_TIMEOUT'))
        self.assertEqual(r['items'][0]['domain'],'COVERAGE')
    def test_pass(self):
        self.assertEqual(self.classify(self.f.detect())['state'],'NO_FINDINGS')
    def test_stale(self):
        self.f.f.receipt=None
        self.assertEqual(self.classify(self.f.detect())['state'],'BLOCK')
    def test_tamper(self):
        v=self.failed();v['findings'][0]['reason']='TOTAL_TIMEOUT'
        self.assertEqual(self.classify(v)['state'],'BLOCK')
        self.assertEqual(self.classify(self.resign(v))['state'],'BLOCK')
    def test_duplicate(self):
        v=self.failed();v['findings'].append(copy.deepcopy(v['findings'][0]))
        self.assertEqual(self.classify(self.resign(v))['state'],'BLOCK')
    def test_cross_scope(self):
        v=self.failed();v['project_id']='other'
        self.assertEqual(self.classify(self.resign(v))['state'],'BLOCK')
    def test_wrong_receipt(self):
        v=self.failed();v['findings'][0]['receipt_digest']='a'*64
        self.assertEqual(self.classify(self.resign(v))['state'],'BLOCK')
    def test_authority(self):
        v=self.failed();v[next(iter(c.FLAGS))]=True
        self.assertEqual(self.classify(self.resign(v))['state'],'BLOCK')
if __name__=='__main__':unittest.main()
