"""P5.3: dependency-free resource telemetry and opt-in admission protection.

Metrics describe the backend process/OS/cgroup, not a remote inference server.
No arbitrary shell, container socket, remote probes or provider inference here.
"""
import json
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path,PurePosixPath
from urllib.parse import urlsplit
import urllib.request
import model_provider as mp

MIB=1024**2

def read(path):
    try:return Path(path).read_text()[:65536]
    except (OSError,UnicodeError):return ''

def nonnegative(value):
    try:
        if isinstance(value,bool):return None
        n=int(value)
        return n if 0<=n<=2**63-1 else None
    except (ValueError,TypeError,OverflowError):return None

def meminfo(text):
    result={}
    for line in text.splitlines():
        key,sep,value=line.partition(':')
        parts=value.split()
        if sep and len(parts)==2 and parts[1]=='kB':
            n=nonnegative(parts[0])
            if n is not None:result[key]=n*1024
    return result

def cgroup_dir(membership,mountinfo):
    member=next((line[3:] for line in membership.splitlines() if line.startswith('0::')),None)
    if member is None or not member.startswith('/'):return None
    # The only supported mount is the kernel's standard cgroup v2 filesystem.
    for line in mountinfo.splitlines():
        left,sep,right=line.partition(' - ')
        fields=left.split()
        if not sep or not right.startswith('cgroup2 ') or len(fields)<5 or fields[4]!='/sys/fs/cgroup':continue
        root=PurePosixPath(fields[3]);p=PurePosixPath(member)
        if '..' in p.parts or '..' in root.parts or '\\' in member or '\\' in fields[3]:return None
        try:relative=p.relative_to(root)
        except ValueError:
            # In a private cgroup namespace, '/' names the mounted group itself.
            if member=='/':relative=PurePosixPath('.')
            else:return None
        return Path('/sys/fs/cgroup').joinpath(*relative.parts)
    return None

def cgroup_limits(reader=read):
    directory=cgroup_dir(reader('/proc/self/cgroup'),reader('/proc/self/mountinfo'))
    if directory is None:return {'scope':'unavailable','memory_limit_bytes':None,'memory_current_bytes':None,'memory_headroom_bytes':None,'cpu_quota_cores':None}
    root=Path('/sys/fs/cgroup');p=directory
    limits=[];heads=[];quotas=[];valid=True
    current=nonnegative(reader(directory/'memory.current').strip())
    while True:
        cap=reader(p/'memory.max').strip()
        if cap and cap!='max':
            limit=nonnegative(cap);used=nonnegative(reader(p/'memory.current').strip())
            if limit is None or used is None:valid=False
            else:limits.append(limit);heads.append(max(0,limit-used))
        elif cap!='max' and p==directory and p!=root:valid=False
        cpu=reader(p/'cpu.max').split()
        if len(cpu)==2 and cpu[0]!='max':
            q=nonnegative(cpu[0]);period=nonnegative(cpu[1])
            if q is not None and period:quotas.append(q/period)
        if p==root:break
        p=p.parent
    return {'scope':'cgroup_v2' if valid else 'cgroup_v2_incomplete','memory_limit_bytes':min(limits) if limits else None,
            'memory_current_bytes':current,'memory_headroom_bytes':min(heads) if heads and valid else None,
            'cpu_quota_cores':min(quotas) if quotas else None}

def measure(reader=read,system=None):
    system=platform.system() if system is None else system
    try:cores=len(os.sched_getaffinity(0))
    except (AttributeError,OSError):cores=os.cpu_count()
    result={'platform':system,'scope':'backend_process','logical_cpu_count':cores,'effective_cpu_cores':cores,
            'host_memory_total_bytes':None,'host_memory_available_bytes':None,'effective_memory_available_bytes':None,
            'process_rss_bytes':None,'cgroup':{'scope':'unavailable','memory_limit_bytes':None,'memory_current_bytes':None,'memory_headroom_bytes':None,'cpu_quota_cores':None}}
    if system=='Linux':
        m=meminfo(reader('/proc/meminfo'));cg=cgroup_limits(reader)
        result.update(host_memory_total_bytes=m.get('MemTotal'),host_memory_available_bytes=m.get('MemAvailable'),
                      process_rss_bytes=meminfo(reader('/proc/self/status')).get('VmRSS'),cgroup=cg)
        if cg['cpu_quota_cores'] is not None:
            result['effective_cpu_cores']=min(cores,cg['cpu_quota_cores']) if cores else cg['cpu_quota_cores']
        if cg['scope']=='cgroup_v2':
            head=cg['memory_headroom_bytes'];host=m.get('MemAvailable')
            if host is not None:result['effective_memory_available_bytes']=min(host,head) if head is not None else host
    return result

def policy(env):
    mode=env.get('ORBIT_RESOURCE_MODE','observe')
    if mode not in ('observe','enforce'):raise ValueError('Invalid resource mode')
    def bounded(name,default,lo,hi):
        try:n=int(env.get(name,str(default)))
        except (ValueError,TypeError):raise ValueError('Invalid '+name) from None
        if not lo<=n<=hi:raise ValueError('Invalid '+name)
        return n
    return {'mode':mode,'min_free_mib':bounded('ORBIT_RESOURCE_MIN_FREE_MIB',128,1,1048576),
            'max_memory_percent':bounded('ORBIT_RESOURCE_MAX_MEMORY_PERCENT',95,50,100)}

