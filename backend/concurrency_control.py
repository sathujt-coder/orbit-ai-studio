"""P5.5: process-local bounded admission for every real server inference."""
from collections import Counter, deque
from contextlib import contextmanager
import hashlib
import os
import threading
import time
from urllib.parse import urlsplit
import model_provider as mp

def policy(env):
    def integer(key,default,minimum,maximum):
        try:n=int(env.get(key,str(default)))
        except (ValueError,TypeError):raise ValueError('Invalid '+key) from None
        if not minimum<=n<=maximum:raise ValueError('Invalid '+key)
        return n
    p={'workers':integer('ORBIT_QUEUE_WORKERS',1,1,8),
       'global_limit':integer('ORBIT_INFERENCE_GLOBAL',1,1,24),
       'endpoint_limit':integer('ORBIT_INFERENCE_ENDPOINT',1,1,24),
       'model_limit':integer('ORBIT_INFERENCE_MODEL',1,1,24),
       'project_limit':integer('ORBIT_INFERENCE_PROJECT',1,1,24),
       'max_waiters':integer('ORBIT_INFERENCE_WAITERS',32,0,128),
       'wait_seconds':integer('ORBIT_INFERENCE_WAIT_SECONDS',30,0,600)}
    if any(p[x]>p['global_limit'] for x in ('endpoint_limit','model_limit','project_limit')):
        raise ValueError('Scoped inference limits cannot exceed global limit')
    return p

def endpoint(lane):
    u=urlsplit(lane.base_url)
    host=(u.hostname or '').lower().rstrip('.')
    if host in ('localhost','127.0.0.1','::1'):host='loopback'
    # Ignore provider, API path and credential to avoid accidental separate pools
    # for aliases on the same origin. DNS aliases outside loopback are not resolved.
    port=u.port or (443 if u.scheme=='https' else 80)
    return hashlib.sha256((u.scheme+'|'+host+'|'+str(port)).encode()).hexdigest()

class Limiter:
    def __init__(self,env=None):
        self.policy=policy(os.environ if env is None else env)
        self.cv=threading.Condition()
        self.active=Counter()
        self.waiters=deque()
        self.total=0
        self.peak=0
        self.peak_waiters=0
        self.counts=Counter()
        self.closed=False

    def keys(self,lane,project):
        e=endpoint(lane)
        return (('endpoint',e),('model',(e,lane.model)),('project',project or '__system__'))

    def fits(self,keys):
        return self.total<self.policy['global_limit'] and all(self.active[k]<self.policy[k[0]+'_limit'] for k in keys)

    def reject(self,reason):
        self.counts[reason]+=1
        raise mp.ConcurrencyError('Inference admission refused: '+reason)

    @contextmanager
    def acquire(self,lane,project=None):
        if lane.provider=='demo':
            yield
            return
        keys=self.keys(lane,project)
        ticket=object()
        started=time.monotonic()
        with self.cv:
            if self.closed:self.reject('closed')
            # FIFO among eligible waiters: a saturated endpoint cannot block
            # unrelated endpoints while spare global slots exist.
            immediate=self.fits(keys) and not any(self.fits(k) for _,k in self.waiters)
            if not immediate:
                if self.policy['wait_seconds']==0:self.reject('busy')
                if len(self.waiters)>=self.policy['max_waiters']:self.reject('wait_queue_full')
                self.waiters.append((ticket,keys))
                self.counts['waited']+=1
                self.peak_waiters=max(self.peak_waiters,len(self.waiters))
                deadline=started+self.policy['wait_seconds']
                try:
                    while True:
                        if self.closed:self.reject('closed')
                        left=deadline-time.monotonic()
                        if left<=0:self.reject('wait_timeout')
                        first=next((t for t,k in self.waiters if self.fits(k)),None)
                        if first is ticket:break
                        self.cv.wait(left)
                finally:
                    self.waiters.remove((ticket,keys))
                    self.cv.notify_all()
            self.total+=1
            self.peak=max(self.peak,self.total)
            for k in keys:self.active[k]+=1
            self.counts['acquired']+=1
            self.cv.notify_all()
        try:yield
        finally:
            with self.cv:
                self.total-=1
                for k in keys:
                    self.active[k]-=1
                    if self.active[k]==0:del self.active[k]
                self.counts['released']+=1
                self.cv.notify_all()

    def close(self):
        with self.cv:
            self.closed=True
            self.cv.notify_all()

    def snapshot(self):
        with self.cv:
            return {'schema':'orbit.concurrency.v1','policy':dict(self.policy),'active':self.total,'waiting':len(self.waiters),
                    'peak_active':self.peak,'peak_waiting':self.peak_waiters,'closed':self.closed,
                    'counts':{k:self.counts[k] for k in ('acquired','released','waited','busy','wait_queue_full','wait_timeout','closed')},
                    'active_scopes':{kind:sum(1 for k in self.active if k[0]==kind) for kind in ('endpoint','model','project')},
                    'note':'Process-local client inference slots, not provider-side GPU execution; resets on restart.'}
