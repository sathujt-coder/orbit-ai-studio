import sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import agent_queue as q
import auth_store,auth_policy,auth_http,model_provider as mp

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.execute('PRAGMA foreign_keys=ON')
        self.c.executescript("""CREATE TABLE projects(id TEXT PRIMARY KEY);
           CREATE TABLE tasks(project_id TEXT,stage_id TEXT,position INTEGER,status TEXT);
           CREATE TABLE coding_jobs(id TEXT PRIMARY KEY,project_id TEXT,status TEXT,error TEXT,updated_at TEXT);
           INSERT INTO projects VALUES('p'),('p2'),('p3');
           INSERT INTO tasks VALUES('p','po',0,'queued'),('p','dev',1,'queued');""")
        auth_store.ensure_schema(self.c);q.ensure_schema(self.c)
        auth_store.create_user(self.c,'owner','fixture-password-123');auth_store.create_user(self.c,'viewer','fixture-password-123')
        for p in ('p','p2','p3'):auth_store.grant(self.c,'owner',p,'owner')
        auth_store.grant(self.c,'viewer','p','viewer')
        self.lanes=mp.load_config({})
    def tearDown(self):self.c.close()
    def add(self,p='p',priority=5,dep=None,kind='pipeline',jid=None,mode='all'):
        if jid:self.c.execute('INSERT INTO coding_jobs VALUES(?,?,?,NULL,?)',(jid,p,'queued','stamp'))
        return q.enqueue(self.c,p,kind,'owner',0,self.lanes,mode=mode if kind=='pipeline' else None,coding_job_id=jid,priority=priority,dependency_id=dep,now=100)
    def claim(self,t=100):return q.claim(self.c,t,'stamp')
    def state(self,p,i):return q.get(self.c,p,i)['status']
    def act(self,i,a,p='p',priority=None):return q.control(self.c,p,i,'owner',a,101,'stamp',priority)
    def test_priority_fifo_dependency_and_scoping(self):
        first=self.add('p',1);second=self.add('p2',9);third=self.add('p3',9)
        blocked=self.add('p',9,first,'coding','j')
        with self.assertRaises(ValueError):q.enqueue(self.c,'p2','coding','owner',0,self.lanes,coding_job_id='other',dependency_id=first)
        r=self.claim();self.assertEqual(r['id'],second);q.change(self.c,r,'succeeded','done',100)
        r=self.claim();self.assertEqual(r['id'],third);q.change(self.c,r,'succeeded','done',100)
        r=self.claim();self.assertEqual(r['id'],first);q.change(self.c,r,'succeeded','done',100)
        self.assertEqual(self.claim()['id'],blocked)
    def test_pause_resume_cancel_and_priority(self):
        i=self.add();self.act(i,'pause');self.assertIsNone(self.claim());self.act(i,'priority',priority=9);self.act(i,'resume')
        r=self.claim(101);self.assertEqual(r['priority'],9);self.act(i,'cancel')
        q.boundary(self.c,q.get(self.c,'p',i),'done',102,'stamp','po')
        self.assertEqual(self.state('p',i),'cancelled')
    def test_pipeline_checkpoints_and_approval(self):
        i=self.add();r=self.claim();self.c.execute("UPDATE tasks SET status='done' WHERE stage_id='po'")
        q.boundary(self.c,r,'done',100,'stamp','po');r=self.claim();self.assertEqual(r['checkpoint_stage'],'po')
        self.c.execute("UPDATE tasks SET status='awaiting_approval' WHERE stage_id='dev'")
        q.boundary(self.c,r,'awaiting_approval',100,'stamp','dev')
        self.assertEqual(self.state('p',i),'waiting_approval')
        with self.assertRaises(ValueError):self.act(i,'resume')
        self.c.execute("UPDATE tasks SET status='approved' WHERE stage_id='dev'")
        self.act(i,'resume');self.assertEqual(self.state('p',i),'queued')
    def test_bounded_pre_dispatch_deferral_and_dead_dependency(self):
        i=self.add();dep=self.add('p',5,i,'coding','j')
        for t in (100,102,106):
            r=self.claim(t);q.defer(self.c,r,t,'stamp')
        self.assertEqual(self.state('p',i),'dead');self.assertIsNone(self.claim(110))
        self.assertEqual(self.state('p',dep),'dead')
        self.assertEqual(self.c.execute("SELECT status FROM coding_jobs WHERE id='j'").fetchone()[0],'failed')
    def test_crash_recovery_preserves_queue_and_does_not_replay(self):
        i=self.add();j=self.add('p2',kind='coding',jid='j')
        r=self.claim();self.assertEqual(r['id'],i);self.c.execute("UPDATE tasks SET status='drafting' WHERE stage_id='po'")
        q.recover(self.c,101,'stamp')
        self.assertEqual(self.state('p',i),'interrupted');self.assertEqual(self.state('p2',j),'queued')
        self.assertEqual(self.c.execute("SELECT status FROM tasks WHERE stage_id='po'").fetchone()[0],'needs_revision')
        self.assertEqual(self.claim(101)['id'],j)
    def test_permission_revoked_and_coding_cancel(self):
        i=self.add();self.c.execute("DELETE FROM auth_memberships WHERE project_id='p' AND user_id='owner'")
        self.assertIsNone(self.claim());self.assertEqual(self.state('p',i),'dead')
        j=self.add('p2',kind='coding',jid='j');self.act(j,'cancel','p2')
        self.assertEqual(self.c.execute("SELECT status FROM coding_jobs WHERE id='j'").fetchone()[0],'failed')
    def test_active_unique_and_no_running_coding_interrupt(self):
        i=self.add('p',kind='coding',jid='j')
        with self.assertRaises(ValueError):q.enqueue(self.c,'p','coding','owner',0,self.lanes,coding_job_id='j2')
        self.claim()
        for a in ('pause','cancel'):
            with self.assertRaises(ValueError):self.act(i,a)
    def test_api_and_viewer_denied(self):
        i=self.add();token=auth_store.login(self.c,'viewer','fixture-password-123')
        h={'Cookie':auth_http.COOKIE+'='+token,'Origin':'http://127.0.0.1:8787','X-ORBIT-CSRF':auth_http.csrf_for(token)}
        self.assertEqual(auth_policy.check(self.c,'GET','/api/projects/p/queue','',{},h,8787)[0],200)
        self.assertEqual(auth_policy.check(self.c,'GET','/api/projects/p2/queue','',{},h,8787)[0],403)
        self.assertEqual(auth_policy.check(self.c,'POST','/api/projects/p/queue/'+i+'/cancel','',{},h,8787)[0],403)
        with self.assertRaises(PermissionError):q.control(self.c,'p',i,'viewer','cancel',101,'stamp')
    def test_exclusive_dispatcher_lock(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.sqlite'
            with q.dispatcher_lock(path):
                with self.assertRaises(RuntimeError):
                    with q.dispatcher_lock(path):pass
            with q.dispatcher_lock(path):pass

    def test_next_stage_dependency_waits_for_approval(self):
        i=self.add(mode='next');dep=self.add(kind='coding',jid='j',dep=i)
        r=self.claim();self.c.execute("UPDATE tasks SET status='awaiting_approval' WHERE stage_id='po'")
        q.boundary(self.c,r,'awaiting_approval',100,'stamp','po')
        self.assertEqual(self.state('p',i),'waiting_approval');self.assertIsNone(self.claim())
        self.c.execute("UPDATE tasks SET status='approved' WHERE stage_id='po'")
        self.act(i,'resume');self.assertEqual(self.state('p',i),'succeeded')
        self.assertEqual(self.claim(101)['id'],dep)
    def test_real_process_crash_and_restart(self):
        import os,subprocess,time
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            database=Path(directory)/'queue.sqlite'
            env=dict(os.environ,AI_COMPANY_DB=str(database),AI_PROVIDER='demo',AI_PROVIDER_A='demo',AI_PROVIDER_B='demo',PYTHONPATH=str(root/'backend'))
            setup="""import server,auth_store,agent_queue
server.init_db()
with server.db() as c:
    a=server.create_project('Crash test','Crash recovery fixture','Web app',c)
    b=server.create_project('Pending test','Pending recovery fixture','Web app',c)
    auth_store.create_user(c,'fixture','fixture-password-123')
    for pid in (a,b):auth_store.grant(c,'fixture',pid,'owner')
    for pid,priority in ((a,9),(b,1)):agent_queue.enqueue(c,pid,'pipeline','fixture',0,server.MODEL_LANES,mode='next',priority=priority)
"""
            subprocess.run([sys.executable,'-c',setup],env=env,check=True,timeout=15)
            # Real process is killed after a durable claim and partial stage update.
            crash="""import server,agent_queue,time
with agent_queue.dispatcher_lock(server.DB_PATH):
    with server.db() as c:
        row=agent_queue.claim(c,int(time.time()),server.now())
        c.execute("UPDATE tasks SET status='drafting' WHERE project_id=? AND stage_id='po'",(row['project_id'],))
    print('CLAIMED',flush=True)
    time.sleep(60)
"""
            process=subprocess.Popen([sys.executable,'-c',crash],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    with sqlite3.connect(database) as db:
                        if db.execute("SELECT COUNT(*) FROM agent_queue WHERE status='running'").fetchone()[0]==1:break
                    time.sleep(.05)
                else:self.fail('Child did not claim task')
                process.kill();process.wait(timeout=5)
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=5)
            restart="""import server,agent_queue,time
with agent_queue.dispatcher_lock(server.DB_PATH):
    with server.db() as c:agent_queue.recover(c,int(time.time()),server.now())
    assert server.dispatch_one()
"""
            subprocess.run([sys.executable,'-c',restart],env=env,check=True,timeout=15)
            with sqlite3.connect(database) as db:
                self.assertEqual(db.execute('SELECT status FROM agent_queue ORDER BY priority DESC').fetchall(),[('interrupted',),('succeeded',)])
                self.assertEqual(db.execute("SELECT t.status FROM tasks t JOIN agent_queue q ON q.project_id=t.project_id WHERE t.stage_id='po' ORDER BY q.priority DESC").fetchall(),[('needs_revision',),('done',)])