def pressure(metrics,limits):
    available=metrics['effective_memory_available_bytes'];cg=metrics['cgroup']
    if available is None:return 'memory_telemetry_unavailable'
    if available<limits['min_free_mib']*MIB:return 'memory_headroom_low'
    # Use effective headroom relative to the smallest finite cgroup cap, conservatively.
    cap=cg['memory_limit_bytes'];head=cg['memory_headroom_bytes']
    if cap and head is not None and (cap-min(cap,head))*100>=cap*limits['max_memory_percent']:return 'cgroup_memory_pressure'
    total=metrics['host_memory_total_bytes'];free=metrics['host_memory_available_bytes']
    if total and free is not None and (total-min(total,free))*100>=total*limits['max_memory_percent']:return 'host_memory_pressure'
    return None

def gpu_snapshot():
    # Optional NVIDIA telemetry from a fixed executable/arguments; no shell or user input.
    executable=shutil.which('nvidia-smi')
    if not executable:return {'status':'unavailable','source':'nvidia-smi','devices':[]}
    try:
        result=subprocess.run([executable,'--query-gpu=index,memory.total,memory.used,utilization.gpu',
                               '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3,check=True)
        devices=[]
        for line in result.stdout[:16384].splitlines()[:32]:
            values=[nonnegative(x.strip()) for x in line.split(',')]
            if len(values)!=4 or any(x is None for x in values):continue
            index,total,used,util=values
            if total and used<=total and util<=100:
                devices.append({'index':index,'vram_total_bytes':total*MIB,'vram_used_bytes':used*MIB,'utilization_percent':util})
        return {'status':'available' if devices else 'unavailable','source':'nvidia-smi','devices':devices}
    except (OSError,subprocess.SubprocessError,UnicodeError):
        return {'status':'unavailable','source':'nvidia-smi','devices':[]}

class Manager:
    def __init__(self,env=None,measure_fn=measure):
        self.policy=policy(os.environ if env is None else env)
        self.measure_fn=measure_fn;self.lock=threading.Lock()
        self.previous=None;self.gpu_cache=None;self.gpu_at=0
        self.counts={'allowed':0,'blocked':0,'would_block':0,'reasons':{}}
    def admit(self,lane):
        if lane.provider=='demo':return
        reason=pressure(self.measure_fn(),self.policy)
        with self.lock:
            if reason:
                key='blocked' if self.policy['mode']=='enforce' else 'would_block'
                self.counts[key]+=1
                self.counts['reasons'][reason]=self.counts['reasons'].get(reason,0)+1
                if key=='blocked':raise mp.ResourceError('Resource admission blocked: '+reason)
            self.counts['allowed']+=1
    def snapshot(self,include_gpu=False):
        m=self.measure_fn();now=time.monotonic();cpu=time.process_time()
        with self.lock:
            previous=self.previous;self.previous=(now,cpu)
            m['process_cpu_percent']=None
            if previous and now-previous[0]>=0.05 and m['effective_cpu_cores']:
                m['process_cpu_percent']=round((cpu-previous[1])*100/(now-previous[0])/m['effective_cpu_cores'],2)
            counters=dict(self.counts,reasons=dict(self.counts['reasons']))
            if include_gpu and (self.gpu_cache is None or now-self.gpu_at>=5):
                self.gpu_cache=gpu_snapshot();self.gpu_at=now
            gpu=self.gpu_cache if include_gpu else None
        return {'schema':'orbit.resources.v1','sampled_at':int(time.time()),'metrics':m,'policy':dict(self.policy),
                'pressure_reason':pressure(m,self.policy),'admission':counters,
                'gpu':gpu,'note':'Backend process/OS/cgroup only. Not remote model capacity; process-local counters reset on restart.'}

def loaded_models(lane):
    # Explicit local-only read from a configured Ollama endpoint. Never pull or unload.
    if lane.provider!='ollama' or urlsplit(lane.base_url).hostname not in ('localhost','127.0.0.1','::1'):
        return {'status':'not_local_ollama','models':[]}
    headers={'Accept':'application/json'}
    if lane.api_key:headers['Authorization']='Bearer '+lane.api_key
    try:
        req=urllib.request.Request(lane.base_url[:-3]+'/api/ps',headers=headers,method='GET')
        with urllib.request.build_opener(urllib.request.ProxyHandler({}),mp.NoRedirect()).open(req,timeout=min(5,lane.timeout)) as r:
            raw=r.read(1_000_001)
        if len(raw)>1_000_000:raise ValueError()
        rows=json.loads(raw)['models']
        if not isinstance(rows,list):raise ValueError()
        models=[]
        for item in rows[:100]:
            if not isinstance(item,dict):continue
            name=item.get('name',item.get('model'))
            if not isinstance(name,str) or not 0<len(name)<=200 or any(ord(x)<32 or ord(x)==127 for x in name):continue
            models.append({'model':name,'size_bytes':nonnegative(item.get('size')),
                           'size_vram_bytes':nonnegative(item.get('size_vram')),
                           'context_length':nonnegative(item.get('context_length'))})
        return {'status':'available','models':models}
    except (OSError,ValueError,KeyError,TypeError,urllib.error.URLError):
        return {'status':'unavailable','models':[]}
