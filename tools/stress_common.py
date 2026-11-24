"""Small shared helpers for isolated P5.9 load tests."""
import json,os,math,time
from pathlib import Path

def require(condition,reason):
    if not condition:raise RuntimeError(reason)

def private_environment(settings):
    # Never use inherited production database, credentials, provider policy or endpoints.
    for k in list(os.environ):
        if k.startswith(('AI_','ORBIT_')):os.environ.pop(k)
    os.environ.update(settings)
    os.umask(0o077)

class Evidence:
    def __init__(self,path,schema,profile):
        self.path=Path(path);self.data={'schema':schema,'profile':profile,'gate':'RUNNING','started_at':int(time.time())}
        with self.path.open('x',encoding='utf-8') as f:json.dump(self.data,f,indent=2)
    def save(self):
        tmp=self.path.with_name(self.path.name+'.tmp')
        with tmp.open('w',encoding='utf-8') as f:json.dump(self.data,f,indent=2,allow_nan=False)
        os.replace(tmp,self.path)
    def finish(self,ok):
        self.data.update(gate='PASS' if ok else 'BLOCK',finished_at=int(time.time()))
        self.save();print(json.dumps(self.data,indent=2))
        return 0 if ok else 2

def latency(values):
    if not values:return {'count':0,'p50_ms':None,'p95_ms':None,'max_ms':None}
    v=sorted(values)
    return {'count':len(v),'p50_ms':v[max(0,math.ceil(.50*len(v))-1)],'p95_ms':v[max(0,math.ceil(.95*len(v))-1)],'max_ms':v[-1]}

def integrity(c):
    return {'quick_check':c.execute('PRAGMA quick_check').fetchone()[0],
            'foreign_key_violations':len(c.execute('PRAGMA foreign_key_check').fetchall())}
