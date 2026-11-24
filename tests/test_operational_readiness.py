import tempfile,sqlite3,unittest,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'tools')]
import acceptance_store,web_acceptance,backup_orbit,run_real_models
class ReadinessTests(unittest.TestCase):
    def test_acceptance_persist_and_fail_closed(self):
        with sqlite3.connect(':memory:') as c:
            self.assertFalse(acceptance_store.view(c,'proj-1')['state']['accepted'])
            acceptance_store.record(c,'proj-1','reviewer',{'requirement':'scope_approved','reference':'issue-12345','passed':True})
            self.assertEqual(acceptance_store.load(c,'proj-1')['evidence']['scope_approved']['reviewer'],'reviewer')
            with self.assertRaises(PermissionError):acceptance_store.accept(c,'proj-1','owner','ACCEPT WEB proj-1')
    def test_backup_restore(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);src=root/'a.sqlite';snap=root/'b.sqlite';rest=root/'c.sqlite'
            with sqlite3.connect(src) as c:
                c.execute('CREATE TABLE projects(id TEXT)')
                c.execute("INSERT INTO projects VALUES('project-1')")
                c.execute('CREATE TABLE auth_sessions(token_hash TEXT)')
                c.execute("INSERT INTO auth_sessions VALUES('test')")
            backup_orbit.copy_database(src,snap)
            backup_orbit.copy_database(snap,rest,True)
            with sqlite3.connect(rest) as c:
                self.assertEqual(c.execute('SELECT id FROM projects').fetchone()[0],'project-1')
                self.assertEqual(c.execute('SELECT count(*) FROM auth_sessions').fetchone()[0],0)
            with self.assertRaises(FileExistsError):backup_orbit.copy_database(src,snap)
    def test_model_preflight(self):
        with self.assertRaises(ValueError):run_real_models.config({})
        with self.assertRaises(ValueError):run_real_models.config({'AI_PROVIDER':'ollama','AI_MODEL_A':'a','AI_MODEL_B':'a'})
        self.assertEqual(run_real_models.config({'AI_PROVIDER':'ollama','AI_MODEL_A':'a','AI_MODEL_B':'b'})['model_b'],'b')
