#!/usr/bin/env python3
"""Offline component benchmark; never changes provider settings or adopts a plan."""
import argparse, collections, hashlib, json, math, os, re, subprocess, sys, time
from pathlib import Path
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import model_provider as mp
import planning_discovery as pd
import planning_scope as ps
import project_planning as pp
import product_requirements as pr
import wbs_decomposition as d
import work_breakdown as w
from planning_fixture import approved_fixture

MODELS=('qwen2.5-coder:3b','qwen2.5:3b','qwen3:4b','qwen2.5-coder:7b','qwen2.5:7b','qwen3:8b')
CASES=('A','B')
REPEATS=(1,2)
LIMIT=6*1024**3
CPU=2
CONTEXT=8192
TIMEOUT=300
TRIAL_TIMEOUT=25*60
PROTOCOL='orbit.wbs-model-benchmark.v1'
BASE='http://127.0.0.1:11434'
CONFIRM='RUN LOCAL WBS BENCHMARK'
# Fixed historical PM inputs, not generated WBS details. From verified
# artifact 15004958355, source 702ca84793f285b80b66388f4c54062d59322bf4.
PM_ARTIFACT_SHA256='629cb1792f22fc13490abf97d8c7cf0804d8adc8dbe28353c9c2bc93712c04e6'
PM={
    'A':("Implement URL saving and listing features for existing projects",[
        ("Create a function to save URLs in the user's project","Ensure saved URLs are persisted in the database"),
        ("Develop a function to list saved URLs in the user's project","Verify that listed URLs match the saved URLs"),
        ("Implement project isolation to prevent unauthorized access to other projects","Ensure that unauthorized users cannot access other projects")]),
    'B':("Implement URL storage and project isolation",[
        ("Save URL in own project","A saved URL is persisted"),
        ("List saved links in own project","Saved URL appears in list"),
        ("Enforce project isolation","Unauthorized cross-project read is denied")])}

def fixture(case):
    doc,extra=approved_fixture()
    doc=pr.validate(doc);policy=ps.contract(doc,extra)
    objective,titles=PM[case]
    proposal=pd.parse(json.dumps(dict(objective=objective,work=[
        dict(requirement=req['id'],implement=t[0],verify=t[1]) for req,t in zip(doc['requirements'],titles)])),dict(document=doc))
    if not ps.assess(proposal,doc,policy)['passed'] or not ps.content_findings(proposal)['passed']:
        raise ValueError('Frozen PM proposal no longer passes unchanged gates')
    src=dict(document=doc,policy=policy,proposal=proposal,requirements_version=1,
        requirements_digest=pp.digest(doc),queue_id='benchmark-frozen-pm',lane=case,proposal_digest=pp.digest(proposal))
    blank=d.blank(src,w.skeleton(src))
    return src,blank

def fixture_id(case):
    source,blank=fixture(case)
    return pp.digest(dict(source=source,blank=blank,prompt=d.RULES,policy=d.POLICY,wire=d.WIRE))

def percentile(values,q):
    return sorted(values)[max(0,math.ceil(len(values)*q)-1)] if values else None

