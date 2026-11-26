"""P6.3h: explicit Git-bound draft export; never merge or deploy.

The OS operator supplies a separately authorized token. No HTTP write route.
A durable reservation precedes remote writes; ambiguous outcomes block retries.
"""
import base64
import hashlib
import json
import re
import sqlite3
import tempfile
from urllib.parse import quote

import engineering_sandbox as sb
import project_planning as pp
import product_requirements as pr
import project_git_workspace as ws
import verification_factory as vf
from github_pr import GitHubClient, VALID_REPO
from coding_factory import safe_path

FLAGS=sb.FLAGS
SHA=re.compile(r'[0-9a-f]{40}\Z')
BASE=re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z')


def ensure_schema(c):
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_draft_exports(
        project_id TEXT NOT NULL REFERENCES projects(id),
        job_id TEXT NOT NULL REFERENCES studio_coding_bindings(job_id),
        plan TEXT NOT NULL, digest TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS engineering_draft_results(
        project_id TEXT NOT NULL, job_id TEXT NOT NULL, result TEXT NOT NULL,digest TEXT NOT NULL,
        PRIMARY KEY(project_id,job_id),
        FOREIGN KEY(project_id,job_id) REFERENCES engineering_draft_exports(project_id,job_id))""")
    for table in ('engineering_draft_exports','engineering_draft_results'):
        for op in ('UPDATE','DELETE'):
            c.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()}
                BEFORE {op} ON {table}
                BEGIN SELECT RAISE(ABORT,'Immutable draft export evidence'); END""")
        c.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table}
            WHEN EXISTS(SELECT 1 FROM {table} WHERE project_id=NEW.project_id AND job_id=NEW.job_id)
            BEGIN SELECT RAISE(ABORT,'Draft export already reserved'); END""")


def current(c,db,pid,jid):
    context,job,decision=sb.current(c,db,pid,jid)
    row=sb.latest(c,pid,jid)
    if not row:raise ValueError('Current passing Git sandbox receipt required')
    snapshot=json.loads(row['snapshot'])
    if (pp.digest(snapshot)!=row['digest'] or snapshot['source']!=context
        or snapshot['actor']!=row['actor'] or snapshot['report']['gate']!='PASS'):
        raise ValueError('Stale or invalid Git sandbox receipt')
    sb.validate(context,job,decision,snapshot['report'],snapshot['git'])
    lane=context['selected']
    return dict(project_id=pid,job_id=jid,selected=lane,
                selection_digest=context['selection_digest'],sandbox_digest=row['digest'],
                sandbox_version=row['version'],sandbox_source_digest=pp.digest(context),
                git=snapshot['git'][lane],**FLAGS),vf.safe_job(job)[lane]


def prepare(c,db,pid,jid,repo,base,base_sha):
    if (not isinstance(repo,str) or not VALID_REPO.fullmatch(repo) or '..' in repo or any(x=='.' for x in repo.split('/'))
        or not isinstance(base,str) or not BASE.fullmatch(base) or '..' in base
        or '//' in base or base.endswith(('/', '.')) or any(x.startswith('.') or x.endswith('.lock') for x in base.split('/'))
        or not isinstance(base_sha,str) or not SHA.fullmatch(base_sha)):
        raise ValueError('Explicit safe repository, base branch and base commit required')
    source,proposal=current(c,db,pid,jid)
    prefix='agent-proposals/'+jid
    lane=source['selected']
    with tempfile.TemporaryDirectory(prefix='orbit-draft-') as work:
        root,git=sb.materialize(db,pid,jid,lane,proposal,source['git']['parent'],work)
        if git!=source['git']:raise ValueError('Reconstructed selected Git commit mismatch')
        files=[]
        for f in proposal['files']:
            path=safe_path(f['path'])
            raw=(root/path).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=f['sha256']:raise ValueError('Export source mismatch')
            files.append(dict(path=prefix+'/candidate-'+lane+'/'+path,content=raw.decode('utf-8')))
    # Evidence only; no raw reviews, prompts, operator rationale or sandbox output.
    evidence=dict(schema='orbit.engineering-draft-evidence.v1',source=source,
                  target=dict(repo=repo,base=base,base_sha=base_sha),
                  notice='Draft review only; no production authorization.')
    files.append(dict(path=prefix+'/VERIFICATION.json',content=pr.canonical(evidence)+'\n'))
    plan=dict(schema='orbit.engineering-draft-plan.v1',source=source,target=evidence['target'],
              files=[dict(path=f['path'],sha256=hashlib.sha256(f['content'].encode()).hexdigest(),
                          blob=ws.object_id('blob',f['content'].encode())) for f in files],**FLAGS)
    return plan,files


def require_sha(value):
    if not isinstance(value,str) or not SHA.fullmatch(value):raise ValueError('Invalid remote Git object')
    return value


class DraftClient(GitHubClient):
    def publish(self,plan,files,recheck):
        target=plan['target'];source=plan['source'];jid=source['job_id'];lane=source['selected']
        api='/repos/'+target['repo'];prefix='agent-proposals/'+jid
        branch='orbit/engineering-'+jid+'-'+pp.digest(plan)[:16]
        base_route=api+'/branches/'+quote(target['base'],safe='')
        def base():
            if self.request('GET',base_route)['commit']['sha']!=target['base_sha']:
                raise ValueError('Remote base changed')
        def tree_entries(sha):
            data=self.request('GET',api+'/git/trees/'+require_sha(sha)+'?recursive=1')
            if data.get('truncated') is not False:raise ValueError('Remote tree incomplete')
            items=data['tree']
            entries={x['path']:(x['mode'],x['type'],x['sha']) for x in items if x['type']!='tree'}
            if len(entries)!=sum(x['type']!='tree' for x in items):raise ValueError('Duplicate remote tree path')
            return entries
        # Validate the entire outbound bundle before any network mutation.
        if len(files)!=len(plan['files']) or len({f['path'] for f in files})!=len(files):
            raise ValueError('Invalid export files')
        for f,d in zip(files,plan['files']):
            path=f['path'];raw=f['content'].encode()
            if path!=prefix+'/VERIFICATION.json':
                start=prefix+'/candidate-'+lane+'/'
                if not path.startswith(start):raise ValueError('Unselected or unsafe path')
                safe_path(path[len(start):])
            if d!=dict(path=path,sha256=hashlib.sha256(raw).hexdigest(),blob=ws.object_id('blob',raw)):
                raise ValueError('Export payload mismatch')
        base()
        commit=self.request('GET',api+'/git/commits/'+target['base_sha'])
        if commit.get('sha')!=target['base_sha']:raise ValueError('Remote commit mismatch')
        base_tree=require_sha(commit['tree']['sha']);before=tree_entries(base_tree)
        if any(p==prefix or p.startswith(prefix+'/') or prefix.startswith(p+'/') for p in before):
            raise ValueError('Remote proposal prefix already occupied')
        recheck()
        entries=[]
        for f,d in zip(files,plan['files']):
            blob=self.request('POST',api+'/git/blobs',dict(content=base64.b64encode(f['content'].encode()).decode(),encoding='base64'))
            if blob.get('sha')!=d['blob']:raise ValueError('Remote blob mismatch')
            entries.append(dict(path=f['path'],mode='100644',type='blob',sha=d['blob']))
        tree=require_sha(self.request('POST',api+'/git/trees',dict(base_tree=base_tree,tree=entries))['sha'])
        expected=dict(before);expected.update({e['path']:(e['mode'],e['type'],e['sha']) for e in entries})
        if tree_entries(tree)!=expected:raise ValueError('Unexpected remote tree changes')
        commit=self.request('POST',api+'/git/commits',dict(message='ORBIT verified candidate '+jid,tree=tree,parents=[target['base_sha']]))
        sha=require_sha(commit['sha'])
        if commit['tree']['sha']!=tree or [p['sha'] for p in commit['parents']]!=[target['base_sha']]:
            raise ValueError('Unexpected remote commit')
        base();recheck()
        ref='refs/heads/'+branch
        created=self.request('POST',api+'/git/refs',dict(ref=ref,sha=sha))
        if created.get('ref')!=ref or created['object']['sha']!=sha:raise ValueError('Unexpected remote ref')
        base();recheck()
        pull=self.request('POST',api+'/pulls',dict(title='ORBIT verified candidate '+jid,
            head=branch,base=target['base'],draft=True,
            body='Selected DEV-'+lane+'; Git-bound sandbox evidence '+source['sandbox_digest']+
            '. Review only. No automatic merge or deployment.'))
        number=pull['number']
        if (type(number) is not int or number<=0 or pull.get('draft') is not True
            or pull.get('state')!='open' or pull.get('merged_at') is not None
            or pull['head']['ref']!=branch or pull['head']['sha']!=sha
            or pull['base']['ref']!=target['base'] or pull['base']['sha']!=target['base_sha']
            or pull['head']['repo']['full_name'].lower()!=target['repo'].lower()
            or pull['base']['repo']['full_name'].lower()!=target['repo'].lower()
            or pull['html_url'].lower()!=('https://github.com/'+target['repo']+'/pull/'+str(number)).lower()):
            raise ValueError('Unexpected draft PR response')
        return dict(repo=target['repo'],base=target['base'],base_sha=target['base_sha'],
                    branch=branch,head_sha=sha,tree_sha=tree,number=number,url=pull['html_url'],draft=True)


def publish(c,db,pid,jid,actor,repo,base,base_sha,expected_digest,confirmation,client):
    if confirmation!='CREATE ENGINEERING DRAFT '+jid+' '+repo+' '+expected_digest:
        raise PermissionError('Exact target-bound confirmation required')
    if c.in_transaction:raise ValueError('Idle database connection required')
    c.execute('BEGIN IMMEDIATE')
    try:
        pp.check_role(c,pid,actor,'publish')
        plan,files=prepare(c,db,pid,jid,repo,base,base_sha)
        if pp.digest(plan)!=expected_digest:raise ValueError('Stale export plan')
        if (c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='code_pr_exports'").fetchone()
            and c.execute('SELECT 1 FROM code_pr_exports WHERE job_id=?',(jid,)).fetchone()):
            raise ValueError('Historical legacy export requires manual reconciliation')
        if c.execute('SELECT 1 FROM engineering_draft_exports WHERE project_id=? AND job_id=?',(pid,jid)).fetchone():
            raise ValueError('Draft export already reserved; manual reconciliation required')
        c.execute('INSERT INTO engineering_draft_exports VALUES(?,?,?,?,?,?)',
                  (pid,jid,pr.canonical(plan),expected_digest,actor,vf.utc_now()))
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                  (actor,pid,'engineering_draft_reserve','allowed'))
        c.commit()
    except Exception:
        c.rollback();raise
    # Reservation survives crashes and remote failures. No automatic retry or deletion.
    c.execute('BEGIN IMMEDIATE')
    def recheck():
        pp.check_role(c,pid,actor,'publish')
        if prepare(c,db,pid,jid,repo,base,base_sha)!=(plan,files):
            raise ValueError('Draft source changed during publication')
    try:
        recheck()
        remote=client.publish(plan,files,recheck)
        recheck()
        result=dict(status='CREATED_DRAFT',plan_digest=expected_digest,remote=remote,**FLAGS)
        c.execute('INSERT INTO engineering_draft_results VALUES(?,?,?,?)',
                  (pid,jid,pr.canonical(result),pp.digest(result)))
        c.execute("INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,strftime('%s','now'))",
                  (actor,pid,'engineering_draft_created','allowed'))
        c.commit()
        return result
    except Exception:
        c.rollback()
        # Pending is intentionally fail-closed even if a remote PR exists.
        raise


def view(c,db,pid,jid):
    out=dict(project_id=pid,job_id=jid,state='BLOCK',receipt=None,**FLAGS)
    row=c.execute('SELECT * FROM engineering_draft_exports WHERE project_id=? AND job_id=?',(pid,jid)).fetchone()
    try:
        source,_=current(c,db,pid,jid)
        if not row:
            out.update(state='AWAITING_EXPLICIT_DRAFT',source=source)
            return out
        plan=json.loads(row['plan'])
        if pp.digest(plan)!=row['digest']:raise ValueError('Invalid draft reservation')
        result=c.execute('SELECT * FROM engineering_draft_results WHERE project_id=? AND job_id=?',(pid,jid)).fetchone()
        if not result:
            out.update(state='RECONCILE_REQUIRED',plan_digest=row['digest']);return out
        receipt=json.loads(result['result'])
        if pp.digest(receipt)!=result['digest'] or receipt['plan_digest']!=row['digest']:
            raise ValueError('Invalid draft result')
        out.update(state='CREATED_DRAFT' if plan['source']==source else 'STALE',
                   receipt=receipt,plan_digest=row['digest'])
    except (ValueError,TypeError,KeyError,AttributeError,PermissionError,sqlite3.Error,OSError):
        if row:out['state']='STALE_OR_INVALID'
    return out
