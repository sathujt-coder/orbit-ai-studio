#!/usr/bin/env python3
"""P6.1 offline acceptance of structured AI discovery and the revision/approval storage contract."""
import argparse, copy, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

IDEA=("A small web app for readers to save URLs and list their saved links. "
      "Users belong to separate projects; a user must not read links from another project. "
      "Only these features are in scope; no mobile app, sharing, or external integrations. "
      "Authenticated project membership is provided by the existing platform. "
      "A saved URL must appear in the list; an unauthorized cross-project read must be denied.")

# Explicit human-fixture decisions, not inferred by backend or copied from model output.
# The original IDEA is unchanged; exact evidence anchors and literal alternatives are
# the test author's scope contract. The independent original semantic checks remain.
SCOPE_CONTRACT=dict(rules=[
    dict(id='SC-1',kind='functional',required=True,evidence='save URLs',
        matches=[['save','saving','store','storing','persist','persisting'],['url','urls','link','links']]),
    dict(id='SC-2',kind='functional',required=True,evidence='list their saved links',
        matches=[['list','listing','display','view','retrieve'],['url','urls','link','links']]),
    dict(id='SC-3',kind='nonfunctional',required=True,evidence='an unauthorized cross-project read must be denied',
        matches=[['project','projects'],['deny','denied','unauthorized','prevent','restrict','isolation','cannot','only']]),
    dict(id='SC-4',kind='functional',required=False,evidence='an unauthorized cross-project read must be denied',
        matches=[['project','projects'],['deny','denied','unauthorized','prevent','restrict','isolation','cannot']])],
    forbidden=['register','registration','sign up','project management','manage projects','manage their projects',
        'manage own projects','create projects','create a project','delete projects','delete a project',
        'mobile app','sharing','external integrations'],
    nonblocking_questions=['How many users will use the app?','What is the average number of saved links per user?',
        'How will users access the app?'],
    # Test-author policy: descriptive observational counts are not MVP limits.
    deferred_metric_subjects=['users','saved links per user','projects per user'],
    problem_source='A small web app for readers to save URLs and list their saved links.')