def measure(evidence,calls,source,blank):
    """Reuse the real decomposition engine and independent replay, not a new score threshold."""
    g=d.gate(evidence,source,blank)
    analysis=w.assess(evidence['candidate'],source)
    attempts=[a for b in evidence['history'] for a in b['attempts']]
    repairs=[a for a in attempts if a['phase']=='wbs_decompose_repair']
    issues=analysis['issues']
    pkgs=d.packages(evidence['candidate'])
    populated=sum(all(p[k] is not None for k in w.DETAIL_FIELDS) for p in pkgs.values())
    expected=[a['phase'] for a in attempts]
    complete=bool(calls and all(c.get('coverage')=='complete' and type(c.get('total_tokens')) is int
        and c['total_tokens']>0 and type(c.get('input_tokens')) is int and type(c.get('output_tokens')) is int
        and c['total_tokens']==c['input_tokens']+c['output_tokens'] for c in calls))
    gates=dict(ready=g['ready'],replay=g['repair_audit_valid'],detail_quality=analysis['detail_ready'],
        exact_trace=analysis['package_count']==6 and analysis['criterion_count']==3 and
            all(len(t['implement'])==len(t['verify'])==1 for t in analysis['traceability'].values()),
        no_contamination=not any(w.detail_contaminated(p[k]) for p in pkgs.values() for k in w.DETAIL_FIELDS),
        call_bound=2<=len(calls)<=4 and len(calls)==g['call_count'] and [c['phase'] for c in calls]==expected,
        native_usage=complete and all(c.get('source')=='ollama_native' and c.get('status')=='ok' for c in calls),
        repair_convergence=all(a['valid'] and a.get('convergence',{}).get('passed') is True and
            not a['convergence'].get('lost_scope_groups') for a in repairs),
        candidate_binding=g['candidate_digest']==pp.digest(evidence['candidate']))
    return dict(gates=gates,quality_pass=all(gates.values()),calls=len(calls),batches=len(evidence['history']),
        completed_packages=populated,issue_count=len(issues),issues_by_code=dict(collections.Counter(x['code'] for x in issues)),
        repair_calls=len(repairs),successful_repairs=sum(a.get('convergence',{}).get('passed') is True for a in repairs),
        input_tokens=sum(c['input_tokens'] for c in calls) if complete else None,
        output_tokens=sum(c['output_tokens'] for c in calls) if complete else None,
        total_tokens=sum(c['total_tokens'] for c in calls) if complete else None,
        latency_p50_ms=percentile([c['elapsed_ms'] for c in calls],.5),
        latency_p95_ms=percentile([c['elapsed_ms'] for c in calls],.95))

def local_json(path):
    # Fixed loopback endpoint, no proxy, redirects, or credentials.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),mp.NoRedirect())
    with opener.open(BASE+path,timeout=20) as response:
        raw=response.read(mp.MAX_RESPONSE+1)
    if len(raw)>mp.MAX_RESPONSE:raise ValueError('Oversized Ollama metadata')
    return json.loads(raw)

def model_identity(model):
    entry=next(x for x in local_json('/api/tags')['models'] if x.get('name')==model or x.get('model')==model)
    digest=entry['digest'].removeprefix('sha256:')
    if not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Missing immutable model digest')
    return dict(model=model,digest=digest,size=entry.get('size'),details=entry.get('details'),
        ollama_version=local_json('/api/version')['version'])

def worker(model,case,repeat,commit):
    source,blank=fixture(case)
    report=dict(schema=PROTOCOL,model=model,case=case,repeat=repeat,source_commit=commit,
        fixture_digest=fixture_id(case),pm_artifact_sha256=PM_ARTIFACT_SHA256,quality_pass=False,
        origin='actual_local_model',calls=[],semantic_reviewed=False,production_adopted=False)
    start=time.monotonic()
    try:
        ident=model_identity(model);report['identity']=ident
        lane=mp.Lane(case,'ollama',BASE+'/v1',model,'',timeout=TIMEOUT,context_window=CONTEXT)
        def call(phase,system,user,schema):
            if len(report['calls'])>=4:raise RuntimeError('Fixture call bound exceeded')
            def observe(usage):
                report['calls'].append(dict(usage,phase=phase,model=model))
            return mp.chat(lane,system,user,schema=schema,max_tokens=d.MAX_OUTPUT,
                runtime_settings=True,usage_observer=observe)
        e=d.run(call,source,blank)
        report['evidence']=e
        report['metrics']=measure(e,report['calls'],source,blank)
        report['identity_after']=model_identity(model)
        report['quality_pass']=report['metrics']['quality_pass'] and report['identity_after']==ident
        report['status']='PASS' if report['quality_pass'] else 'QUALITY_BLOCK'
    except Exception as exc:
        report.update(status='INFERENCE_ERROR',error_type=type(exc).__name__,error=str(exc)[:300])
    report['wall_ms']=round((time.monotonic()-start)*1000)
    return report

