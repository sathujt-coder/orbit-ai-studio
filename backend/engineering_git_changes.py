"""P6.4d.1: read-only, exact Git tree change detection for reviewed candidates.

The current project baseline is empty, not an earlier delivered product.
A/B is a comparison of independent candidates, not chronological history.
No candidate execution, remote Git operation or changes to the project repo.
"""
import hashlib
import shutil
import sqlite3
import tempfile
from pathlib import Path

import engineering_sandbox as sb
import engineering_quality as quality
import project_git_workspace as ws
import project_planning as pp
import verification_factory as vf

FLAGS=sb.FLAGS
COMPARISONS=('baseline_to_A','baseline_to_B','A_to_B')

def file_map(proposal):
    out={}
    for f in proposal['files']:
        path=f['path'];raw=f['content'].encode('utf-8')
        sha=hashlib.sha256(raw).hexdigest()
        if path in out or sha!=f['sha256']:raise ValueError('Invalid file manifest')
        out[path]=dict(blob=ws.object_id('blob',raw),sha256=sha)
    return out

def read_tree(repo,commit,expected):
    actual={}
    for item in ws.git(repo,'ls-tree','-rz',commit).split(b'\0'):
        if not item:continue
        header,path=item.split(b'\t',1);mode,kind,oid=header.decode('ascii').split(' ')
        path=path.decode('utf-8')
        if mode!='100644' or kind!='blob' or path in actual or path not in expected:
            raise ValueError('Unexpected Git tree entry')
        raw=ws.git(repo,'cat-file','blob',oid)
        if ws.object_id('blob',raw)!=oid:raise ValueError('Git blob identity mismatch')
        actual[path]=dict(blob=oid,sha256=hashlib.sha256(raw).hexdigest())
    if actual!=expected:raise ValueError('Git tree manifest mismatch')
    return actual

def expected_changes(before,after):
    changes=[]
    for path in sorted(set(before)|set(after)):
        old=before.get(path);new=after.get(path)
        if old==new:continue
        status='ADDED' if old is None else 'DELETED' if new is None else 'MODIFIED'
        changes.append(dict(path=path,status=status,before=old,after=new))
    return changes

def compare(repo,left,right,before,after):
    # No rename detection or textconv: paths and exact blob bytes are authority.
    raw=ws.git(repo,'diff-tree','--no-commit-id','--no-renames','--name-status','-r','-z',left,right)
    fields=raw.split(b'\0')
    if fields.pop()!=b'' or len(fields)%2:raise ValueError('Invalid Git diff protocol')
    statuses={b'A':'ADDED',b'D':'DELETED',b'M':'MODIFIED'}
    observed={}
    for status,path in zip(fields[::2],fields[1::2]):
        name=path.decode('utf-8')
        if status not in statuses or name in observed:raise ValueError('Unsupported Git change')
        observed[name]=statuses[status]
    changes=expected_changes(before,after)
    if observed!={x['path']:x['status'] for x in changes}:raise ValueError('Git diff/manifest disagreement')
    counts={s:sum(x['status']==s for x in changes) for s in ('ADDED','MODIFIED','DELETED')}
    return dict(from_commit=left,to_commit=right,changes=changes,counts=counts,
                unchanged_count=sum(before.get(p)==after[p] for p in after if p in before))

def analyze(db,pid,jid,base,proposals,expected_git):
    if set(proposals)!=set(expected_git) or set(proposals)!={'A','B'}:
        raise ValueError('Both exact candidate manifests required')
    repo=ws.location(db,pid)
    if ws.inspect(repo,pid)!=base:raise ValueError('Git baseline changed')
    with tempfile.TemporaryDirectory(prefix='orbit-git-change-') as tmp:
        clone=Path(tmp)/'candidate.git'
        shutil.copytree(repo,clone)
        if ws.inspect(clone,pid)!=base:raise ValueError('Copied baseline changed')
        maps={'baseline':read_tree(clone,base,{})}
        commits={'baseline':base}
        for lane in ('A','B'):
            proposal=proposals[lane]
            meta,objects=sb.git_objects(proposal,base,jid,lane)
            if meta!=expected_git[lane]:raise ValueError('Candidate Git receipt mismatch')
            for oid,(kind,raw) in objects.items():
                if ws.git(clone,'hash-object','-w','-t',kind,'--stdin',data=raw).decode().strip()!=oid:
                    raise ValueError('Git object identity mismatch')
            commits[lane]=meta['commit']
            if (ws.git(clone,'rev-parse',meta['commit']+'^').decode().strip()!=base
                or ws.git(clone,'rev-parse',meta['commit']+'^{tree}').decode().strip()!=meta['tree']):
                raise ValueError('Candidate Git parent/tree mismatch')
            maps[lane]=read_tree(clone,meta['commit'],file_map(proposal))
        result={name:compare(clone,commits[left],commits[right],maps[left],maps[right])
                for name,left,right in (('baseline_to_A','baseline','A'),('baseline_to_B','baseline','B'),('A_to_B','A','B'))}
    if ws.inspect(repo,pid)!=base:raise ValueError('Git baseline changed during comparison')
    return result

def view(c,db,pid,jid):
    out=dict(schema='orbit.git-change-evidence.v1',project_id=pid,job_id=jid,state='BLOCK',
             source=None,comparisons={},selected_comparison=None,
             baseline_kind='empty_project_baseline',comparison_kind='independent_candidates',
             rename_detection=False,scope='development_evidence_only',**FLAGS)
    try:
        quality.lineage(c,pid,jid)
        context,job,_=sb.current(c,db,pid,jid)
        current=sb.view(c,db,pid,jid)
        receipt=current['receipt']
        lane=context['selected'];src=context['source']
        if (current['state']!='PASS' or not receipt or lane not in ('A','B')
            or receipt['selected']!=lane or receipt['selection_digest']!=context['selection_digest']
            or src['project_id']!=pid or src['job_id']!=jid
            or current['source_digest']!=pp.digest(context)):
            raise ValueError('Current sandbox receipt required')
        proposals=vf.safe_job(job)
        git=receipt['git']
        for k in ('A','B'):
            if (git[k]['parent']!=src['base_commit']
                or git[k]['source_sha256']!=src['bound_evidence']['candidates'][k]['digest']
                or git[k]['source_sha256']!=receipt['lanes'][k]['sha256']):
                raise ValueError('Candidate source mismatch')
        comparisons=analyze(db,pid,jid,src['base_commit'],proposals,git)
        out.update(state='GIT_CHANGE_EVIDENCE_READY',source=dict(project_id=pid,job_id=jid,
            workspace_id=src['workspace_id'],base_commit=src['base_commit'],
            qa_source_digest=src['qa_source_digest'],selection_digest=context['selection_digest'],
            sandbox_digest=receipt['digest'],sandbox_source_digest=current['source_digest'],
            selected=lane,git=git),comparisons=comparisons,selected_comparison='baseline_to_'+lane)
    except (ValueError,TypeError,KeyError,AttributeError,PermissionError,sqlite3.Error,OSError,UnicodeError):
        pass
    out['evidence_digest']=pp.digest(out)
    return out
