"""Read-only evidence of legacy stage handoff eligibility; never dispatch authority.

Legacy pipeline consumes truncated preceding finals without a durable input receipt.
Do not claim actual consumption, immutable historical binding or production approval.
"""
import hashlib
import github_bridge

def view(c,pid,stages,tasks):
    by_id={t['stage_id']:t for t in tasks}
    outputs=[]
    for stage in stages:
        sid=stage['id'];task=by_id.get(sid)
        entry=dict(stage_id=sid,status='blocked',reason='stage_not_complete',
                   artifact_id=None,run_id=None,content_digest=None,version=None,
                   execution_authorized=False)
        # Human-gated stages must actually be approved, not merely done.
        if task and task['status'] in ('done','approved') and (not stage['approval'] or task['status']=='approved'):
            latest=c.execute("SELECT id FROM artifacts WHERE project_id=? AND stage_id=? AND kind='final' ORDER BY rowid DESC LIMIT 1",(pid,sid)).fetchone()
            if latest:
                try:
                    artifact=github_bridge.reviewed_artifact(c,pid,latest['id'])
                    # Reject a final belonging to a superseded run even when a
                    # newer attempt has not produced a final yet.
                    newest=c.execute("SELECT run_id FROM artifacts WHERE project_id=? AND stage_id=? AND kind IN ('draft','final') ORDER BY rowid DESC LIMIT 1",(pid,sid)).fetchone()
                    if not newest or newest['run_id']!=artifact['run_id']:raise ValueError('Superseded run')
                    version=c.execute("SELECT COUNT(*) FROM artifacts WHERE project_id=? AND stage_id=? AND kind='final'",(pid,sid)).fetchone()[0]
                    entry.update(status='reviewed_output',reason=None,artifact_id=artifact['id'],
                        run_id=artifact['run_id'],content_digest=hashlib.sha256(artifact['content'].encode('utf-8')).hexdigest(),version=version)
                except (ValueError,TypeError,KeyError):entry['reason']='review_or_source_invalid'
            else:entry['reason']='missing_final'
        outputs.append(entry)
    roles=[]
    for i,stage in enumerate(stages):
        previous=outputs[:i]
        roles.append(dict(stage_id=stage['id'],output=outputs[i],inputs=previous,
            input_status='project_idea' if not previous else 'reviewed_sources_available' if all(x['status']=='reviewed_output' for x in previous) else 'blocked',
            consumption_status='NOT_RECORDED',execution_authorized=False))
    return dict(schema='orbit.studio-handoff.v1',project_id=pid,scope='legacy_pipeline',
        roles=roles,production_release_authorized=False)
