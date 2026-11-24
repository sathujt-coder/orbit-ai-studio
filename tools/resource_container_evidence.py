#!/usr/bin/env python3
"""Read the fixed CI inference container's actual configured limits and final usage."""
import json,subprocess,sys
from pathlib import Path
def run(*args):
    return subprocess.check_output(['docker',*args],text=True,timeout=20).strip()
def main():
    path=Path(sys.argv[1])
    data={'schema':'orbit.container-resources.v1','container':'orbit-airgap','gate':'BLOCK'}
    try:
        state=json.loads(run('inspect','orbit-airgap'))[0]
        h=state['HostConfig'];s=state['State']
        stats=json.loads(run('stats','--no-stream','--format','{{json .}}','orbit-airgap'))
        data.update(memory_limit_bytes=h['Memory'],memory_swap_limit_bytes=h['MemorySwap'],cpu_limit_cores=h['NanoCpus']/1e9,
                    network_mode=h['NetworkMode'],running=s['Running'],oom_killed=s['OOMKilled'],
                    sample={k:stats.get(k) for k in ('CPUPerc','MemUsage','MemPerc','PIDs')})
        try:
            events=run('exec','orbit-airgap','cat','/sys/fs/cgroup/memory.events')
            data['memory_events']={k:int(v) for k,v in (line.split() for line in events.splitlines()) if k in ('oom','oom_kill','max','high')}
        except (OSError,ValueError,subprocess.SubprocessError):data['memory_events']=None
        if h['Memory']==6*1024**3 and h['MemorySwap']==h['Memory'] and h['NanoCpus']==2_000_000_000 and h['NetworkMode']=='none' and s['Running'] and not s['OOMKilled'] and stats.get('MemUsage') and (data['memory_events'] is None or data['memory_events'].get('oom_kill',0)==0):
            data['gate']='PASS'
    except (OSError,ValueError,KeyError,IndexError,TypeError,subprocess.SubprocessError) as e:data['error_type']=type(e).__name__
    finally:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as f:json.dump(data,f,indent=2)
        print(json.dumps(data,indent=2))
    return 0 if data['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
