#!/usr/bin/env python3
"""Real local PM A/B acceptance; no plan adoption or execution."""
import argparse,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

def require(ok,message):
    if not ok:raise RuntimeError(message)

def wbs_acceptance(server,pid,report):
    """Use actual local AI detail outputs only; preserve P6.2c checks."""
    import work_breakdown as w,project_planning as pp,decomposition_jobs as dj,wbs_decomposition as d,usage_store,cost_store
    report['wbs']=dict(detail_origin='model_generated',lanes={},gates={})
    gates=report['wbs']['gates'];report['wbs']['gate']='BLOCK'
    for lane in 'AB':
        with server.db() as c:
            view=w.view(c,pid);source=view['sources'][lane]
            version=view['current']['version'] if view['current'] else 0
            seed=w.save(c,pid,'fixture-author',dict(source,expected_version=version,confirmation='CREATE WBS DRAFT'),server.now(),seed=True)
            base=seed['current'];gates['wbs_'+lane+'_structure']=seed['analysis']['deliverable_count']==3 and seed['analysis']['package_count']==6 and seed['analysis']['criterion_count']==3
            gates['wbs_'+lane+'_draft_blocked']=seed['analysis']['structure_ready'] and not seed['decomposition_ready']
        run=server.enqueue_decomposition(pid,'fixture-author',dict(wbs_version=base['version'],wbs_digest=base['digest'],confirmation='RUN AI DECOMPOSITION'))['queue_id']
        require(server.dispatch_one(),'Decomposition queue did not dispatch')
        with server.db() as c:
            state=dj.latest(c,pid)
            calls=[dict(x) for x in c.execute('SELECT agent_id,lane,provider,model,purpose,status,coverage,total_tokens FROM ai_usage WHERE project_id=? AND run_id=? ORDER BY rowid',(pid,run))]
            entry=dict(discovery=state,calls=calls,draft_blocked=gates['wbs_'+lane+'_draft_blocked'])
            report['wbs']['lanes'][lane]=entry
            e=state['evidence'] if state else None
            gates['wbs_'+lane+'_ai_ready']=bool(state and state['ready'] and state['status']=='succeeded' and not state['stale'] and e and e['origin']=='model_generated')
            gates['wbs_'+lane+'_no_auto_write']=w.latest(c,pid)['version']==base['version'] and w.latest(c,pid)['digest']==base['digest']
            gates['wbs_'+lane+'_calls']=bool(e and 2<=len(calls)<=4 and len(calls)==e['call_count'] and e['ledger_valid'] and
                [(x['lane'],x['purpose']) for x in calls]==[(lane,a['phase']) for b in e['history'] for a in b['attempts']] and all(
                x['provider']=='ollama' and x['model']==state['model']['model'] and x['agent_id']=='wbs-'+lane and x['status']=='ok' and x['coverage']=='complete' and x['total_tokens']>0 for x in calls))
            gates['wbs_'+lane+'_audit']=bool(e and e.get('wire')==d.WIRE and e.get('example_policy')==w.EXAMPLE_POLICY and e.get('instruction_policy')==w.INSTRUCTION_POLICY and e.get('context_policy')==d.CONTEXT_POLICY and e['repair_audit_valid'] and e['wbs_version']==base['version'] and e['wbs_digest']==base['digest'] and e['source']==source)
            gates['wbs_'+lane+'_convergence']=bool(e and e['repair_audit_valid'] and all(a['valid'] and a.get('convergence',{}).get('passed') is True and a['convergence'].get('lost_scope_groups')==[] for b in e['history'] for a in b['attempts'] if a['phase']=='wbs_decompose_repair'))
            gates['wbs_'+lane+'_details']=False
            if gates['wbs_'+lane+'_ai_ready']:
                # Explicit fixture actor save of the exact AI candidate tests the
                # unchanged P6.2c save gate; not automatic adoption by the worker.
                saved=w.save(c,pid,'fixture-author',dict(source,expected_version=base['version'],document=e['candidate']),server.now())
                a=saved['analysis']
                gates['wbs_'+lane+'_details']=saved['decomposition_ready'] and not a['semantic_reviewed'] and not a['issues'] and not any(w.detail_contaminated(pkg[k]) for pkg in d.packages(saved['current']['document']).values() for k in w.DETAIL_FIELDS) and saved['current']['digest']==e['candidate_digest'] and all(len(t['implement'])==len(t['verify'])==1 for t in a['traceability'].values())
                entry.update(current=saved['current'],analysis=a,explicit_fixture_save=True)
    with server.db() as c:
        gates['wbs_no_adoption']=pp.latest(c,pid) is None and not pp.view(c,pid)['execution_ready']
        gates['wbs_database_integrity']=c.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not list(c.execute('PRAGMA foreign_key_check'))
        usage=usage_store.summary(c,pid,1)['totals'];cost=cost_store.summary(c,pid,1)['totals']
        count=len(report['calls'])+sum(len(v['calls']) for v in report['wbs']['lanes'].values())
        gates['wbs_token_ledger']=usage['requests']==usage['complete_calls']==count
        gates['wbs_local_cost']=cost['local_assumed_zero_calls']==count
        gates['wbs_no_budget_leak']=server.BUDGET_GUARD.view(c,all_projects=True)['totals']['held_calls']==0
        gates['wbs_no_active_inference']=server.CONCURRENCY.snapshot()['active']==0
        report['wbs'].update(token_usage=usage,cost=cost)
    report['wbs']['gate']='PASS' if all(gates.values()) else 'BLOCK'
    return all(gates.values())