def require(ok,message):
    if not ok:raise RuntimeError(message)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--report',type=Path,required=True);p.add_argument('--confirm',required=True)
    a=p.parse_args()
    if a.confirm!='RUN LOCAL REQUIREMENTS' or a.report.exists():p.error('Explicit confirmation and new report required')
    report={'schema':'orbit.offline-requirements.v1','gate':'BLOCK','scope':'synthetic durable queue AI discovery and explicit adoption; no HTTP or actual human approval','source_commit':os.getenv('STRESS_SOURCE_COMMIT','unknown')}
    try:
        with tempfile.TemporaryDirectory() as d:
            os.environ.update(AI_COMPANY_DB=str(Path(d)/'requirements.sqlite'),AI_PROVIDER='ollama',
                AI_PROVIDER_A='ollama',AI_PROVIDER_B='ollama',AI_MODEL_A='qwen2.5-coder:3b',
                AI_MODEL_B='qwen2.5:3b',AI_BASE_URL='http://127.0.0.1:11434/v1',
                AI_BASE_URL_A='http://127.0.0.1:11434/v1',AI_BASE_URL_B='http://127.0.0.1:11434/v1',
                AI_API_KEY='',AI_API_KEY_A='',AI_API_KEY_B='',AI_TIMEOUT='300',ORBIT_BUDGET_MODE='enforce',
                ORBIT_MONTHLY_GLOBAL_USD='0',ORBIT_MAX_RUN_CALLS='20')
            import server, model_provider as mp, usage_store, cost_store, product_requirements as pr
            import requirements_jobs as jobs, auth_store
            server.init_db()
            with server.db() as c:
                pid=server.create_project('Requirements fixture',IDEA,'Web app',c)
                auth_store.create_user(c,'fixture-author','local-fixture-password')
                auth_store.grant(c,'fixture-author',pid,'owner')
            lanes=mp.require_distinct_real(server.provider_snapshot()[1])
            require(all(l.provider=='ollama' and l.base_url=='http://127.0.0.1:11434/v1' for l in lanes.values()),'Nonlocal provider forbidden')
            run=server.enqueue_requirements(pid,'fixture-author',scope_contract=SCOPE_CONTRACT)['queue_id']
            require(server.dispatch_one(),'Queue did not dispatch')
            with server.db() as c:queued=jobs.latest(c,pid)
            report['queue_status']=queued['status'];report['queue_reason']=queued['reason']
            evidence=queued['evidence']
            report['discovery']=evidence
            with server.db() as c:
                report['attempts']=[dict(r) for r in c.execute('SELECT agent_id,lane,model,provider,purpose,status,coverage,total_tokens FROM ai_usage WHERE run_id=? ORDER BY rowid',(run,))]
            if not evidence:
                raise RuntimeError('No completed discovery evidence: '+queued['reason'])
            document=evidence['document']
            # Independent lightweight fixture checks; not a general semantic quality oracle.
            functional=' '.join(r['description']+' '+' '.join(r['acceptance']) for r in document['requirements'] if r['kind']=='functional').lower()
            nonfunctional=' '.join(r['description']+' '+' '.join(r['acceptance']) for r in document['requirements'] if r['kind']=='nonfunctional').lower()
            checks={'save':('save' in functional or 'store' in functional) and ('url' in functional or 'link' in functional),
                'list':any(k in functional for k in ('list','display','view','retrieve')),
                'isolation': 'project' in nonfunctional and any(k in nonfunctional for k in ('denied','deny','unauthorized','prevent','restrict','isolation','cannot','access','only'))}
            # Explicit scope checks on actual must/should/could features, not on assumptions
            # or out-of-scope text. This catches the observed registration/project CRUD creep.
            import re
            checks['no_new_registration_or_project_management']=not any(
                re.search(r'\b(register|registration|sign.up|create (?:a |new )?projects?|delete (?:a |existing )?projects?|manage (?:their |own )?projects?|project management)\b',
                    r['description']+' '+' '.join(r['acceptance']),re.I)
                for r in document['requirements'] if r['kind']=='functional')
            # A past false positive counted "saved" as an action. Require an actual
            # save/store/persist verb and link object within one functional requirement.
            checks['explicit_save_action']=any(
                re.search(r'\b(save|saving|store|storing|persist|persisting)\b',r['description']+' '+' '.join(r['acceptance']),re.I)
                and re.search(r'\b(urls?|links?)\b',r['description']+' '+' '.join(r['acceptance']),re.I)
                for r in document['requirements'] if r['kind']=='functional')
            report['fixture_checks']=checks
            report['final_review']=evidence['final_review']
            report['scope_findings']=evidence.get('scope_findings')
            report['scope_repair']=evidence.get('scope_repair')
            report['false_approval_detected']=evidence.get('false_approval_detected')
            report['no_op_repair']=evidence.get('no_op_repair')
            report['convergence']=evidence.get('convergence')
            report['review_audit']=evidence.get('review_audit')
            report['quality_revision']=evidence.get('quality_revision')
            report['ready_for_human_review']=evidence.get('ready_for_human_review')
            report['open_questions']=document['open_questions']
            require(all(checks.values()),'Essential fixture scope missing or unrequested scope added')
            require(queued['status']=='succeeded' and queued['can_adopt'],'Queued discovery did not pass review: '+queued['reason'])
            require(evidence['ready_for_human_review'],'Final review or open questions block adoption')
            import requirements_scope as sc
            require(sc.assess(document,sc.validate(IDEA,SCOPE_CONTRACT))['passed'],'Independent scope contract enforcement failed')
            require(jobs.quality_gate(evidence,sc.validate(IDEA,SCOPE_CONTRACT))[0],'Independent convergence gate failed')
            audits=evidence['review_audit']
            expected_reviews=[('requirements_cross_review','A'),('requirements_cross_review','B'),('requirements_final_review','B')]
            if evidence.get('scope_recheck'):expected_reviews.append(('requirements_scope_recheck','B'))
            if evidence.get('quality_revision') is not None:expected_reviews.append(('requirements_quality_recheck','B'))
            require([(x['phase'],x['lane']) for x in audits]==expected_reviews,'Review audit sequence mismatch')
            require(evidence['false_approval_detected']==any(x['false_approval'] for x in audits),'False approval audit mismatch')
            require(audits[-1]['document_digest']==sc.digest(document) and audits[-1]['scope_passed'],'Latest review is not bound to accepted content')
            require(evidence['convergence'] is None or evidence['convergence']['passed'],'Semantic convergence failed')
            with server.db() as c:
                adopted=jobs.adopt(c,pid,'fixture-author',dict(queue_id=run,digest=queued['digest'],
                    expected_version=0,confirmation='ADOPT AI REQUIREMENTS'),server.now())
                require(not adopted['planning_ready'] and jobs.latest(c,pid)['adopted_version']==1,'Adoption gate failed')
            def denied(fn):
                try:fn()
                except ValueError:return True
                return False
            def approval(row,**kw):
                return dict(version=row['version'],digest=row['digest'],confirmation='APPROVE PRODUCT REQUIREMENTS') | kw
            # Simulated authorized human adopts AI draft; this is not real human sign-off.
            with server.db() as c:
                blocked_doc=copy.deepcopy(document);blocked_doc['open_questions']=['Fixture unresolved decision']
                first=pr.save(c,pid,'fixture-author',dict(expected_version=1,document=blocked_doc),server.now())
                unresolved=denied(lambda:pr.approve(c,pid,'fixture-reviewer',approval(first['current']),server.now()))
                current=pr.save(c,pid,'fixture-author',dict(expected_version=2,document=document),server.now())
                row=current['current']
                stale=denied(lambda:pr.approve(c,pid,'fixture-reviewer',approval(first['current']),server.now()))
                wrong_digest=denied(lambda:pr.approve(c,pid,'fixture-reviewer',approval(row,digest='wrong'),server.now()))
                wrong_confirmation=denied(lambda:pr.approve(c,pid,'fixture-reviewer',approval(row,confirmation='yes'),server.now()))
                approved=pr.approve(c,pid,'fixture-reviewer',approval(row),server.now())
            with server.db() as c:
                persisted=pr.view(c,pid)
                revised=pr.save(c,pid,'fixture-author',dict(expected_version=3,document=document),server.now())
                usage=usage_store.summary(c,pid,1)['totals'];cost=cost_store.summary(c,pid,1)['totals']
                calls=[dict(r) for r in c.execute('SELECT agent_id,lane,model,provider,purpose,status,coverage,total_tokens FROM ai_usage WHERE run_id=? ORDER BY rowid',(run,))]
                guard=server.BUDGET_GUARD.view(c,all_projects=True)
                integrity=c.execute('PRAGMA integrity_check').fetchone()[0]
                foreign_keys=list(c.execute('PRAGMA foreign_key_check'))
            gates=dict(unresolved_blocked=unresolved,stale_blocked=stale,wrong_digest_blocked=wrong_digest,
                wrong_confirmation_blocked=wrong_confirmation,not_ready_before_approval=not current['planning_ready'],
                ready_after_approval=approved['planning_ready'],approval_persisted=persisted['planning_ready'] and persisted['current']['digest']==row['digest'],
                new_revision_invalidates=not revised['planning_ready'],database_integrity=integrity=='ok' and not foreign_keys)
            expected=[(dept+'-'+lane,dept+'_'+phase) for dept in ('research','ba')
                for phase in ('proposal','cross_review') for lane in 'AB']
            expected += [('po-A','requirements_proposal'),('po-B','requirements_proposal'),('po-A','requirements_cross_review'),
                ('po-B','requirements_cross_review'),('po-A','requirements_synthesis'),('po-B','requirements_final_review')]
            collaboration=evidence['collaboration']
            revised_quality=evidence.get('quality_revision') is not None
            if revised_quality:
                expected += [('po-A','requirements_quality_revision'),('po-B','requirements_quality_recheck')]
            scope_recheck=bool(evidence.get('scope_recheck'))
            if scope_recheck:
                expected += [('po-B','requirements_scope_recheck')]
            # Optional, bounded repair immediately after each document phase. No extra calls
            # or arbitrary retries can satisfy this sequence gate.
            index=0;sequence_ok=True;repairs=0
            for agent,phase in expected:
                if index>=len(calls) or (calls[index]['agent_id'],calls[index]['purpose'])!=(agent,phase):
                    sequence_ok=False;break
                index+=1
                if phase in ('requirements_proposal','requirements_synthesis','requirements_quality_revision') and index<len(calls) and (calls[index]['agent_id'],calls[index]['purpose'])==(agent,phase+'_repair'):
                    repairs+=1;index+=1
            report['repair_calls']=repairs
            report['quality_revision_calls']=2 if revised_quality else 0
            report['scope_recheck_calls']=int(scope_recheck)
            gates.update(real_calls=sequence_ok and index==len(calls) and len(calls)==14+repairs+(2 if revised_quality else 0)+int(scope_recheck) and not (scope_recheck and revised_quality) and repairs<=(4 if revised_quality else 3) and len(calls)<=20 and all(x['provider']=='ollama' and x['status']=='ok' and x['model']==lanes[x['lane']].model and x['coverage']=='complete' and x['total_tokens']>0 for x in calls),
                review_audit_complete=True,semantic_convergence=evidence['convergence'] is None or evidence['convergence']['passed'],
                scope_contract_enforced=evidence['scope_findings']['passed'] and not evidence['no_op_repair'] and evidence['scope_contract']==sc.validate(IDEA,SCOPE_CONTRACT),
                department_evidence=collaboration['research_mode']=='input_analysis_only' and all(
                    set(collaboration[d]['proposals'])==set(collaboration[d]['reviews'])=={'A','B'} for d in ('research','ba')),
                token_ledger=usage['requests']==usage['complete_calls']==len(calls),
                local_cost=cost['local_assumed_zero_calls']==len(calls), no_budget_leak=guard['totals']['held_calls']==0,
                no_active_inference=server.CONCURRENCY.snapshot()['active']==0)
            report.update(gates=gates,calls=calls,token_usage=usage,cost=cost)
            require(all(gates.values()),'Acceptance gate failed')
            report['gate']='PASS'
    except Exception as e:
        report['error_type']=type(e).__name__
        report['error']=str(e) if isinstance(e,(RuntimeError,ValueError)) else 'See test output'
    finally:
        with a.report.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2)
        print(json.dumps({k:v for k,v in report.items() if k!='discovery'},indent=2))
    return 0 if report['gate']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
