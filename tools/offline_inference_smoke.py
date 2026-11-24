#!/usr/bin/env python3
"""Actual local Ollama inference; no generated code execution or GitHub writes."""
import argparse,json,os,sys,tempfile,threading,time,urllib.request,re
from pathlib import Path
from contextlib import nullcontext
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
import model_provider
import sqlite3
import offline_sandbox_gate as sandbox_gate
import offline_generation as generation
from contextlib import closing
MODELS=('qwen2.5-coder:3b','qwen2.5:3b')
SPEC=generation.BENCHMARK_SPEC
def get_json(path):
    with urllib.request.build_opener(urllib.request.ProxyHandler({}),model_provider.NoRedirect()).open('http://127.0.0.1:11434'+path,timeout=15) as r:
        raw=r.read(2_000_001)
        if len(raw)>2_000_000:raise ValueError('Oversized local metadata')
        return json.loads(raw)
def config(models):
    if len(set(models))!=2 or any(not re.fullmatch(r'[a-zA-Z0-9._/-]+:[a-zA-Z0-9._-]+',m) or 'cloud' in m.lower() for m in models):
        raise ValueError('Two distinct local model tags required')
    return model_provider.load_config({'AI_PROVIDER':'ollama','AI_BASE_URL':'http://127.0.0.1:11434/v1','AI_MODEL_A':models[0],'AI_MODEL_B':models[1],'AI_TIMEOUT':'180'})
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model-a',default=MODELS[0]);p.add_argument('--model-b',default=MODELS[1])
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--db-output',type=Path,help='Optional new private SQLite file to retain candidates for human review')
    p.add_argument('--repair-db',type=Path)
    p.add_argument('--repair-report',type=Path)
    p.add_argument('--workflow',action='store_true',help='Run independent generation and cross review, not code execution')
    p.add_argument('--confirm',required=True)
    a=p.parse_args()
    if a.confirm!='RUN LOCAL INFERENCE':p.error('Explicit confirmation RUN LOCAL INFERENCE required')
    if a.report.exists():p.error('Report path already exists')
    if a.db_output and (not a.workflow or a.db_output.exists() or a.db_output.resolve()==a.report.resolve()):p.error('DB output must be a distinct new file, with --workflow')
    if bool(a.repair_db)!=bool(a.repair_report) or (a.repair_db and not (a.workflow and a.db_output)):
        p.error('Repair requires previous DB + sandbox report, workflow and new private DB')
    report={'schema':'orbit.offline-inference.v1','mode':'local_ollama','network_isolation':'not asserted by this script','sandbox_verified':False,'production_approved':False,'git_writes':False}
    code=1
    try:
        models=(a.model_a,a.model_b);lanes=config(models)
        tags=get_json('/api/tags')['models']
        found={m['name']:m for m in tags}
        report['models']={}
        for lane,tag in zip('AB',models):
            digest=found.get(tag,{}).get('digest','')
            if not re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}',digest):raise ValueError('Required local model missing: '+tag)
            report['models'][lane]={'tag':tag,'digest':digest}
        report['runtime_version']=get_json('/api/version').get('version','unknown')
        report['probe']=model_provider.probe(lanes)
        if not report['probe']['both_responded']:raise ValueError('Both models must respond')
        code=0
        if a.workflow:
            # Isolated synthetic project, never sends real repository or customer data.
            with (nullcontext(None) if a.db_output else tempfile.TemporaryDirectory(prefix='orbit-local-inference-')) as tmp:
                db_path=a.db_output.resolve() if a.db_output else Path(tmp)/'smoke.sqlite'
                if a.db_output:
                    fd=os.open(db_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
                os.environ.update(AI_COMPANY_DB=str(db_path),AI_PROVIDER='demo')
                for k in ('AI_PROVIDER_A','AI_PROVIDER_B'):os.environ.pop(k,None)
                import server,coding_factory as cf,usage_store,cost_store,resource_manager
                server.init_db()
                with server.db() as c:
                    pid=server.create_project('Local inference smoke','Small independent Web backend arithmetic module for a synthetic test only.','Web app',c)
                repair=None
                if a.repair_db:
                    previous=json.loads(a.repair_report.read_text())
                    if previous.get('models')!=report['models']:raise ValueError('Repair must use the same model digests')
                    with closing(sqlite3.connect(a.repair_db.resolve().as_uri()+'?mode=ro',uri=True)) as old:
                        old.row_factory=sqlite3.Row
                        previous_job=cf.detail(old,previous['job_id'])
                    if previous_job['spec']!=SPEC:raise ValueError('Repair benchmark scope mismatch')
                    repair=sandbox_gate.repair_plan(previous_job,previous)
                    report['repair']={'parent_job_id':previous_job['id'],'reused_lanes':[k for k,v in repair.items() if v['reuse']],
                                      'regenerated_lanes':[k for k,v in repair.items() if not v['reuse']]}
                done=threading.Event()
                calls=[]
                diagnostics=[]
                recoveries=[]
                repair_events=[]
                repair_sampling=set()
                job_ref={'id':None}
                resource_before=server.RESOURCE_MANAGER.snapshot()
                def model(system,user,lane):
                    calls.append(lane)
                    return usage_store.tracked_chat(server.db,server.LOCK,lanes[lane],system,user,project_id=pid,agent_id='dev-'+lane,purpose='offline_generation',run_id=job_ref['id'],resource_guard=server.RESOURCE_MANAGER,max_tokens=2048)
                def structured(system,user,lane,schema):
                    calls.append(lane)
                    return usage_store.tracked_chat(server.db,server.LOCK,lanes[lane],system,user,project_id=pid,agent_id='dev-'+lane,purpose='code_review' if schema is cf.REVIEW_SCHEMA else 'file_repair' if schema is generation.FILE_SCHEMA else 'code_generate',run_id=job_ref['id'],resource_guard=server.RESOURCE_MANAGER,schema=schema,max_tokens=2048,
                                               repair_temperature=0.25 if lane in repair_sampling and schema is generation.FILE_SCHEMA else None)
                model.structured=structured
                def diagnostic(lane,schema,attempt,code):
                    kind='proposal' if schema is cf.PROPOSAL_SCHEMA else 'review' if schema is cf.REVIEW_SCHEMA else 'single_file'
                    diagnostics.append({'lane':lane,'kind':kind,'attempt':attempt,'code':code})
                def recovery(model_call,project,spec,context,lane):
                    event={'lane':lane,'status':'started'};recoveries.append(event)
                    try:
                        result=generation.recover(model_call,project,spec,context,lane)
                        event['status']='generated';return result
                    except (ValueError,model_provider.ProviderError):
                        event['status']='failed';raise
                model.structured_diagnostic=diagnostic
                model.proposal_recovery=recovery
                def intelligent(model_call,project,spec,context,lane,previous):
                    repair_sampling.add(lane)
                    try:return generation.intelligent_repair(model_call,project,spec,context,lane,previous,repair_events)
                    finally:repair_sampling.discard(lane)
                model.repair_candidate=intelligent
                def worker(jid,project):
                    job_ref['id']=jid
                    try:cf.work(server.db,server.LOCK,jid,project,model,server.now,server.log,server.get_preceding,repair=repair)
                    finally:done.set()
                jid=cf.begin(server.db,server.LOCK,pid,SPEC,server.uid,server.now,server.log,worker)
                if not done.wait(1600):raise ValueError('Workflow exceeded time budget')
                with server.db() as c:
                    j=cf.detail(c,jid)
                    usage=usage_store.summary(c,pid,1)
                    costs=cost_store.summary(c,pid,1)
                report['token_usage']=usage
                report['ai_cost']=costs
                resource_after=server.RESOURCE_MANAGER.snapshot()
                loaded=resource_manager.loaded_models(lanes['A'])
                report['resources']={'before':resource_before,'after':resource_after,'local_ollama':loaded}
                report['workflow']={'job_id':jid,'status':j['status'],'calls':calls,'failure':j.get('error'),'structured_diagnostics':diagnostics,'file_recoveries':recoveries,'intelligent_repairs':repair_events,
                    'candidates':{k:len((j.get('proposal_'+k.lower()) or {}).get('files',[])) for k in 'AB'},
                    'reviews':{k:{field:(j.get('review_'+k.lower()) or {}).get(field) for field in ('verdict','score')} for k in 'AB'},
                    'review_gate_passed':j['status']=='ready','private_db_retained':bool(a.db_output),'candidate_files':(j.get('manifest') or {}).get('candidate_files',{})}
                # A rejected review is a functioning gate, not successful acceptance.
                code=0 if j['status']=='ready' else 2
                if code==0 and (usage['totals']['requests']!=len(calls) or usage['totals']['complete_calls']!=len(calls) or usage['totals']['total_tokens'] is None or usage['totals']['total_tokens']<=0):
                    report['usage_gate']='BLOCK';code=2
                else:report['usage_gate']='PASS' if code==0 else 'not_accepted'
                if code==0 and (costs['totals']['requests']!=len(calls) or costs['totals']['local_assumed_zero_calls']!=len(calls) or costs['totals']['total_usd']!='0.000000000000'):
                    report['cost_gate']='BLOCK';code=2
                else:report['cost_gate']='PASS' if code==0 else 'not_accepted'
                if code==0 and (resource_after['admission']['allowed']!=len(calls) or resource_after['admission']['blocked'] or loaded['status']!='available' or not loaded['models'] or (resource_after['policy']['mode']=='enforce' and resource_after['metrics']['effective_memory_available_bytes'] is None)):
                    report['resource_gate']='BLOCK';code=2
                else:report['resource_gate']='PASS' if code==0 else 'not_accepted'
        else:report['workflow']={'status':'not_requested'}
    except (OSError,ValueError,KeyError,TypeError,model_provider.ProviderError) as e:
        report['error_type']=type(e).__name__
        # Do not print remote body, generated source or secrets.
        code=1
    finally:
        with a.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
        print(json.dumps(report,indent=2))
    return code
if __name__=='__main__':raise SystemExit(main())
