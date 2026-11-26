"""P6.3g: explicit local-only Git-bound replay of BOTH reviewed candidates.

The trusted OS operator runs Docker; HTTP exposes redacted evidence only.
The original project baseline and P6.3f selection report are never overwritten.
"""
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

import engineering_candidate_selection as sel
import project_git_workspace as ws
import project_planning as pp
import product_requirements as pr
import verification_factory as vf
import react_candidate_gate as react
from verified_pr import verified_bundle

FLAGS = sel.FLAGS


def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_sandbox_runs(
        project_id TEXT NOT NULL REFERENCES projects(id),
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        version INTEGER NOT NULL CHECK(version>0),
        snapshot TEXT NOT NULL, digest TEXT NOT NULL,
        actor TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id,version))""")
    for op in ('UPDATE','DELETE'):
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS engineering_sandbox_no_{op.lower()}
            BEFORE {op} ON engineering_sandbox_runs
            BEGIN SELECT RAISE(ABORT,'Immutable engineering sandbox receipt'); END""")
    c.execute("""CREATE TRIGGER IF NOT EXISTS engineering_sandbox_no_replace
        BEFORE INSERT ON engineering_sandbox_runs
        WHEN EXISTS(SELECT 1 FROM engineering_sandbox_runs WHERE project_id=NEW.project_id
                    AND job_id=NEW.job_id AND version=NEW.version)
        BEGIN SELECT RAISE(ABORT,'Duplicate engineering sandbox receipt'); END""")


def latest(c,pid,jid):
    return c.execute('SELECT * FROM engineering_sandbox_runs WHERE project_id=? AND job_id=? ORDER BY version DESC LIMIT 1',
                     (pid,jid)).fetchone()


def current(c,db_path,pid,jid):
    src=sel.source(c,db_path,pid,jid)
    row=sel.latest(c,pid,jid)
    if not row:
        raise ValueError('Current explicit Tech Lead selection required')
    decision=sel.validated_receipt(c,pid,row,src)['decision']
    job,prior=sel.current_inputs(c,pid,src)
    context=dict(schema='orbit.engineering-sandbox-source.v1',source=src,
                 selection_version=row['version'],selection_digest=row['digest'],
                 selected=decision['selected'],selected_digest=decision['selected_digest'],
                 profile=prior.get('profile') or 'legacy',**FLAGS)
    if context['profile'] not in ('legacy',react.PROFILE):
        raise ValueError('Unsupported sandbox profile')
    return context,job,decision


def git_objects(proposal,base,jid,lane):
    """Deterministic Git objects from validated bytes; no checkout filters/hooks."""
    root={}
    objects={}
    def obj(kind,raw):
        oid=ws.object_id(kind,raw)
        objects[oid]=(kind,raw)
        return oid
    for f in proposal['files']:
        parts=f['path'].split('/')
        node=root
        for part in parts[:-1]:
            node=node.setdefault(part,{})
            if not isinstance(node,dict):
                raise ValueError('Candidate path prefix collision')
        if parts[-1] in node:
            raise ValueError('Candidate path collision')
        node[parts[-1]]=obj('blob',f['content'].encode('utf-8'))
    def tree(node):
        raw=b''
        for name,value in sorted(node.items(),key=lambda x:(x[0]+('/' if isinstance(x[1],dict) else '')).encode()):
            is_dir=isinstance(value,dict)
            oid=tree(value) if is_dir else value
            raw+=(b'40000 ' if is_dir else b'100644 ')+name.encode()+b'\0'+bytes.fromhex(oid)
        return obj('tree',raw)
    tid=tree(root)
    raw=(f'tree {tid}\nparent {base}\nauthor ORBIT Sandbox <sandbox@orbit.invalid> 0 +0000\n'
         f'committer ORBIT Sandbox <sandbox@orbit.invalid> 0 +0000\n\nORBIT candidate {jid} {lane}\n').encode()
    commit=obj('commit',raw)
    return dict(commit=commit,tree=tid,parent=base,source_sha256=vf.plan_lane(proposal)['sha256']),objects