def docker(*args,timeout=60):
    return subprocess.check_output(['docker',*args],text=True,timeout=timeout,stderr=subprocess.STDOUT).strip()

def command(*args,timeout=60):
    return subprocess.run(['docker',*args],timeout=timeout,check=False).returncode

def ready(container):
    for _ in range(60):
        try:
            docker('exec',container,'ollama','list',timeout=5)
            return
        except (OSError,subprocess.SubprocessError):
            time.sleep(1)
    raise RuntimeError('Ollama not ready')

def resources(container):
    state=json.loads(docker('inspect',container))[0]
    h=state['HostConfig'];s=state['State']
    result=dict(memory_limit=h['Memory'],swap_limit=h['MemorySwap'],cpu_limit=h['NanoCpus']/1e9,
        network=h['NetworkMode'],running=s['Running'],oom_killed=s['OOMKilled'],restart_count=state['RestartCount'])
    try:
        result['peak_bytes']=int(docker('exec',container,'cat','/sys/fs/cgroup/memory.peak'))
        result['current_bytes']=int(docker('exec',container,'cat','/sys/fs/cgroup/memory.current'))
        result['cgroup_limit_bytes']=int(docker('exec',container,'cat','/sys/fs/cgroup/memory.max'))
        result['events']={k:int(v) for k,v in (x.split() for x in docker('exec',container,'cat','/sys/fs/cgroup/memory.events').splitlines())}
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        result['sample_error']=type(exc).__name__
    result['passed']=resource_pass(result)
    return result

def resource_pass(r):
    return bool(r.get('memory_limit')==r.get('swap_limit')==r.get('cgroup_limit_bytes')==LIMIT and
        r.get('cpu_limit')==CPU and r.get('network')=='none' and r.get('running') is True and
        r.get('oom_killed') is False and r.get('restart_count')==0 and
        type(r.get('peak_bytes')) is int and 0<r['peak_bytes']<=LIMIT and
        r.get('events',{}).get('oom')==0 and r.get('events',{}).get('oom_kill')==0)

def resource_diagnostics(r):
    """Explain the existing strict resource gate, without changing it."""
    reasons=[]
    for key,expected in (('memory_limit',LIMIT),('swap_limit',LIMIT),('cgroup_limit_bytes',LIMIT),
                         ('cpu_limit',CPU),('network','none'),('restart_count',0)):
        if r.get(key)!=expected:reasons.append(key+'_mismatch')
    if r.get('running') is not True:reasons.append('runtime_not_running')
    if r.get('oom_killed') is not False:reasons.append('oom_killed_or_unknown')
    peak=r.get('peak_bytes')
    if type(peak) is not int or peak<=0:reasons.append('peak_missing_or_invalid')
    elif peak>LIMIT:reasons.append('peak_over_limit')
    events=r.get('events',{})
    for key in ('oom','oom_kill'):
        if events.get(key)!=0:
            reasons.append(key+'_event' if type(events.get(key)) is int and events[key]>0 else key+'_unverified')
    return dict(passed=resource_pass(r),reasons=reasons,peak_bytes=peak,
        peak_over_limit_bytes=max(0,peak-LIMIT) if type(peak) is int else None)

def trial_diagnostics(row,replay_pass):
    """Keep resource, inference and reported quality failures independent.

    Diagnostics are descriptive only; replay_pass comes from trial_qualifies.
    Never upgrade a trial or treat missing worker metrics as a quality pass.
    """
    worker=row.get('worker',{});metrics=worker.get('metrics',{})
    resource=resource_diagnostics(row.get('resources',{}))
    gates=metrics.get('gates',{})
    return dict(case=row['case'],repeat=row['repeat'],status=row['status'],
        replay_pass=replay_pass,resource=resource,worker_status=worker.get('status'),
        worker_exit=row.get('worker_exit'),worker_error_type=worker.get('error_type'),
        infra_error_type=row.get('error_type'),quality_metrics_available=bool(gates),
        reported_quality_pass=metrics.get('quality_pass'),
        reported_failed_gates=sorted(k for k,v in gates.items() if v is not True),
        reported_issues_by_code=metrics.get('issues_by_code'),
        reported_repair_calls=metrics.get('repair_calls'),
        reported_successful_repairs=metrics.get('successful_repairs'))

