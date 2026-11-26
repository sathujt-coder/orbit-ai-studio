"""Test-only coherent SQLite and pristine Git baseline snapshots.

Never initialize a missing source workspace or rewrite evidence to fit a copy.
Production workspace validation is used before and after copying.
"""
from contextlib import closing
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import stat

import project_git_workspace as ws


def database_path(c):
    path=next((row[2] for row in c.execute('PRAGMA database_list') if row[1]=='main'),'')
    if not path:
        raise ValueError('Persistent source database required')
    return Path(path).resolve()


def workspace_snapshot(db,pid):
    baseline=ws.view(db,pid)
    if baseline['state']!='READY':
        raise ValueError('Source or copied Git workspace is not READY')
    repo=ws.location(db,pid)
    entries={}
    for folder,dirs,files in os.walk(repo,followlinks=False):
        for name in sorted(dirs+files):
            path=Path(folder)/name
            info=path.lstat()
            rel=path.relative_to(repo).as_posix()
            if stat.S_ISDIR(info.st_mode):
                entries[rel]=('directory',stat.S_IMODE(info.st_mode))
            elif stat.S_ISREG(info.st_mode) and info.st_nlink==1:
                entries[rel]=('file',stat.S_IMODE(info.st_mode),hashlib.sha256(path.read_bytes()).hexdigest())
            else:
                raise ValueError('Unsafe workspace snapshot entry')
    return dict(baseline=baseline,entries=entries)


def capture(c,pid,evidence):
    return dict(workspace=workspace_snapshot(database_path(c),pid),evidence=evidence(c,pid))


def copy_project_snapshot(c,destination,pid,evidence):
    """Copy exactly one project's Git workspace and the SQLite backup.

    Caller owns a fresh private temporary directory. Source state is checked
    again after the copy; no source metadata, refs or receipts are changed.
    """
    source=database_path(c)
    destination=Path(destination).resolve()
    target=ws.location(destination,pid)
    if c.in_transaction:
        raise ValueError('Snapshot requires an idle source connection')
    if destination==source or os.path.lexists(destination) or os.path.lexists(target.parent):
        raise ValueError('Snapshot destination must be new')
    before=capture(c,pid,evidence)
    with closing(sqlite3.connect(destination)) as dest:
        dest.row_factory=sqlite3.Row
        c.backup(dest)
        if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Copied SQLite integrity failure')
        if dest.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Copied SQLite foreign key failure')
        target.parent.mkdir(mode=0o700)
        # Do not follow unexpected symlinks; validation rejects them.
        shutil.copytree(ws.location(source,pid),target,symlinks=True)
        copied=capture(dest,pid,evidence)
        if copied!=before or capture(c,pid,evidence)!=before:
            raise ValueError('SQLite/Git/evidence snapshot mismatch')
    return before
