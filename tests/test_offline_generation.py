import sys,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'backend')]
import coding_factory as cf
import model_provider as mp
import offline_generation as g
class Model:
    def __init__(self,outputs):
        self.outputs=iter(outputs);self.calls=[];self.diagnostics=[]
    def structured(self,s,u,l,schema):
        self.calls.append((l,u,schema))
        r=next(self.outputs)
        if isinstance(r,Exception):raise r
        return r
    def structured_diagnostic(self,l,s,a,c):self.diagnostics.append((l,a,c))
    def proposal_recovery(self,*args):return g.recover(*args)
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.project={'name':'P','platform':'Web app','idea':'Synthetic'}
        self.main=json.dumps({'content':'def add(a,b):\n    return a+b'})
        self.test=json.dumps({'content':'import unittest\nfrom main import add\nclass T(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(add(-1,1),0)'})
    def test_split_after_two_invalid_replies(self):
        m=Model(['not json','{}',self.main,self.test])
        p=cf.generate_proposal(m,self.project,g.BENCHMARK_SPEC,'','A')
        self.assertEqual([f['path'] for f in p['files']],['main.py','test_main.py'])
        self.assertEqual([x[0] for x in m.calls],['A']*4)
        self.assertEqual(len(m.diagnostics),2)
        self.assertEqual(m.calls[2][2],g.FILE_SCHEMA)
        self.assertIn('def add',m.calls[3][1])
    def test_provider_failure_does_not_trigger_recovery(self):
        m=Model([mp.ProviderError('failure')])
        with self.assertRaises(mp.ProviderError):cf.generate_proposal(m,self.project,g.BENCHMARK_SPEC,'','A')
        self.assertEqual(len(m.calls),1)
    def test_unsafe_split_output_blocked(self):
        m=Model(['{}','{}',json.dumps({'content':'import os'}),json.dumps({'content':'import os'})])
        with self.assertRaises(cf.StructuredReplyError):cf.generate_proposal(m,self.project,g.BENCHMARK_SPEC,'','B')
        self.assertEqual(len(m.calls),4)
    def test_split_recovery_only_for_fixed_benchmark(self):
        m=Model(['{}','{}'])
        with self.assertRaises(ValueError):cf.generate_proposal(m,self.project,'Another feature','','B')
        self.assertEqual(len(m.calls),2)
    def test_no_split_on_valid_proposal(self):
        raw=json.dumps({'summary':'s','files':[{'path':'main.py','content':'def add(a,b): return a+b'}]})
        m=Model([raw])
        cf.generate_proposal(m,self.project,g.BENCHMARK_SPEC,'','A')
        self.assertEqual(len(m.calls),1)

    def prior(self,main=None):
        return cf.validate_proposal({'summary':'prior','files':[{'path':'main.py','content':main or 'def add(a,b):\n    return a+b'},
            {'path':'test_main.py','content':json.loads(self.test)['content']}]})
    def test_targeted_repair_only_replaces_invalid_file(self):
        prior=self.prior('def add(a,b):\n    return a +\n')
        m=Model([self.main]);events=[]
        p=g.intelligent_repair(m,self.project,g.BENCHMARK_SPEC,'','B',{'proposal':prior},events)
        self.assertEqual(len(m.calls),1)
        self.assertEqual(cf.source_hashes(p)['test_main.py'],cf.source_hashes(prior)['test_main.py'])
        self.assertEqual(events[0]['target_files'],['main.py'])
        self.assertEqual(events[0]['status'],'changed')
        self.assertIn('PYTHON_SYNTAX',m.calls[0][1])
    def test_unchanged_full_proposal_switches_to_files(self):
        prior=self.prior();events=[]
        changed_main=json.dumps({'content':'def add(a,b):\n    result=a+b\n    return result'})
        changed_test=json.dumps({'content':'import unittest\nfrom main import add\nclass T(unittest.TestCase):\n    def test_zero(self):\n        self.assertEqual(add(0,0),0)'})
        m=Model([json.dumps(prior),changed_main,changed_test])
        p=g.intelligent_repair(m,self.project,g.BENCHMARK_SPEC,'','B',{'proposal':prior},events)
        self.assertTrue(events[0]['stagnation_detected'])
        self.assertEqual(events[0]['strategy'],'stagnation_file_repair')
        self.assertNotEqual(cf.source_hashes(prior),cf.source_hashes(p))
    def test_repeated_file_source_blocks(self):
        prior=self.prior();events=[]
        m=Model([json.dumps(prior),self.main,self.main])
        with self.assertRaises(cf.StructuredReplyError):
            g.intelligent_repair(m,self.project,g.BENCHMARK_SPEC,'','B',{'proposal':prior},events)
        self.assertEqual(events[0]['status'],'blocked')
        self.assertTrue(events[0]['stagnation_detected'])
