"""Final system acceptance: synthetic review transport, real SQLite and queue."""
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
import test_work_breakdown as fixture
import work_breakdown as w
import project_planning as pp
import agent_queue as q
import usage_store

class FinalPlanningAcceptance(unittest.TestCase):
    def setUp(self):
        self.h=fixture.WbsTests();self.h.setUp();self.addCleanup(self.h.tearDown)
        self.c=self.h.c;usage_store.ensure_schema(self.c)
        self.h.run_pm();base=self.h.seed();v=self.h.save(fixture.detail(base['current']['document']))
        p=v['current'];doc=v['resource_estimates']['draft']
        for item in doc['packages']:item.update(effort_minutes=30,role='Dev')
        w.resource_estimates.save(self.c,'p','owner',dict(expected_version=0,wbs_version=p['version'],wbs_digest=p['digest'],
            document=doc,confirmation='SAVE RESOURCE ESTIMATES'),'t',v)
        v=w.view(self.c,'p');doc=v['sprint_schedule']['draft']
        doc['sprints']=[dict(id='S1',start='2026-12-01',end='2026-12-07',capacity={'Dev':180})]
        for item in doc['assignments']:item['sprint']='S1'
        doc['milestones']=[dict(id='M1',title='Fixture milestone',sprint='S1',packages=[x['id'] for x in doc['assignments']])]
        w.sprint_schedule.save(self.c,'p','owner',dict(v['sprint_schedule']['source'],expected_version=0,document=doc,
            confirmation='SAVE SPRINT SCHEDULE'),'t',v)
        self.r=w.planning_review;self.a=w.planning_adoption
    def enqueue(self):
        v=w.view(self.c,'p')
        identifier=self.r.enqueue(self.c,'p','owner',0,self.h.lanes,dict(bundle_digest=v['cross_review']['bundle_digest'],
            confirmation='RUN PM CROSS REVIEW'),v)
        return identifier
    def review(self):
        identifier=self.enqueue();row=q.claim(self.c,9999999999,'t')
        snap=self.r.checked(self.c,'p',identifier,w.view(self.c,'p'))
        def call(lane,system,user,schema):
            packet=json.loads(user)
            self.assertEqual(packet['author'],'PM-'+('B' if lane=='A' else 'A'))
            uid=usage_store.start(self.c,self.h.lanes[lane],'p','pm-'+lane,'planning_cross_review',identifier)
            usage_store.finish(self.c,uid,dict(elapsed_ms=1,status='ok',input_tokens=20,output_tokens=30,total_tokens=50,
                coverage='complete',source='synthetic_test'))
            return json.dumps(dict(verdict='APPROVE',score=90,feedback='Synthetic evidence',checks={k:True for k in self.r.DIMENSIONS}))
        evidence=self.r.run(call,snap)
        result=self.r.persist(self.c,'p',identifier,evidence,self.h.lanes,'t',w.view(self.c,'p'))
        q.boundary(self.c,row,result,9999999999,'t')
        v=w.view(self.c,'p');self.assertTrue(v['adoption']['can_adopt'])
        return identifier,dict(v['adoption']['binding'],expected_version=0,confirmation='APPROVE AND ADOPT PLANNING BUNDLE')
    def test_audit_snapshot_tamper_and_ledger_fail_closed(self):
        identifier,body=self.review()
        adopted=self.a.adopt(self.c,'p','reviewer',body,'t',w.view(self.c,'p'))
        self.assertEqual(adopted['current']['digest'],pp.digest(adopted['current']['snapshot']))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM auth_audit WHERE action='planning_adopt:1' AND actor='reviewer'").fetchone()[0],1)
        self.c.execute("UPDATE ai_usage SET coverage='unknown' WHERE run_id=?",(identifier,))
        self.assertFalse(w.view(self.c,'p')['cross_review']['quality_ready'])
        self.assertTrue(w.view(self.c,'p')['adoption']['stale'])
        self.c.execute("UPDATE planning_adoptions SET snapshot='{}' WHERE project_id='p'")
        self.assertTrue(w.view(self.c,'p')['adoption']['stale'])
        self.assertFalse(w.view(self.c,'p')['adoption']['execution_authorized'])
    def test_concurrent_adoption_single_commit(self):
        _,body=self.review();self.c.commit()
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'acceptance.sqlite')
            with sqlite3.connect(path) as dst:self.c.backup(dst)
            barrier=threading.Barrier(2);out=[]
            def worker():
                c=sqlite3.connect(path,timeout=10);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
                try:
                    barrier.wait(timeout=5)
                    # Same serialization boundary as production server LOCK.
                    c.execute('BEGIN IMMEDIATE')
                    self.a.adopt(c,'p','reviewer',body,'t',w.view(c,'p'));c.commit();out.append('adopted')
                except ValueError:c.rollback();out.append('blocked')
                finally:c.close()
            threads=[threading.Thread(target=worker) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join(15)
            self.assertEqual(sorted(out),['adopted','blocked'])
            with sqlite3.connect(path) as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM planning_adoptions').fetchone()[0],1)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM auth_audit WHERE action='planning_adopt:1'").fetchone()[0],1)
                self.assertEqual(list(c.execute('PRAGMA foreign_key_check')),[])
    def test_restart_interrupts_review_and_blocks_dependent(self):
        identifier=self.enqueue();q.claim(self.c,9999999999,'t')
        dependent=q.enqueue(self.c,'p','pipeline','owner',0,self.h.lanes,mode='next',dependency_id=identifier)
        self.c.execute('CREATE TABLE coding_jobs(id TEXT,status TEXT,error TEXT,updated_at TEXT)')
        self.c.execute('CREATE TABLE tasks(project_id TEXT,stage_id TEXT,status TEXT)')
        self.c.commit()
        q.recover(self.c,9999999999,'t')
        self.assertEqual(q.get(self.c,'p',identifier)['status'],'interrupted')
        self.assertIsNone(q.claim(self.c,9999999999,'t'))
        self.assertEqual(q.get(self.c,'p',dependent)['reason'],'dependency_failed')
        self.assertFalse(w.view(self.c,'p')['adoption']['can_adopt'])
        self.assertIsNone(self.a.latest(self.c,'p'))
