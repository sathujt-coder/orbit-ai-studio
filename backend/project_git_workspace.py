"""P6.3e: explicit, project-local Git baseline. No candidate writes or execution."""
import configparser
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile

BRANCH = 'refs/heads/orbit-base'
CONFIRMATION = 'INITIALIZE PROJECT GIT WORKSPACE'
FLAGS = dict(automatic_dispatch=False, execution_authorized=False,
             merge_authorized=False, production_release_authorized=False,
             remote_writes_authorized=False)


def identity(pid):
    if not isinstance(pid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',pid):
        raise ValueError('Invalid workspace project identity')
    return hashlib.sha256(('orbit.project.git.v1:'+pid).encode()).hexdigest()


def location(db_path,pid):
    database=Path(db_path).resolve()
    return database.with_name(database.name+'.git-workspaces')/identity(pid)


def private_dir(path):
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise ValueError('Workspace directory is not private')


def git(repo,*args,data=None):
    executable=shutil.which('git')
    if not executable:
        raise ValueError('Local Git is unavailable')
    # Do not inherit credentials, Git configuration, external object directories,
    # alternate indexes, or protocol helpers from the agent/server environment.
    env=dict(PATH=os.defpath,LANG='C',LC_ALL='C',HOME=str(repo.parent),
             GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,
             GIT_TERMINAL_PROMPT='0',GIT_ALLOW_PROTOCOL='',GIT_OPTIONAL_LOCKS='0')
    try:
        result=subprocess.run([executable,'--git-dir='+str(repo),*args],
                              input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              cwd=repo.parent,env=env,timeout=10,check=True)
    except (subprocess.SubprocessError,OSError):
        raise ValueError('Local Git workspace operation failed') from None
    return result.stdout


def object_id(kind,data):
    return hashlib.sha1((kind+' '+str(len(data))).encode()+b'\0'+data).hexdigest()


def baseline(pid):
    empty=object_id('tree',b'')
    raw=('tree '+empty+'\nauthor ORBIT Workspace <workspace@orbit.invalid> 0 +0000\n'
         'committer ORBIT Workspace <workspace@orbit.invalid> 0 +0000\n\n'
         'ORBIT project workspace '+identity(pid)+'\n').encode()
    return empty,raw,object_id('commit',raw)


def inspect(repo,pid):
    private_dir(repo.parent)
    private_dir(repo)
    # P6.3e has only a pristine baseline. Reject unexpected files, symbolic
    # links, hard links, hooks, alternates, remotes or ref changes before Git.
    empty,raw,commit=baseline(pid)
    allowed_dirs={'objects','objects/info','objects/pack','refs','refs/heads','refs/tags',
                  'objects/'+empty[:2],'objects/'+commit[:2]}
    allowed_files={'HEAD','config',BRANCH,'objects/'+empty[:2]+'/'+empty[2:],
                   'objects/'+commit[:2]+'/'+commit[2:]}
    found=set()
    for folder,dirs,files in os.walk(repo,followlinks=False):
        for name in dirs+files:
            path=Path(folder)/name
            rel=path.relative_to(repo).as_posix()
            info=path.lstat()
            if rel in allowed_dirs and stat.S_ISDIR(info.st_mode):
                continue
            if (rel in allowed_files and stat.S_ISREG(info.st_mode)
                    and info.st_nlink==1 and info.st_size<=4096):
                found.add(rel)
                continue
            raise ValueError('Unexpected workspace content')
    if found!=allowed_files:
        raise ValueError('Workspace baseline is incomplete')
    cfg=configparser.ConfigParser(interpolation=None)
    cfg.read_string((repo/'config').read_text(encoding='utf-8'))
    if (cfg.defaults() or cfg.sections()!=['core']
            or set(cfg['core'])!={'repositoryformatversion','filemode','bare'}
            or cfg['core']['repositoryformatversion']!='0'
            or cfg['core']['bare']!='true' or cfg['core']['filemode'] not in ('true','false')):
        raise ValueError('Unexpected workspace Git configuration')
    if (repo/'HEAD').read_bytes()!=('ref: '+BRANCH+'\n').encode():
        raise ValueError('Unexpected workspace HEAD')
    if (repo/BRANCH).read_bytes()!=(commit+'\n').encode():
        raise ValueError('Workspace project baseline mismatch')
    if git(repo,'cat-file','commit',commit)!=raw or git(repo,'cat-file','tree',empty)!=b'':
        raise ValueError('Workspace baseline object mismatch')
    return commit


def view(db_path,pid):
    repo=location(db_path,pid)
    result=dict(project_id=pid,workspace_id=identity(pid),state='UNINITIALIZED',
                base_commit=None,branch='orbit-base',mode='local_bare_baseline',**FLAGS)
    try:
        if os.path.lexists(repo.parent):
            private_dir(repo.parent)
        if os.path.lexists(repo):
            result.update(state='READY',base_commit=inspect(repo,pid))
    except (ValueError,OSError,configparser.Error,UnicodeError):
        result['state']='BLOCK'
    return result


def initialize(db_path,pid,body):
    if body!={'confirmation':CONFIRMATION}:
        raise ValueError('Explicit workspace initialization confirmation required')
    repo=location(db_path,pid)
    if os.path.lexists(repo):
        if view(db_path,pid)['state']=='READY':
            return view(db_path,pid)  # Idempotent explicit retry; never overwrite.
        raise ValueError('Existing workspace is invalid; automatic replacement prohibited')
    try:
        repo.parent.mkdir(mode=0o700,exist_ok=True)
        private_dir(repo.parent)
        # Initialize and verify the complete repo before publishing its directory.
        stage=Path(tempfile.mkdtemp(prefix='.initializing-',dir=repo.parent))
        try:
            git(stage,'init','--bare','--template=','--object-format=sha1','--initial-branch=orbit-base')
            empty,raw,commit=baseline(pid)
            if git(stage,'hash-object','-w','-t','tree','--stdin',data=b'').decode().strip()!=empty:
                raise ValueError('Unexpected empty tree identity')
            if git(stage,'hash-object','-w','-t','commit','--stdin',data=raw).decode().strip()!=commit:
                raise ValueError('Unexpected workspace commit identity')
            git(stage,'update-ref',BRANCH,commit,'0'*40)
            inspect(stage,pid)
            if os.path.lexists(repo):
                raise ValueError('Workspace already exists')
            stage.rename(repo)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    except (OSError,configparser.Error,UnicodeError):
        raise ValueError('Workspace initialization failed closed') from None
    return view(db_path,pid)
