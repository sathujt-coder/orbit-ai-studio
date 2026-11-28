import hashlib,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import engineering_git_changes as g

def proposal(files):
    return dict(summary='Fixture',files=[dict(path=k,content=v,sha256=hashlib.sha256(v.encode()).hexdigest()) for k,v in files.items()])

class GitChangesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'orbit.db';self.pid='p';self.jid='j'
        self.base=g.ws.initialize(self.db,self.pid,dict(confirmation=g.ws.CONFIRMATION))['base_commit']
        self.proposals={'A':proposal({'main.py':'x=1\n','old.py':'x=1\n','same.py':'x=0\n'}),
                        'B':proposal({'main.py':'x=2\n','new.py':'x=1\n','same.py':'x=0\n'})}
        self.git={k:g.sb.git_objects(v,self.base,self.jid,k)[0] for k,v in self.proposals.items()}
    def analyze(self):return g.analyze(self.db,self.pid,self.jid,self.base,self.proposals,self.git)
    def test_real_git_add_modify_delete(self):
        d=self.analyze()
        self.assertEqual(d['A_to_B']['counts'],dict(ADDED=1,MODIFIED=1,DELETED=1))
        self.assertEqual(d['A_to_B']['unchanged_count'],1)
        self.assertEqual([(x['path'],x['status']) for x in d['A_to_B']['changes']],
                         [('main.py','MODIFIED'),('new.py','ADDED'),('old.py','DELETED')])
        self.assertEqual(d['baseline_to_B']['counts'],dict(ADDED=3,MODIFIED=0,DELETED=0))
        self.assertEqual(d['A_to_B']['changes'][0]['before']['sha256'],hashlib.sha256(b'x=1\n').hexdigest())
    def test_identical_tree_no_change(self):
        self.proposals['B']=self.proposals['A']
        self.git['B']=g.sb.git_objects(self.proposals['B'],self.base,self.jid,'B')[0]
        d=self.analyze()
        self.assertEqual(d['A_to_B']['changes'],[])
        self.assertEqual(d['A_to_B']['unchanged_count'],3)
    def test_pristine_baseline_unchanged(self):
        repo=g.ws.location(self.db,self.pid)
        def snapshot():return {p.relative_to(repo).as_posix():p.read_bytes() for p in repo.rglob('*') if p.is_file()}
        before=snapshot();a=self.analyze();b=self.analyze()
        self.assertEqual(a,b);self.assertEqual(before,snapshot())
        self.assertEqual(g.ws.inspect(repo,self.pid),self.base)
    def test_tampered_git_receipt_rejected(self):
        self.git['B']['tree']='0'*40
        with self.assertRaises(ValueError):self.analyze()
    def test_tampered_manifest_rejected(self):
        self.proposals['B']['files'][0]['sha256']='0'*64
        self.git['B']=g.sb.git_objects(self.proposals['B'],self.base,self.jid,'B')[0]
        with self.assertRaises(ValueError):self.analyze()
    def test_wrong_project_or_parent_rejected(self):
        with self.assertRaises((ValueError,OSError)):
            g.analyze(self.db,'other',self.jid,self.base,self.proposals,self.git)
        with self.assertRaises(ValueError):
            g.analyze(self.db,self.pid,self.jid,'0'*40,self.proposals,self.git)
    def test_stale_or_superseded_fail_closed(self):
        with patch.object(g.quality,'lineage',side_effect=ValueError('Superseded')):
            v=g.view(None,self.db,self.pid,self.jid)
        self.assertEqual(v['state'],'BLOCK');self.assertEqual(v['comparisons'],{})
        self.assertTrue(all(v[k] is False for k in g.FLAGS))
    def test_git_diff_disagreement_rejected(self):
        old=g.ws.git
        def fake(repo,*args,**kwargs):
            if args[0]=='diff-tree':return b''
            return old(repo,*args,**kwargs)
        with patch.object(g.ws,'git',side_effect=fake):
            with self.assertRaises(ValueError):self.analyze()
if __name__=='__main__':unittest.main()
