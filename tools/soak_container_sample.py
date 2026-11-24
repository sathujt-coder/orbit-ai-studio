#!/usr/bin/env python3
"""Append bounded Ollama runtime evidence from a dedicated stress container."""
import json,re,subprocess,sys,time
def run(*args):return subprocess.check_output(['docker',*args],text=True,timeout=20).strip()
def main():
    name,path=sys.argv[1:]
    if not re.fullmatch(r'orbit-soak-\d+|orbit-airgap',name):raise ValueError('Dedicated stress container required')
    data={'sampled_at':int(time.time()),'gate':'BLOCK'}
    try:
        obj=json.loads(run('inspect',name))[0];h=obj['HostConfig'];s=obj['State']
        stats=json.loads(run('stats','--no-stream','--format','{{json .}}',name))
        raw=run('exec',name,'cat','/sys/fs/cgroup/memory.events')
        events={k:int(v) for k,v in (line.split() for line in raw.splitlines()) if k in ('oom','oom_kill','max','high')}
        data.update(container_id=obj['Id'],memory_limit=h['Memory'],memory_swap=h['MemorySwap'],cpu_cores=h['NanoCpus']/1e9,network=h['NetworkMode'],
                    running=s['Running'],oom_killed=s['OOMKilled'],memory_events=events,stats={k:stats.get(k) for k in ('MemUsage','MemPerc','CPUPerc','PIDs')})
        if h['Memory']==6*1024**3 and h['MemorySwap']==h['Memory'] and h['NanoCpus']==2_000_000_000 and h['NetworkMode']=='none' and s['Running'] and not s['OOMKilled'] and events.get('oom')==events.get('oom_kill')==0 and stats.get('MemUsage'):data['gate']='PASS'
    except Exception as e:data['error_type']=type(e).__name__
    with open(path,'a',encoding='utf-8') as f:f.write(json.dumps(data)+'\n')
    return 0 if data['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
