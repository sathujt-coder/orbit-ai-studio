"""Deny-by-default HTTP route authorization for local ORBIT."""
import re
from urllib.parse import parse_qs
import auth_store
import auth_http
import hmac
import provider_settings

ID=r'[A-Za-z0-9_-]{1,100}'
def resource_project(c,table,identifier):
    # Table names are fixed by the route policy, never supplied by clients.
    row=c.execute('SELECT project_id FROM '+table+' WHERE id=?',(identifier,)).fetchone()
    return row[0] if row else ''
def scope(c,method,path,query='',body=None):
    body=body or {}
    if method=='GET':
        if path=='/api/provider/routing':return ('','provider_routing_read')
        if path=='/api/provider/settings':return ('','provider_settings_read')
        if path=='/api/provider/usage':return ('','provider_usage_read')
        if path=='/api/provider/resources':return ('','provider_resources_read')
        if path in ('/api/provider/cost','/api/provider/rates'):return ('','provider_cost_read')
        if path in ('/api/bootstrap','/api/github/status'):return ('','authenticated')
        if path=='/api/chat':return (parse_qs(query).get('project_id',[''])[0],'read')
        m=re.fullmatch(r'/api/projects/('+ID+r')/queue(?:/'+ID+r')?',path)
        if m:return (m[1],'read')
        m=re.fullmatch(r'/api/projects/('+ID+r')/(state|coding|github|members|audit|acceptance|usage|cost|routing)',path)
        if m:return (m[1], 'manage' if m[2] in ('members','audit') else 'read')
        m=re.fullmatch(r'/api/coding/('+ID+r')(?:/(quality|verifications|download))?',path)
        if m:return (resource_project(c,'coding_jobs',m[1]),'read')
        m=re.fullmatch(r'/api/artifacts/('+ID+r')',path)
        if m:return (resource_project(c,'artifacts',m[1]),'read')
    if method=='POST':
        if path=='/api/provider/routing/preview':return ('','provider_routing_preview')
        if path=='/api/provider/resources/models':return ('','provider_resource_models')
        if path in ('/api/provider/settings','/api/provider/probe','/api/provider/models','/api/provider/rates'):
            return ('','provider_'+path.rsplit('/',1)[1])
        if path=='/api/projects':return ('','create')
        if path in ('/api/coding/start','/api/chat','/api/github/preview','/api/github/draft-pr'):
            pid=body.get('project_id','')
            return (pid if isinstance(pid,str) else '', {'/api/github/preview':'read','/api/github/draft-pr':'publish'}.get(path,'write'))
        m=re.fullmatch(r'/api/projects/('+ID+r')/acceptance/(evidence|signoff)',path)
        if m:return (m[1],'manage' if m[2]=='signoff' else 'approve')
        m=re.fullmatch(r'/api/projects/('+ID+r')/queue/'+ID+r'/(pause|resume|cancel|priority|retry)',path)
        if m:return (m[1],'write')
        m=re.fullmatch(r'/api/projects/('+ID+r')/(run|pause|members|budget)',path)
        if m:return (m[1],'manage' if m[2] in ('members','budget') else 'write')
        m=re.fullmatch(r'/api/stages/('+ID+r')/('+ID+r')/(approve|retry)',path)
        if m:return (m[1],'approve' if m[3]=='approve' else 'write')
    return None
def check(c,method,path,query,body,headers,port,transport=None):
    secure=bool(transport and transport.secure)
    origins=transport.origins(port) if transport else {f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    token=auth_http.token_from(headers,secure)
    user=auth_store.principal(c,token)
    if not user:
        auth_http.audit(c,'anonymous','http:'+method,'denied')
        return 401,None
    if method=='POST':
        csrf=headers.get('X-ORBIT-CSRF','')
        if headers.get('Origin') not in origins or not re.fullmatch('[0-9a-f]{64}',csrf) or not hmac.compare_digest(csrf,auth_http.csrf_for(token)):
            auth_http.audit(c,user,'csrf','denied')
            return 403,None
    target=scope(c,method,path,query,body)
    if target is None:return 404,None
    pid,action=target
    if action in ('authenticated','create'):return 200,(user,pid,action)
    if action.startswith('provider_'):
        if provider_settings.is_admin(user):return 200,(user,'',action)
        auth_http.audit(c,user,action,'denied');return 403,None
    if not pid or not c.execute('SELECT 1 FROM projects WHERE id=?',(pid,)).fetchone():
        auth_http.audit(c,user,'resource_scope','denied')
        return 403,None
    if not auth_store.authorize(c,user,pid,action):return 403,None
    return 200,(user,pid,action)

def set_member(c,actor,pid,target,role):
    if target==actor or role not in ('developer','reviewer','viewer','revoke'):
        raise PermissionError('Cannot change own role or grant ownership')
    existing=c.execute('SELECT role FROM auth_memberships WHERE user_id=? AND project_id=?',(target,pid)).fetchone()
    if existing and existing[0]=='owner':raise PermissionError('Owner role protected')
    if role=='revoke':
        c.execute('DELETE FROM auth_memberships WHERE user_id=? AND project_id=?',(target,pid))
    else:auth_store.grant(c,target,pid,role)
def visible_projects(c,user):
    return [dict(row) for row in c.execute('SELECT p.* FROM projects p JOIN auth_memberships m ON m.project_id=p.id WHERE m.user_id=? ORDER BY p.created_at DESC',(user,))]
