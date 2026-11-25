"""Read-only legacy quality evidence. Existing handoff gate remains authoritative."""
import hashlib
import github_bridge

def view(c,pid,stages,tasks,handoff):
    task_by_id={t['stage_id']:t for t in tasks}
    roles=[]
    for stage in stages:
        sid=stage['id'];task=task_by_id.get(sid,{})
        h=next(r for r in handoff['roles'] if r['stage_id']==sid)
        receipt=h.get('receipt')
        # Prefer newest recorded run, never borrow older votes for a new run.
        newest=c.execute("SELECT run_id FROM artifacts WHERE project_id=? AND stage_id=? AND kind IN ('draft','final') ORDER BY rowid DESC LIMIT 1",(pid,sid)).fetchone()
        rid=receipt['run_id'] if receipt else newest['run_id'] if newest else None
        final=c.execute("SELECT id,run_id,content FROM artifacts WHERE project_id=? AND stage_id=? AND kind='final' AND run_id=? ORDER BY rowid DESC LIMIT 1",(pid,sid,rid)).fetchone() if rid else None
        drafts=[dict(x) for x in c.execute("SELECT id,agent_id FROM artifacts WHERE project_id=? AND stage_id=? AND kind='draft' AND run_id=? ORDER BY rowid DESC",(pid,sid,rid))] if rid else []
        reviews=[dict(x) for x in c.execute("SELECT id,reviewer_id,author_id,verdict,score,feedback,created_at,run_id FROM reviews WHERE project_id=? AND stage_id=? AND run_id=? ORDER BY rowid DESC LIMIT 2",(pid,sid,rid))] if rid else []
        pairs={(x['reviewer_id'],x['author_id']) for x in reviews}
        checks=[]
        def check(key,status):checks.append(dict(key=key,status=status))
        check('independent_drafts','PASS' if {x['agent_id'] for x in drafts}=={sid+'-A',sid+'-B'} else 'PENDING')
        check('cross_review_pairs','PASS' if len(reviews)==2 and pairs==github_bridge.EXPECTED_PAIRS(sid) else 'BLOCK' if len(reviews)==2 else 'PENDING')
        for lane in ('A','B'):
            match=[x for x in reviews if x['reviewer_id']==sid+'-'+lane and x['author_id']==sid+'-'+('B' if lane=='A' else 'A')]
            check('review_'+lane,'PASS' if len(match)==1 and match[0]['verdict']=='APPROVE' and type(match[0]['score']) is int and match[0]['score']>=80 else 'BLOCK' if match else 'PENDING')
        check('final_artifact','PASS' if final and len(final['content'].encode('utf-8'))<=200000 else 'BLOCK' if final else 'PENDING')
        check('human_approval','NOT_REQUIRED' if not stage['approval'] else 'PASS' if task.get('status')=='approved' and final and task.get('approved_at') else 'PENDING')
        check('upstream_sources','PASS' if h['input_status'] in ('project_idea','reviewed_sources_available') else 'BLOCK')
        check('receipt_currency','BLOCK' if h['consumption_status'] in ('STALE','INVALID') else 'PASS' if receipt and h['consumption_status'] in ('DRAFTS_RETURNED','DEMO_DRAFTS') else 'NOT_RECORDED' if not receipt else 'PENDING')
        output=h['output']
        # Never upgrade the existing authoritative gate; stale evidence has its
        # own visual warning even when legacy output eligibility is still true.
        state='STALE' if h['consumption_status']=='STALE' else 'INVALID' if h['consumption_status']=='INVALID' else 'REVIEWED_OUTPUT' if output['status']=='reviewed_output' and output['run_id']==rid else 'BLOCK' if task.get('status') in ('needs_revision','awaiting_approval','done','approved') or any(x['status']=='BLOCK' for x in checks) else 'PENDING'
        roles.append(dict(stage_id=sid,run_id=rid,state=state,mode=receipt.get('mode') if receipt else None,
            checks=checks,reviews=reviews,drafts=drafts,final=dict(id=final['id'],run_id=final['run_id'],content_digest=hashlib.sha256(final['content'].encode('utf-8')).hexdigest()) if final else None,
            output_eligibility=output['status'],output_reason=output['reason'],approved_at=task.get('approved_at') if task.get('status')=='approved' else None,
            minimum_review_score=80,execution_authorized=False))
    return dict(schema='orbit.studio-quality.v1',project_id=pid,scope='legacy_pipeline',roles=roles,
        real_ai_acceptance='NOT_ASSESSED',model_qualification='NOT_ASSESSED',system_acceptance='NOT_ASSESSED',production_release_authorized=False)