def write(path,data):
    with path.open('x',encoding='utf-8') as out:json.dump(data,out,indent=2,ensure_ascii=False)

def trial(model,case,repeat,commit,folder,ollama,python,volume):
    name='orbit-bench-airgap';client='orbit-bench-client'
    path=folder/('trial-'+case+'-'+str(repeat)+'.json')
    outer=dict(model=model,case=case,repeat=repeat,source_commit=commit,qualified=False,
        fixture_digest=fixture_id(case),status='INFRA_ERROR')
    start=time.monotonic()
    try:
        docker('run','-d','--name',name,'--network','none','--memory','6g','--memory-swap','6g','--cpus','2',
            '-e','OLLAMA_NO_CLOUD=1','-e','OLLAMA_NUM_PARALLEL=1','-e','OLLAMA_MAX_LOADED_MODELS=1',
            '-e','OLLAMA_CONTEXT_LENGTH=8192','-v',volume+':/root/.ollama',ollama)
        ready(name)
        rc=command('run','--rm','--name',client,'--user',str(os.getuid())+':'+str(os.getgid()),
            '--network','container:'+name,'--mount','type=bind,src='+str(ROOT)+',dst=/repo,readonly',
            '--mount','type=bind,src='+str(folder)+',dst=/report','-e','PYTHONDONTWRITEBYTECODE=1',
            python,'python','/repo/tools/wbs_benchmark.py','worker','--model',model,'--case',case,
            '--repeat',str(repeat),'--commit',commit,'--report','/report/'+path.name,
            '--confirm',CONFIRM,timeout=TRIAL_TIMEOUT)
        outer['worker_exit']=rc
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        outer['error_type']=type(exc).__name__
    finally:
        command('rm','-f',client)
        try:outer['resources']=resources(name)
        except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError) as exc:
            outer['resources']=dict(passed=False,error_type=type(exc).__name__)
        command('rm','-f',name)
    if path.exists():
        outer['worker']=json.loads(path.read_text())
    r=outer['resources'];wr=outer.get('worker',{})
    if r.get('oom_killed') is True or r.get('events',{}).get('oom',0)>0 or r.get('events',{}).get('oom_kill',0)>0:
        outer['status']='RESOURCE_BLOCK'
    elif not r.get('passed'):
        outer['status']='RESOURCE_UNVERIFIED'
    elif outer.get('worker_exit')==0 and wr.get('status') in ('PASS','QUALITY_BLOCK','INFERENCE_ERROR'):
        outer['status']=wr['status']
        outer['qualified']=bool(wr.get('quality_pass') and wr['status']=='PASS')
    outer['wall_ms']=round((time.monotonic()-start)*1000)
    return outer

def trial_qualifies(row,model,commit):
    """Independently replay worker evidence and check measured resource bounds."""
    try:
        case=row['case'];wr=row['worker'];identity=wr['identity']
        if (row['status']!='PASS' or row.get('worker_exit')!=0 or not resource_pass(row['resources'])
                or wr['schema']!=PROTOCOL or wr['origin']!='actual_local_model'
                or wr['production_adopted'] is not False or wr['semantic_reviewed'] is not False
                or wr['source_commit']!=commit or wr['model']!=model or wr['case']!=case
                or wr['repeat']!=row['repeat'] or wr['fixture_digest']!=fixture_id(case)
                or wr['pm_artifact_sha256']!=PM_ARTIFACT_SHA256
                or identity['model']!=model or not re.fullmatch('[0-9a-f]{64}',identity['digest'])
                or not identity['ollama_version'] or identity!=wr['identity_after']
                or any(c['model']!=model for c in wr['calls'])):
            return False
        src,blank=fixture(case)
        return measure(wr['evidence'],wr['calls'],src,blank)['quality_pass']
    except (KeyError,ValueError,TypeError,IndexError,AttributeError):
        return False