def main():
    p=argparse.ArgumentParser();p.add_argument('--report',type=Path,required=True);p.add_argument('--confirm',required=True)
    a=p.parse_args()
    if a.confirm!='RUN LOCAL PLANNING' or a.report.exists():p.error('Explicit confirmation and new report required')
    report=dict(schema='orbit.offline-planning.v1',gate='BLOCK',source_commit=os.getenv('STRESS_SOURCE_COMMIT','unknown'))
    try:
        with tempfile.TemporaryDirectory() as d:
            os.environ.update(AI_COMPANY_DB=str(Path(d)/'planning.sqlite'),AI_PROVIDER='ollama',
                AI_PROVIDER_A='ollama',AI_PROVIDER_B='ollama',AI_MODEL_A='qwen2.5-coder:3b',AI_MODEL_B='qwen2.5:3b',
                AI_BASE_URL='http://127.0.0.1:11434/v1',AI_BASE_URL_A='http://127.0.0.1:11434/v1',AI_BASE_URL_B='http://127.0.0.1:11434/v1',
                AI_API_KEY='',AI_API_KEY_A='',AI_API_KEY_B='',AI_TIMEOUT='300',ORBIT_BUDGET_MODE='enforce',
                ORBIT_MONTHLY_GLOBAL_USD='0',ORBIT_MAX_RUN_CALLS='4')
            import server,auth_store,product_requirements as pr,project_planning as pp,planning_jobs as pj,model_provider as mp,usage_store,cost_store
            server.init_db()
            doc=dict(problem='Readers need to save and retrieve links securely',goals=['Save and list links'],users=['Readers'],
                scope=['Web link storage and listing in existing projects'],out_of_scope=['Mobile','Sharing','Registration','Project management'],
                assumptions=['Authenticated project membership is provided'],open_questions=[],
                requirements=[
                    dict(id='REQ-1',kind='functional',description='Save URL in own project',priority='must',acceptance=['A saved URL is persisted']),
                    dict(id='REQ-2',kind='functional',description='List saved links in own project',priority='must',acceptance=['Saved URL appears in list']),
                    dict(id='REQ-3',kind='nonfunctional',description='Enforce project isolation',priority='must',acceptance=['Unauthorized cross-project read is denied'])],
                stories=[dict(id='US-1',actor='Reader',goal='Save and retrieve own links securely',benefit='Find links later',requirements=['REQ-1','REQ-2','REQ-3'])])
            with server.db() as c:
                pid=server.create_project('Planning fixture',doc['problem'],'Web app',c)
                auth_store.create_user(c,'fixture-author','local-fixture-password');auth_store.grant(c,'fixture-author',pid,'owner')
                row=pr.save(c,pid,'fixture-author',dict(expected_version=0,document=doc),server.now())['current']
                row=pr.approve(c,pid,'fixture-author',dict(version=row['version'],digest=row['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS'),server.now())['current']
            lanes=mp.require_distinct_real(server.provider_snapshot()[1])
            require(all(v.provider=='ollama' and v.base_url=='http://127.0.0.1:11434/v1' for v in lanes.values()),'Nonlocal provider forbidden')
            # Explicit fixture-author decisions: exact approved evidence and literal action/object groups.
            policy=dict(forbidden=['register','sign up','create projects'],rules=[
                dict(requirement='REQ-1',kind='implement',evidence=doc['requirements'][0]['description'],matches=[['save','store','persist','saving','storing','persisting','insert'],['url','urls','link','links']]),
                dict(requirement='REQ-1',kind='verify',evidence=doc['requirements'][0]['acceptance'][0],matches=[['save','saved','persist','persisted','saving','persists','storage'],['url','urls','link','links'],['save','saved','persist','saving','storage']]),
                dict(requirement='REQ-2',kind='implement',evidence=doc['requirements'][1]['description'],matches=[['list','display','retrieve','view','listing','retrieval','show','fetch'],['url','urls','link','links']]),
                dict(requirement='REQ-2',kind='verify',evidence=doc['requirements'][1]['acceptance'][0],matches=[['list','listed','listing','display','displayed','retrieve','view','fetch'],['url','urls','link','links'],['list','listed','listing','display','retrieve','view','fetch']]),
                dict(requirement='REQ-3',kind='implement',evidence=doc['requirements'][2]['description'],matches=[['isolation','isolate','authorization','unauthorized','access','deny','restrict','security'],['project','projects']]),
                dict(requirement='REQ-3',kind='verify',evidence=doc['requirements'][2]['acceptance'][0],matches=[['isolation','unauthorized','denied','deny','cannot','restrict','access'],['project','projects']])])
            run=server.enqueue_planning(pid,'fixture-author',dict(requirements_version=row['version'],requirements_digest=row['digest'],confirmation='RUN AI PLANNING',scope_contract=policy))['queue_id']
            require(server.dispatch_one(),'Queue did not dispatch')
            with server.db() as c:
                state=pj.latest(c,pid);report['discovery']=state
                calls=[dict(r) for r in c.execute('SELECT agent_id,lane,model,provider,purpose,status,coverage,total_tokens FROM ai_usage WHERE run_id=? ORDER BY rowid',(run,))]
                report['calls']=calls
                usage=usage_store.summary(c,pid,1)['totals'];cost=cost_store.summary(c,pid,1)['totals']
                report.update(token_usage=usage,cost=cost)
                guard=server.BUDGET_GUARD.view(c,all_projects=True)
                integrity=c.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not list(c.execute('PRAGMA foreign_key_check'))
                untouched=pp.latest(c,pid) is None and not pp.view(c,pid)['execution_ready']
                snapshot=pj.input_for(c,pid,run)
            require(state['evidence'] is not None,'Planning evidence missing: '+state['reason'])
            e=state['evidence'];gates={}
            gates['source_binding']=e['source_digest']==row['digest'] and e['source_version']==row['version'] and json.loads(snapshot['snapshot'])['document']==doc and json.loads(snapshot['snapshot'])['scope_contract']==policy
            # Canonical PRD validator may preserve list order; all references are checked again.
            gates['scope_repair_audit']=bool(state['ready'] and state['status']=='succeeded' and e['scope_ready'] and e['repair_audit_valid'] and all(x['passed'] for x in e['scope_findings'].values()) and all(x['passed'] for x in e['scope_convergence'].values()))
            gates['content_quality']=bool(e['content_ready'] and all(x['passed'] for x in e['content_findings'].values()) and set(e['content_findings'])=={'A','B'})
            gates['two_proposals']=set(e['proposals'])=={'A','B'} and e['structurally_ready'] and not e['semantic_reviewed']
            gates['coverage_and_graph']=all(len(pp.analyze(v,doc)['traceability'])==3 and len(v['tasks'])==6 for v in e['proposals'].values())
            gates['no_estimates']=all(t['effort_minutes'] is None for v in e['proposals'].values() for t in v['tasks'])
            # An independent fixture check is deliberately stronger than ID coverage alone.
            import re
            patterns={'REQ-1':r'\b(save|store|persist|saving|storing|persisting|insert|create|saved|storage)\b',
                'REQ-2':r'\b(list|display|retrieve|view|listing|retrieval|show|fetch|listed)\b',
                'REQ-3':r'\b(isolation|isolat\w*|authoriz\w*|unauthoriz\w*|access|permission\w*|den\w*|restrict\w*|security)\b'}
            gates['fixture_content']=all(re.search(patterns[t['requirements'][0]],t['title'],re.I) and
                not re.search(r'\b(registration|register|sign up|mobile|sharing|project management|create projects)\b',t['title'],re.I)
                for v in e['proposals'].values() for t in v['tasks'])
            expected=[(lane,x['phase']) for lane in 'AB' for x in e['attempts'][lane]]
            gates['real_calls']=2<=len(calls)<=4 and [(x['lane'],x['purpose']) for x in calls]==expected and all(
                x['agent_id']=='pm-'+x['lane'] and x['provider']=='ollama' and x['model']==lanes[x['lane']].model
                and x['status']=='ok' and x['coverage']=='complete' and x['total_tokens']>0 for x in calls)
            gates['model_provenance']=state['models']=={k:dict(provider=v.provider,model=v.model) for k,v in lanes.items()}
            gates['token_ledger']=usage['requests']==usage['complete_calls']==len(calls)
            gates['local_cost']=cost['local_assumed_zero_calls']==len(calls)
            gates['no_budget_leak']=guard['totals']['held_calls']==0
            gates['no_active_inference']=server.CONCURRENCY.snapshot()['active']==0
            gates['no_auto_adoption']=untouched;gates['database_integrity']=integrity
            report['gates']=gates
            require(all(gates.values()),'PM acceptance gate failed')
            gates['wbs_acceptance']=wbs_acceptance(server,pid,report)
            require(gates['wbs_acceptance'],'WBS acceptance gate failed')
            report['gate']='PASS'
    except Exception as e:
        report['error_type']=type(e).__name__;report['error']=str(e) if isinstance(e,(ValueError,RuntimeError)) else 'See test output'
    finally:
        with a.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
        print(json.dumps(report,indent=2))
    return 0 if report['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