def materialize(db_path,pid,jid,lane,proposal,base,work):
    repo=ws.location(db_path,pid)
    if ws.inspect(repo,pid)!=base:
        raise ValueError('Git baseline changed')
    meta,objects=git_objects(proposal,base,jid,lane)
    with tempfile.TemporaryDirectory(prefix='orbit-git-candidate-') as private:
        clone=Path(private)/'candidate.git'
        shutil.copytree(repo,clone)
        # The copy is checked BEFORE any Git operation or candidate object write.
        if ws.inspect(clone,pid)!=base:
            raise ValueError('Copied baseline changed')
        for oid,(kind,raw) in objects.items():
            if ws.git(clone,'hash-object','-w','-t',kind,'--stdin',data=raw).decode().strip()!=oid:
                raise ValueError('Git object identity mismatch')
        ref='refs/heads/orbit-candidate-'+lane
        ws.git(clone,'update-ref',ref,meta['commit'],'0'*40)
        if ws.git(clone,'rev-parse',ref+'^').decode().strip()!=base:
            raise ValueError('Git candidate parent mismatch')
        entries=ws.git(clone,'ls-tree','-rz',meta['commit']).split(b'\0')
        expected={f['path']:f for f in proposal['files']}
        recovered={}
        for entry in entries:
            if not entry:continue
            header,path=entry.split(b'\t',1)
            mode,kind,oid=header.decode().split(' ')
            name=path.decode('utf-8')
            if mode!='100644' or kind!='blob' or name not in expected or name in recovered:
                raise ValueError('Unexpected Git tree entry')
            raw=ws.git(clone,'cat-file','blob',oid)
            f=expected[name]
            if raw!=f['content'].encode('utf-8') or hashlib.sha256(raw).hexdigest()!=f['sha256']:
                raise ValueError('Git materialized source mismatch')
            recovered[name]=dict(path=name,content=raw.decode('utf-8'),sha256=f['sha256'])
        if set(recovered)!=set(expected):
            raise ValueError('Incomplete Git tree')
        # Retain proposal order for the existing canonical lane digest.
        extracted=dict(proposal,files=[recovered[f['path']] for f in proposal['files']])
        root=vf._materialize_proposal(extracted,work)
        # Verify the exact files mounted read-only in Docker.
        for f in extracted['files']:
            if hashlib.sha256((root/f['path']).read_bytes()).hexdigest()!=f['sha256']:
                raise ValueError('Sandbox file digest mismatch')
    return root,meta


def version(c,pid,jid):
    row=latest(c,pid,jid)
    return row['version'] if row else 0


def validate(context,job,decision,report,git):
    proposals=vf.safe_job(job)
    src=context['source']
    if (report['job_id']!=src['job_id'] or report['project_id']!=src['project_id']
        or report.get('approval')!='local_cli_explicit' or report['sandbox']['runtime']!='docker'
        or report['sandbox']['network']!='none'
        or (report.get('profile') or 'legacy')!=context['profile']):
        raise ValueError('Sandbox report provenance mismatch')
    if report['gate']!='PASS':
        if report['gate']!='BLOCK' or report.get('verdict') not in ('blocked','failed','not_verified'):
            raise ValueError('Unknown sandbox verdict')
        return
    if set(git)!=set(proposals) or set(report['lanes'])!=set(proposals):
        raise ValueError('Both Git-bound candidates required')
    for lane,proposal in proposals.items():
        expected,_=git_objects(proposal,src['base_commit'],src['job_id'],lane)
        if git[lane]!=expected or report['lanes'][lane]['sha256']!=expected['source_sha256']:
            raise ValueError('Sandbox Git/source binding mismatch')
        for step in report['lanes'][lane]['steps']:
            vf.pinned_image(step['image'])
    # Reuse all existing selection/export evidence checks with the new report.
    # Compare against the original selection, but allow new real test counts.
    from web_candidate_selection import decide
    replay=decide(job,report,selected=decision['selected'],techlead=decision['techlead'],
                  rationale=decision['rationale'],confirmation='SELECT DEV-'+decision['selected']+' '+job['id'])
    verified_bundle(job,report,decision=replay)
    if replay['selected_digest']!=context['selected_digest']:
        raise ValueError('Selected source changed')


