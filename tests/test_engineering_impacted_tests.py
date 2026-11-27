import hashlib,sys,unittest,copy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_impacted_tests as m

def graph(files):
    return m.di.graph(dict(files=[dict(path=k,content=v,sha256=hashlib.sha256(v.encode()).hexdigest()) for k,v in files.items()]))
def comp(a,b):
    old=m.di.index(a);new=m.di.index(b);x=m.di.changes.expected_changes(old,new)
    return m.di.impact(a,b,dict(from_commit='a',to_commit='b',changes=x,
        counts={s:sum(v['status']==s for v in x) for s in ('ADDED','MODIFIED','DELETED')},
        unchanged_count=sum(old.get(p)==new[p] for p in new if p in old)))
def case(i,module):
    return dict(id=i,criterion_id='AC',kind='POSITIVE',execution=dict(runtime='python',module=module,function='f',arguments=[],assertion=dict(operator='equals',value=1)))
class MappingTests(unittest.TestCase):
    def setUp(self):
        self.a=graph({'core.py':'x=1','service.py':'import core','other.py':'x=0'})
        self.b=graph({'core.py':'x=2','service.py':'import core','other.py':'x=0'})
        self.cases=[case('C','core'),case('S','service'),case('O','other')]
        self.targets=[dict(path=x['execution']['module']+'.py',module_sha256=m.di.index(self.b)[x['execution']['module']+'.py']['sha256']) for x in self.cases]
    def test_direct_transitive_unaffected_all_required(self):
        v=m.map_cases(self.cases,self.targets,self.b,comp(self.a,self.b))
        self.assertEqual([x['reason'] for x in v['cases']],['DIRECT_CHANGE','TRANSITIVE_DEPENDENCY','NO_STATIC_IMPACT_DETECTED'])
        self.assertEqual(v['impacted_count'],2);self.assertEqual(v['required_count'],3)
        self.assertTrue(all(x['required'] for x in v['cases']))
    def test_identical_no_exemption(self):
        v=m.map_cases(self.cases,self.targets,self.b,comp(self.b,self.b))
        self.assertEqual(v['impacted_count'],0);self.assertEqual(v['required_count'],3)
    def test_conservative_all_cases(self):
        a=graph({'core.py':'x=1','service.py':'import core','other.py':'import unknown_dependency'})
        b=graph({'core.py':'x=2','service.py':'import core','other.py':'import unknown_dependency'})
        targets=copy.deepcopy(self.targets);targets[2]['module_sha256']=m.di.index(b)['other.py']['sha256']
        v=m.map_cases(self.cases,targets,b,comp(a,b))
        self.assertEqual(v['impacted_count'],3);self.assertTrue(all(x['reason']=='CONSERVATIVE_FALLBACK' for x in v['cases']))
    def test_deleted_dependency(self):
        a=graph({'core.py':'x=1','service.py':'import core'})
        b=graph({'service.py':'import core'})
        v=m.map_cases([self.cases[1]],[self.targets[1]],b,comp(a,b))
        self.assertEqual(v['impacted_count'],1)
    def test_wrong_target_digest_or_path_rejected(self):
        for change in ({'module_sha256':'0'*64},{'path':'other.py'}):
            targets=copy.deepcopy(self.targets);targets[0].update(change)
            with self.assertRaises(ValueError):m.map_cases(self.cases,targets,self.b,comp(self.a,self.b))
    def test_missing_duplicate_case_rejected(self):
        with self.assertRaises(ValueError):m.map_cases(self.cases,self.targets[:-1],self.b,comp(self.a,self.b))
        with self.assertRaises(ValueError):m.map_cases([self.cases[0]]*3,self.targets,self.b,comp(self.a,self.b))
    def test_incomplete_impact_rejected(self):
        c=comp(self.a,self.b);c['current_impacted_paths']=[]
        with self.assertRaises(ValueError):m.map_cases(self.cases,self.targets,self.b,c)
    def test_stale_fail_closed(self):
        with patch.object(m.di,'view',return_value={'state':'BLOCK'}),patch.object(m.tp,'view',return_value={}),patch.object(m.runner,'current',side_effect=ValueError('stale')):
            v=m.view(None,None,'p','j')
        self.assertEqual(v['state'],'BLOCK');self.assertEqual(v['mappings'],{})
        self.assertTrue(v['full_regression_required']);self.assertFalse(v['selective_execution_authorized'])
if __name__=='__main__':unittest.main()
