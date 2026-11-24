"""Tests of bounded formatting recovery; no actual model inference."""
import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import coding_factory as cf
import model_provider as mp
class Fake:
    def __init__(self,outputs):self.outputs=iter(outputs);self.calls=[]
    def structured(self,s,u,l,schema):
        self.calls.append((l,u,schema))
        result=next(self.outputs)
        if isinstance(result,Exception):raise result
        return result
    def __call__(self,*args):raise AssertionError('Expected structured route')
class StructuredTests(unittest.TestCase):
    def setUp(self):
        self.project={'name':'P','platform':'Web app','idea':'Test'}
        self.valid=json.dumps({'summary':'s','files':[{'path':'main.py','content':'def add(a,b): return a+b'}]})
        self.proposal=cf.validate_proposal(self.valid)
    def test_retry_invalid_proposal_then_valid(self):
        f=Fake(['not JSON',self.valid])
        self.assertEqual(cf.generate_proposal(f,self.project,'test feature','','A'),self.proposal)
        self.assertEqual([x[0] for x in f.calls],['A','A'])
        self.assertEqual(f.calls[0][2],cf.PROPOSAL_SCHEMA)
    def test_retry_limit(self):
        f=Fake(['{}','{}'])
        with self.assertRaises(cf.StructuredReplyError):cf.generate_proposal(f,self.project,'test feature','','A')
        self.assertEqual(len(f.calls),2)
    def test_provider_failure_not_retried(self):
        f=Fake([mp.ProviderError('connection failed')])
        with self.assertRaises(mp.ProviderError):cf.generate_proposal(f,self.project,'test feature','','A')
        self.assertEqual(len(f.calls),1)
    def test_truncation_retry(self):
        f=Fake([mp.OutputError('incomplete'),self.valid])
        self.assertEqual(cf.generate_proposal(f,self.project,'test feature','','A'),self.proposal)
    def test_negative_review_not_retried(self):
        f=Fake(['{"verdict":"APPROVE","score":79,"feedback":"missing test"}'])
        r=cf.review_proposal(f,self.project,'test',self.proposal,'B','A')
        self.assertEqual(r['verdict'],'REQUEST_CHANGES')
        self.assertEqual(len(f.calls),1)
        self.assertEqual(f.calls[0][2],cf.REVIEW_SCHEMA)
    def test_invalid_review_then_valid(self):
        f=Fake(['{"verdict":"APPROVE","score":"100","feedback":"bad"}','{"verdict":"REQUEST_CHANGES","score":60,"feedback":"No tests"}'])
        r=cf.review_proposal(f,self.project,'test',self.proposal,'A','B')
        self.assertEqual((r['verdict'],r['score'],r['author']),('REQUEST_CHANGES',60,'B'))
        self.assertEqual(len(f.calls),2)