def summarize(model,trials,commit,images):
    expected={(c,r) for c in CASES for r in REPEATS}
    keys=[(x['case'],x['repeat']) for x in trials]
    identities=[x.get('worker',{}).get('identity',{}) for x in trials]
    digests={x.get('digest') for x in identities if x.get('digest')}
    versions={x.get('ollama_version') for x in identities if x.get('ollama_version')}
    metrics=[x.get('worker',{}).get('metrics',{}) for x in trials]
    calls=[c for x in trials for c in x.get('worker',{}).get('calls',[])]
    replays=[trial_qualifies(x,model,commit) for x in trials]
    qualified=sum(replays)
    diagnostics=[trial_diagnostics(x,ok) for x,ok in zip(trials,replays)]
    complete=(len(keys)==len(expected) and set(keys)==expected and all(
        x.get('model')==model and x.get('source_commit')==commit and x.get('fixture_digest')==fixture_id(x['case'])
        and x['status'] in ('PASS','QUALITY_BLOCK','RESOURCE_BLOCK','INFERENCE_ERROR','RESOURCE_UNVERIFIED','INFRA_ERROR') for x in trials))
    comparable=complete and all(x['status'] in ('PASS','QUALITY_BLOCK','RESOURCE_BLOCK') for x in trials)
    # A model may fail on this hardware. Missing metrics are never zero-filled.
    measured=bool(metrics and all(type(x.get('total_tokens')) is int for x in metrics))
    repair_calls=sum(c.get('phase')=='wbs_decompose_repair' for c in calls)
    peaks=[x.get('resources',{}).get('peak_bytes') for x in trials if type(x.get('resources',{}).get('peak_bytes')) is int]
    status='QUALIFIED' if comparable and qualified==len(expected) and len(digests)==len(versions)==1 else 'NOT_QUALIFIED'
    return dict(schema=PROTOCOL,model=model,source_commit=commit,images=images,profile=dict(memory_bytes=LIMIT,
        cpu_cores=CPU,context_tokens=CONTEXT,output_tokens=d.MAX_OUTPUT,batch=d.BATCH,max_calls_per_case=4),
        benchmark_complete=comparable,trials_recorded=complete,qualification=status,model_digests=sorted(digests),ollama_versions=sorted(versions),
        expected_trials=len(expected),qualified_trials=qualified,pass_rate=qualified/len(expected),
        trial_statuses=dict(collections.Counter(x['status'] for x in trials)),
        calls=len(calls),repair_calls=repair_calls,repair_call_rate=repair_calls/len(calls) if calls else None,
        successful_repairs=sum(x.get('successful_repairs',0) for x in metrics),
        repair_success_rate=(sum(x.get('successful_repairs',0) for x in metrics)/repair_calls if repair_calls else None),
        completed_packages=sum(x.get('completed_packages',0) for x in metrics),
        total_tokens=sum(x['total_tokens'] for x in metrics) if measured else None,
        total_wall_ms=sum(x.get('wall_ms',0) for x in trials) if complete else None,
        latency_p50_ms=percentile([c['elapsed_ms'] for c in calls],.5),latency_p95_ms=percentile([c['elapsed_ms'] for c in calls],.95),
        peak_bytes=max(peaks) if peaks else None,trials=trials,diagnostics=diagnostics,
        diagnostic_resource_reasons=dict(collections.Counter(reason for x in diagnostics for reason in x['resource']['reasons'])),
        semantic_reviewed=False,production_adopted=False)