def run(c,db_path,pid,jid,actor,expected_digest,expected_version,confirmation,
        *,python_image=None,node_image=None,react_image=None,timeout=25):
    if confirmation!='RUN ENGINEERING SANDBOX '+jid:
        raise PermissionError('Explicit local sandbox execution confirmation required')
    if type(expected_version) is not int or expected_version<0:
        raise ValueError('Invalid sandbox receipt version')
    if c.in_transaction:
        raise ValueError('Sandbox requires an idle database connection')
    # Snapshot under one read transaction; do not hold DB writer lock during Docker.
    c.execute('BEGIN')
    try:
        pp.check_role(c,pid,actor,'approve')
        context,job,decision=current(c,db_path,pid,jid)
        if pp.digest(context)!=expected_digest or version(c,pid,jid)!=expected_version:
            raise ValueError('Stale sandbox execution source or version')
        c.commit()
    except Exception:
        c.rollback();raise
    git={}
    def extract(lane,proposal,work):
        root,meta=materialize(db_path,pid,jid,lane,proposal,context['source']['base_commit'],work)
        git[lane]=meta
        return root
    if context['profile']==react.PROFILE:
        report=react.verify_react(job,image=react_image,approval='RUN REACT SANDBOX '+jid,
                                  timeout=timeout,materialize=extract)
    else:
        report=vf.verify_job(job,python_image=python_image,node_image=node_image,
                             timeout=timeout,approval='RUN SANDBOX '+jid,materialize=extract)
    validate(context,job,decision,report,git)
    # Store only structural evidence, not untrusted test stdout/stderr.
    for lane in report['lanes'].values():
        for step in lane.get('steps',[]):
            step.pop('output',None)
    snapshot=dict(source=context,git=git,report=report,actor=actor,scope='development_evidence_only',**FLAGS)
    digest=pp.digest(snapshot)
    c.execute('BEGIN IMMEDIATE')
    try:
        pp.check_role(c,pid,actor,'approve')
        fresh,fresh_job,fresh_decision=current(c,db_path,pid,jid)
        if fresh!=context or version(c,pid,jid)!=expected_version:
            raise ValueError('Sandbox source changed during execution')
        validate(fresh,fresh_job,fresh_decision,report,git)
        c.execute('INSERT INTO engineering_sandbox_runs VALUES(?,?,?,?,?,?,?)',
                  (pid,jid,expected_version+1,pr.canonical(snapshot),digest,actor,vf.utc_now()))
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                  (actor,pid,'engineering_sandbox_replay','allowed'))
        c.commit()
    except Exception:
        c.rollback();raise
    return dict(version=expected_version+1,digest=digest,gate=report['gate'],git=git,
                selected=context['selected'],selection_digest=context['selection_digest'],**FLAGS)


def view(c,db_path,pid,jid):
    result=dict(project_id=pid,job_id=jid,state='BLOCK',latest_version=0,source_digest=None,
                receipt=None,**FLAGS)
    row=latest(c,pid,jid)
    if row:
        result.update(latest_version=row['version'],state='STALE')
        try:
            snapshot=json.loads(row['snapshot'])
            if pp.digest(snapshot)!=row['digest'] or snapshot['actor']!=row['actor']:
                raise ValueError('Invalid sandbox receipt')
        except (ValueError,TypeError,KeyError):
            result['state']='INVALID';return result
    try:
        context,job,decision=current(c,db_path,pid,jid)
        result['source_digest']=pp.digest(context)
        if not row:
            result['state']='AWAITING_EXPLICIT_SANDBOX'
        elif snapshot['source']==context:
            try:
                validate(context,job,decision,snapshot['report'],snapshot['git'])
            except (ValueError,TypeError,KeyError,AttributeError,PermissionError):
                result['state']='INVALID';return result
            report=snapshot['report']
            result.update(state='PASS' if report['gate']=='PASS' else 'BLOCK',
                          receipt=dict(version=row['version'],digest=row['digest'],actor=row['actor'],
                              selected=context['selected'],selection_digest=context['selection_digest'],
                              git=snapshot['git'],gate=report['gate'],lanes={
                                  k:dict(status=v['status'],sha256=v.get('sha256'),
                                         test_count=sum(s.get('test_count') or 0 for s in v.get('steps',[])))
                                  for k,v in report['lanes'].items()}))
    except (ValueError,KeyError,TypeError,AttributeError,PermissionError,sqlite3.Error,OSError):
        pass
    return result
