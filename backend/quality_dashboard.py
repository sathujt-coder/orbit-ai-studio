"""Read-only quality summary; never expose sandbox stdout or credentials."""
from verification_factory import list_reports
from web_candidate_selection import compare

def quality_summary(conn, job):
    entries=list_reports(conn,job['id'],1)
    result={'job_id':job['id'],'status':job['status'],'reviews':{},'verification':None,
            'selection_ready':False,'draft_pr':None,'production_approved':False}
    for key in ('review_a','review_b'):
        review=job.get(key) or {}
        result['reviews'][key]={'verdict':review.get('verdict'),'score':review.get('score')}
    if entries:
        entry=entries[0];report=entry['report']
        result['verification']={'id':entry['id'],'profile':report.get('profile','legacy'),
            'gate':report.get('gate'),'created_at':entry['created_at'],
            'lanes':{k:{'status':v.get('status'),'steps':[{'name':s.get('step'),'passed':s.get('passed'),'test_count':s.get('test_count')} for s in v.get('steps',[])]} for k,v in report.get('lanes',{}).items()}}
        try:
            compare(job,report)
            result['selection_ready']=True
        except (ValueError,PermissionError,KeyError,TypeError):
            pass
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='code_pr_exports'").fetchone():
        row=conn.execute('SELECT status,pr_number FROM code_pr_exports WHERE job_id=?',(job['id'],)).fetchone()
        if row: result['draft_pr']=dict(row)
    return result