def run_model(model,commit,folder,ollama,python):
    folder.mkdir(parents=True,exist_ok=False)
    volume='orbit-bench-models';download='orbit-bench-download'
    images=dict(ollama=ollama,python=python);trials=[]
    try:
        docker('pull',ollama,timeout=600);docker('pull',python,timeout=600)
        docker('volume','create',volume)
        docker('run','-d','--name',download,'-e','OLLAMA_NO_CLOUD=1','-v',volume+':/root/.ollama',ollama)
        ready(download)
        docker('exec',download,'ollama','pull',model,timeout=1200)
        docker('rm','-f',download)
        for repeat in REPEATS:
            for case in CASES:
                trials.append(trial(model,case,repeat,commit,folder,ollama,python,volume))
                print(model,case,repeat,trials[-1]['status'],flush=True)
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print('Benchmark infrastructure error:',type(exc).__name__,flush=True)
    finally:
        command('rm','-f',download,'orbit-bench-client','orbit-bench-airgap')
        command('volume','rm',volume)
    result=summarize(model,trials,commit,images);write(folder/'summary.json',result)
    return 0 if result['benchmark_complete'] else 2

def aggregate(folder,commit,report):
    found={}
    for path in sorted(folder.rglob('summary.json')):
        row=json.loads(path.read_text())
        if row['model'] in found or row.get('source_commit')!=commit:raise ValueError('Duplicate model summary or source mismatch')
        found[row['model']]=row
    # Independent summary recomputation; never trust a claimed qualification flag.
    rows=[summarize(model,found[model]['trials'],commit,found[model]['images']) for model in MODELS if model in found]
    complete=set(found)==set(MODELS) and all(r['benchmark_complete'] and r['source_commit']==commit for r in rows)
    same_images=(len({pr.canonical(r['images']) for r in rows})==1 and all(
        pinned_image(r['images'].get('ollama',''),'ollama/ollama') and pinned_image(r['images'].get('python',''),'python') for r in rows))
    same_runtime=len({v for r in rows for v in r['ollama_versions']})==1
    eligible=[r['model'] for r in rows if r['qualification']=='QUALIFIED']
    result=dict(schema=PROTOCOL,source_commit=commit,benchmark_complete=complete and same_images and same_runtime,
        qualification_gate='PASS' if complete and same_images and same_runtime and eligible else 'BLOCK',
        qualified_models=eligible if complete and same_images and same_runtime else [],models=rows,
        missing_models=sorted(set(MODELS)-set(found)),production_adopted=False,same_runtime=same_runtime,same_images=same_images,
        note='Component qualification on one fixed PRD; full queued A/B acceptance and human review remain required.')
    write(report,result)
    print(json.dumps({k:v for k,v in result.items() if k!='models'},indent=2))
    return 0 if result['qualification_gate']=='PASS' else 2

def pinned_image(value,name):
    return bool(re.fullmatch(re.escape(name)+r'@sha256:[0-9a-f]{64}',value))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('worker','run','aggregate'));p.add_argument('--model',choices=MODELS)
    p.add_argument('--case',choices=CASES);p.add_argument('--repeat',type=int,choices=REPEATS)
    p.add_argument('--commit',required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--input',type=Path);p.add_argument('--ollama-image');p.add_argument('--python-image')
    p.add_argument('--confirm',required=True);a=p.parse_args()
    if a.confirm!=CONFIRM or not re.fullmatch('[0-9a-f]{40}',a.commit) or a.report.exists():p.error('Explicit confirmation, exact source SHA and new report required')
    if a.mode=='worker':
        if not (a.model and a.case and a.repeat):p.error('Model, case and repeat required')
        write(a.report,worker(a.model,a.case,a.repeat,a.commit));return 0
    if a.mode=='run':
        if not a.model or not pinned_image(a.ollama_image or '','ollama/ollama') or not pinned_image(a.python_image or '','python'):
            p.error('Allowlisted model and digest-pinned images required')
        return run_model(a.model,a.commit,a.report.resolve(),a.ollama_image,a.python_image)
    if not a.input:p.error('Aggregate input required')
    return aggregate(a.input,a.commit,a.report)
if __name__=='__main__':raise SystemExit(main())
