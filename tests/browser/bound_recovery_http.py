"""CI-only authenticated HTTP recovery on an isolated copy of real planning state.

No live worker manipulation, real inference, or production release. The HTTP
handler and dispatcher are production code; only transport/sandbox are fixtures.
"""
import json
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import server
import agent_queue as aq
import bound_recovery as br
import coding_factory as cf
import dependency_completion as dc
import project_planning as pp
import studio_coding as sc
import studio_verification as qa
import verification_factory as vf
from requirements_fixture import fixture_chat
from test_verification_factory import FakeDocker,PY_IMG

class Client:
    def __init__(self,port,user):
        self.port=port
        self.cookie=''
        self.csrf=''
        status,data,headers=self.call('/api/auth/login',{'user':user,'password':'local-ci-fixture-password'})
        assert status==200 and data['user']==user
        self.cookie=headers['Set-Cookie'].split(';',1)[0]
        self.csrf=data['csrf_token']
        assert self.expect(200,'/api/auth/session')['csrf_token']==self.csrf

    def call(self,path,body=None,csrf=None):
        headers={'Origin':f'http://127.0.0.1:{self.port}','X-ORBIT-UI':'1','Content-Type':'application/json',
                 'Cookie':self.cookie,'X-ORBIT-CSRF':self.csrf if csrf is None else csrf}
        with closing(HTTPConnection('127.0.0.1',self.port,timeout=30)) as connection:
            connection.request('GET' if body is None else 'POST',path,
                               None if body is None else json.dumps(body),headers)
            response=connection.getresponse()
            return response.status,json.loads(response.read()),dict(response.getheaders())

    def expect(self,status,path,body=None,csrf=None):
        actual,data,_=self.call(path,body,csrf)
        assert actual==status,(path,actual,data)
        return data

def run(c,pid,root_package,snapshot):
    original=snapshot(c,pid)
    with tempfile.TemporaryDirectory(prefix='orbit-bound-http-') as temp:
        path=Path(temp)/'isolated.sqlite'
        with closing(sqlite3.connect(path)) as dest:c.backup(dest)
        with patch.object(server,'DB_PATH',path),aq.dispatcher_lock(path):
            with server.db() as db:
                assert not db.execute("SELECT 1 FROM agent_queue WHERE project_id=? AND status IN ('queued','running','paused','waiting_approval')",(pid,)).fetchone()
                assert not db.execute('SELECT 1 FROM studio_coding_bindings WHERE project_id=?',(pid,)).fetchone()
                db.execute("UPDATE agent_queue SET available_at=253402300799 WHERE project_id<>? AND status='queued'",(pid,))
            # Real HTTP server on an ephemeral loopback port. Dispatch manually
            # only after assertions, so cancellation/interrupt tests cannot race.
            with ThreadingHTTPServer(('127.0.0.1',0),server.Handler) as http:
                port=http.server_address[1]
                with patch.object(server,'PORT',port):
                    thread=threading.Thread(target=http.serve_forever,daemon=True)
                    thread.start()
                    try:
                        results=exercise(pid,root_package,port,snapshot)
                    finally:
                        http.shutdown()
                        thread.join()
    assert snapshot(c,pid)==original
    return results

