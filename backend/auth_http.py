"""Local HTTP authentication endpoints. Existing application routes not yet protected."""
import hashlib
import hmac
import secrets
import time
from http.cookies import SimpleCookie, CookieError
import auth_store

COOKIE='orbit_session'
def token_from(headers):
    try:
        cookie=SimpleCookie()
        cookie.load(headers.get('Cookie',''))
        return cookie[COOKIE].value if COOKIE in cookie else ''
    except (CookieError,ValueError):return ''
def csrf_for(token):
    return hashlib.sha256(('orbit-csrf-v1:'+token).encode()).hexdigest()
def cookie(token='',age=0):
    # Local HTTP only. Secure flag required when migrating to HTTPS.
    return f'{COOKIE}={token}; Path=/api; HttpOnly; SameSite=Strict; Max-Age={age}'
def session(c,headers):
    token=token_from(headers)
    user=auth_store.principal(c,token)
    if not user:return 401,{'error':'Authentication required'},{}
    return 200,{'user':user,'csrf_token':csrf_for(token)},{}
def audit(c,user,action,outcome):
    c.execute('INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,?)',(user,'',action,outcome,int(time.time())))
def handle(c,path,headers,body,port):
    if headers.get('Origin') not in {f'http://127.0.0.1:{port}',f'http://localhost:{port}'} or headers.get('X-ORBIT-UI')!='1':
        return 403,{'error':'Same-origin request required'},{}
    if not isinstance(body,dict):return 400,{'error':'Invalid body'},{}
    token=token_from(headers)
    if path=='/api/auth/login':
        user=body.get('user');password=body.get('password')
        if not isinstance(user,str) or len(user)>100 or not isinstance(password,str) or len(password)>256:
            return 400,{'error':'Invalid credentials'},{}
        # Global local-instance throttle; persists across restarts.
        recent=c.execute("SELECT COUNT(*) FROM auth_audit WHERE action='login' AND outcome='denied' AND created_at>?",(int(time.time())-60,)).fetchone()[0]
        if recent>=10:return 429,{'error':'Try again later'},{}
        try:new=auth_store.login(c,user,password)
        except PermissionError:
            audit(c,'anonymous','login','denied')
            return 401,{'error':'Invalid credentials'},{}
        if token:auth_store.logout(c,token)
        audit(c,user,'login','allowed')
        return 200,{'user':user,'csrf_token':csrf_for(new)},{'Set-Cookie':cookie(new,3600)}
    if path=='/api/auth/logout':
        user=auth_store.principal(c,token)
        if not user:return 401,{'error':'Authentication required'},{}
        if not hmac.compare_digest(headers.get('X-ORBIT-CSRF',''),csrf_for(token)):
            audit(c,user,'logout','denied')
            return 403,{'error':'CSRF validation failed'},{}
        auth_store.logout(c,token)
        audit(c,user,'logout','allowed')
        return 200,{'ok':True},{'Set-Cookie':cookie()}
    return 404,{'error':'Not found'},{}
