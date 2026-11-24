#!/usr/bin/env python3
"""Create an online SQLite snapshot or restore to a NEW local file; never overwrite."""
import argparse,os,sqlite3
from pathlib import Path
def copy_database(source,destination,restore=False):
    source=Path(source).resolve(strict=True)
    destination=Path(destination).absolute()
    if not source.is_file():raise ValueError('Source must be a file')
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    os.close(fd)
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Integrity check failed')
            if restore and dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auth_sessions'").fetchone():
                dst.execute('DELETE FROM auth_sessions')
                dst.commit()
        return destination
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['backup','restore'])
    p.add_argument('source',type=Path)
    p.add_argument('destination',type=Path)
    a=p.parse_args()
    print(copy_database(a.source,a.destination,a.mode=='restore'))
if __name__=='__main__':main()