def exercise(pid,root_package,port,snapshot):
    owner=Client(port,'ci-browser-user')
    dev=Client(port,'ci-developer')
    reviewer=Client(port,'ci-reviewer')
    viewer=Client(port,'ci-viewer')
    base=f'/api/projects/{pid}'
    wp=base+'/studio/work-packages/'
    completion=base+'/engineering/completions/confirm'
    state=lambda:owner.expect(200,base+'/state')
    def job_view(jid):
        return next(x for x in state()['workflow']['coding_jobs'] if x['job_id']==jid)
    def completion_view(jid):
        return next(x for x in state()['dependency_completion']['items'] if x['job_id']==jid)
    root_binding=next(x for x in state()['workflow']['work_packages']['bindings'] if x['package_id']==root_package)
    root_body=dict(adoption_version=root_binding['adoption_version'],package_id=root_package,
                   binding_digest=root_binding['digest'],confirmation='QUEUE ADOPTED WORK PACKAGE')
    def recover(kind,submit_path,submit_body,upstream=None):
        old=dev.expect(202,submit_path,submit_body)
        oid,oq=old['job_id'],old['queue_id']
        assert job_view(oid)['queue']['status']=='queued'
        if kind=='root':
            dev.expect(200,base+'/queue/'+oq+'/cancel',{})
            terminal='cancelled'
        else:
            # Simulated startup recovery of a claimed but uncertain task,
            # under exclusive ownership of this isolated database.
            with server.db() as db:
                claimed=aq.claim(db,int(time.time()),server.now())
                assert claimed['id']==oq
                aq.recover(db,int(time.time()),server.now())
            terminal='interrupted'
        prior=job_view(oid)
        assert prior['queue']['status']==terminal and prior['status']=='failed'
        assert prior['qa']['state']=='BLOCK'
        recovery=prior['recovery']
        assert recovery['state']=='READY_FOR_EXPLICIT_RETRY'
        src=recovery['source']
        assert src['previous_job_id']==oid and src['previous_queue_id']==oq
        assert src['previous_status']==terminal
        assert pp.digest(src)==recovery['source_digest']
        assert src['dependency_source_digest']==(submit_body['source_digest'] if upstream else None)
        body=dict(queue_id=oq,source_digest=recovery['source_digest'],
                  rationale='Explicitly recover this terminal synthetic development attempt.',
                  confirmation='RETRY BOUND WORK PACKAGE')
        with server.db() as db:
            before_job=cf.detail(db,oid)
            before_queue=dict(aq.get(db,pid,oq))
            before_binding=dict(sc.lookup(db,pid,oid))
            before_pin=db.execute('SELECT snapshot,digest FROM engineering_queue_sources WHERE job_id=?',(oid,)).fetchone()
            before_pin=dict(before_pin) if before_pin else None
            assert bool(before_pin)==bool(upstream)
            assert not db.execute('SELECT 1 FROM ai_usage WHERE project_id=? AND run_id=?',(pid,oid)).fetchone()
            before=snapshot(db,pid)
        for client in (reviewer,viewer):
            client.expect(403,wp+'retry',body)
        dev.expect(403,wp+'retry',body,csrf='0'*64)
        for changed in ({'source_digest':'wrong'},{'confirmation':'yes'},{'rationale':'short'}):
            dev.expect(400,wp+'retry',{**body,**changed})
        dev.expect(400,base+'/queue/'+oq+'/retry',{'confirmation':'RETRY QUEUE TASK'})
        with server.db() as db:
            assert snapshot(db,pid)==before
            # Fault after receipt INSERT; exact row digest rollback via HTTP.
            db.execute("CREATE TRIGGER http_retry_fault AFTER INSERT ON studio_bound_retries BEGIN SELECT RAISE(ABORT,'HTTP retry receipt fault'); END")
        try:
            failed=dev.expect(400,wp+'retry',body)
            assert failed['error']=='HTTP retry receipt fault'
        finally:
            with server.db() as db:
                db.execute('DROP TRIGGER http_retry_fault')
                assert snapshot(db,pid)==before
        new=dev.expect(202,wp+'retry',body)
        jid,qid=new['job_id'],new['queue_id']
        assert jid!=oid and qid!=oq and new['retry_of']==oq
        assert new['status']=='queued' and new['production_release_authorized'] is False
        queued=job_view(jid)
        assert queued['queue']['retry_of']==oq and queued['queue']['status']=='queued'
        assert queued['planning_binding']=='BOUND' and queued['qa']['state']=='BLOCK'
        assert queued['source_binding']['spec_digest']==src['spec_digest']
        assert job_view(oid)['recovery']['state']=='BLOCK'
        dev.expect(400,wp+'retry',body)
        with server.db() as db:
            receipt=db.execute('SELECT * FROM studio_bound_retries WHERE project_id=? AND job_id=?',(pid,jid)).fetchone()
            snap=json.loads(receipt['snapshot'])
            assert pp.digest(snap)==receipt['digest']==new['receipt_digest']
            assert snap['source']==src and snap['job_id']==jid and snap['queue_id']==qid
            assert snap['actor']==receipt['actor']=='ci-developer'
            assert receipt['previous_job_id']==oid
            assert all(snap[k] is False for k in ('automatic_dispatch','execution_authorized','production_release_authorized'))
            new_job=cf.detail(db,jid)
            assert new_job['spec']==before_job['spec']
            assert all(new_job[k] is None for k in ('proposal_a','proposal_b','review_a','review_b','manifest'))
            pin=db.execute('SELECT snapshot,digest FROM engineering_queue_sources WHERE job_id=?',(jid,)).fetchone()
            assert (dict(pin) if pin else None)==before_pin
            if upstream:assert json.loads(pin['snapshot'])['prerequisites'][0]['job_id']==upstream
            assert not db.execute('SELECT 1 FROM ai_usage WHERE project_id=? AND run_id=?',(pid,jid)).fetchone()
        with patch.object(server.model_provider,'chat',side_effect=fixture_chat) as calls:
            assert server.dispatch_one() is True
            assert calls.call_count==4
        ready=job_view(jid)
        assert ready['queue']['status']=='succeeded' and ready['status']=='ready'
        assert ready['planning_binding']=='BOUND' and ready['qa']['state']=='BLOCK'
        with server.db() as db:
            rows=db.execute('SELECT status,source FROM ai_usage WHERE project_id=? AND run_id=?',(pid,jid)).fetchall()
            assert len(rows)==4 and all(x['status']=='ok' and x['source']=='fixture' for x in rows)
            report=vf.verify_job(cf.detail(db,jid),python_image=PY_IMG,approval='RUN SANDBOX '+jid,runner=FakeDocker())
            assert report['gate']=='PASS'
            vf.store_report(db,report)
        fresh=job_view(jid)['qa']
        assert fresh['state']=='AWAITING_HUMAN_QA' and fresh['latest_version']==0
        assert fresh['source']['job_id']==jid and fresh['source']['queue_id']==qid
        criteria=[dict(id=x['id'],verdict='PASS',rationale='Synthetic fixture criterion reviewed for development evidence only.') for x in fresh['source']['acceptance']]
        qa_body=dict(job_id=jid,source_digest=fresh['source_digest'],expected_version=0,criteria=criteria,confirmation='ATTEST WORK PACKAGE QA')
        reviewer.expect(400,wp+'qa',{**qa_body,'job_id':oid})
        attested=reviewer.expect(201,wp+'qa',qa_body)
        assert attested['version']==1
        assert job_view(jid)['qa']['state']=='HUMAN_QA_PASS'
        candidate=completion_view(jid)
        assert candidate['state']=='AWAITING_CONFIRMATION' and candidate['source']['qa_digest']==attested['digest']
        complete_body=dict(job_id=jid,source_digest=candidate['source_digest'],expected_version=0,selected='B',
                           rationale='Explicit synthetic candidate completion for development evidence only.',
                           confirmation='CONFIRM DEPENDENCY COMPLETION DEV-B '+jid)
        finished=reviewer.expect(201,completion,complete_body)
        assert finished['version']==1 and finished['production_release_authorized'] is False
        assert completion_view(jid)['state']=='COMPLETION_EVIDENCE_CONFIRMED'
        historical=completion_view(oid)
        assert historical['state']=='SUPERSEDED' and historical['receipt'] is None
        assert job_view(oid)['qa']['state']=='BLOCK'
        with server.db() as db:
            assert cf.detail(db,oid)==before_job
            assert dict(aq.get(db,pid,oq))==before_queue
            assert dict(sc.lookup(db,pid,oid))==before_binding
            pin=db.execute('SELECT snapshot,digest FROM engineering_queue_sources WHERE job_id=?',(oid,)).fetchone()
            assert (dict(pin) if pin else None)==before_pin
            assert not db.execute('SELECT 1 FROM ai_usage WHERE project_id=? AND run_id=?',(pid,oid)).fetchone()
            saved=dc.latest(db,pid,src['adoption_version'],src['package_id'])
            assert saved['job_id']==jid and saved['digest']==finished['digest']
            assert dc.source(db,pid,jid)==json.loads(saved['snapshot'])['source']
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
        dev.expect(400,wp+'retry',body)
        return jid,dict(kind=kind,previous_status=terminal,retry_http=202,rollback=True,
                       model_calls=4,qa_http=201,completion_http=201,immutable_history=True)
    root_jid,root_result=recover('root',wp+'coding',root_body)
    eligible=[x for x in state()['dependency_queue']['items'] if x['state']=='READY_FOR_EXPLICIT_SUBMISSION']
    assert len(eligible)==1
    item=eligible[0]
    assert [x['job_id'] for x in item['source']['prerequisites']]==[root_jid]
    dep_body=dict(adoption_version=item['adoption_version'],package_id=item['package_id'],
                  binding_digest=item['source']['binding_digest'],source_digest=item['source_digest'],
                  confirmation='QUEUE DEPENDENT WORK PACKAGE')
    dep_jid,dep_result=recover('dependent',base+'/engineering/dependent-coding',dep_body,root_jid)
    with server.db() as db:
        report=db.execute('SELECT report_json FROM coding_verifications WHERE project_id=? AND job_id=? ORDER BY rowid DESC LIMIT 1',(pid,root_jid)).fetchone()
        vf.store_report(db,json.loads(report['report_json']))
    assert job_view(dep_jid)['planning_binding']=='STALE'
    assert job_view(dep_jid)['qa']['state']=='STALE'
    assert completion_view(dep_jid)['state']=='STALE'
    return dict(root=root_result,dependent=dep_result,recovered_root_prerequisite=True,upstream_stale=True)
