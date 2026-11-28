import hashlib,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_dependency_impact as d

def proposal(files):
    return dict(summary='Fixture',files=[dict(path=k,content=v,sha256=hashlib.sha256(v.encode()).hexdigest()) for k,v in files.items()])
def graph(files):return d.graph(proposal(files))
def compare(a,b):
    old=d.index(a);new=d.index(b);x=d.changes.expected_changes(old,new)
    return dict(from_commit='old',to_commit='new',changes=x,
        counts={s:sum(v['status']==s for v in x) for s in ('ADDED','MODIFIED','DELETED')},
        unchanged_count=sum(old.get(p)==new[p] for p in new if p in old))
def impact(a,b):return d.impact(a,b,compare(a,b))

class DependencyImpactTests(unittest.TestCase):
    def test_transitive_and_unaffected(self):
        files={'core.py':'x=1','service.py':'import core','test_service.py':'import service','other.py':'x=0'}
        a=graph(files);b=graph(dict(files,**{'core.py':'x=2'}));v=impact(a,b)
        self.assertEqual(v['direct_paths'],['core.py'])
        self.assertEqual(v['transitive_paths'],['service.py','test_service.py'])
        self.assertEqual(v['current_impacted_paths'],['core.py','service.py','test_service.py'])
        self.assertTrue(v['full_regression_required'])
    def test_deleted_dependency_uses_before_edges(self):
        a=graph({'core.py':'x=1','service.py':'import core'})
        b=graph({'service.py':'import core'})
        v=impact(a,b);self.assertEqual(v['removed_impacted_paths'],['core.py'])
        self.assertEqual(v['transitive_paths'],['service.py'])
        self.assertEqual(v['analysis_mode'],'CONSERVATIVE_ALL_FILES')
    def test_relative_and_package_import(self):
        g=graph({'pkg/__init__.py':'','pkg/core.py':'x=1','pkg/service.py':'from . import core','test.py':'from pkg.service import x'})
        self.assertIn(dict(importer='pkg/service.py',dependency='pkg/core.py'),g['edges'])
        self.assertIn(dict(importer='test.py',dependency='pkg/service.py'),g['edges'])
        self.assertIn(dict(importer='test.py',dependency='pkg/__init__.py'),g['edges'])
        self.assertEqual(g['uncertainties'],[])
    def test_cycle_terminates(self):
        a=graph({'a.py':'import b','b.py':'import a'})
        b=graph({'a.py':'import b\nx=1','b.py':'import a'})
        self.assertEqual(impact(a,b)['transitive_paths'],['b.py'])
    def test_dynamic_import_conservative(self):
        a=graph({'a.py':'import importlib\nimportlib.import_module("b")','b.py':'x=1','c.py':'x=1'})
        b=graph({'a.py':'import importlib\nimportlib.import_module("b")','b.py':'x=2','c.py':'x=1'})
        v=impact(a,b);self.assertEqual(v['analysis_mode'],'CONSERVATIVE_ALL_FILES')
        self.assertEqual(v['current_impacted_paths'],['a.py','b.py','c.py'])
    def test_unsupported_and_parse_error_conservative(self):
        for name,source in [('config.json','{}'),('bad.py','def ???'),('consumer.py','import unknown_dependency')]:
            a=graph({'a.py':'x=1',name:source});b=graph({'a.py':'x=2',name:source})
            self.assertEqual(impact(a,b)['current_impacted_paths'],sorted(['a.py',name]))
            self.assertTrue(b['uncertainties'])
    def test_identical_no_change_no_skip_authority(self):
        a=graph({'a.py':'x=1'});v=impact(a,a)
        self.assertEqual(v['impacted_paths'],[]);self.assertTrue(v['full_regression_required'])
    def test_tampered_change_manifest_rejected(self):
        a=graph({'a.py':'x=1'});b=graph({'a.py':'x=2'})
        c=compare(a,b);c['changes']=[]
        with self.assertRaises(ValueError):d.impact(a,b,c)
    def test_ambiguous_module_conservative(self):
        a=graph({'pkg.py':'x=1','pkg/__init__.py':'x=2','a.py':'import pkg'})
        self.assertTrue(any(x['code']=='AMBIGUOUS_MODULE' for x in a['uncertainties']))
    def test_stale_fails_closed(self):
        with patch.object(d.changes,'view',return_value={'state':'BLOCK'}):
            v=d.view(None,None,'p','j')
        self.assertEqual(v['state'],'BLOCK');self.assertEqual(v['graphs'],{})
        self.assertTrue(v['full_regression_required']);self.assertFalse(v['selective_execution_authorized'])
if __name__=='__main__':unittest.main()
