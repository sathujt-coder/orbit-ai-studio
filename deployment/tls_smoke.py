#!/usr/bin/env python3
"""HTTPS smoke against a local isolated container with explicitly trusted test cert."""
import json,ssl,sys,urllib.request,urllib.error
from http.cookiejar import CookieJar
origin=sys.argv[2] if len(sys.argv)>2 else 'https://localhost:8443'
context=ssl.create_default_context(cafile=sys.argv[1])
jar=CookieJar()
opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),urllib.request.HTTPCookieProcessor(jar))
def call(path,body=None,csrf=None,expected=200,request_origin=origin):
    h={'Origin':request_origin,'X-ORBIT-UI':'1','Content-Type':'application/json'}
    if csrf:h['X-ORBIT-CSRF']=csrf
    r=urllib.request.Request(origin+path,headers=h,data=None if body is None else json.dumps(body).encode())
    try:
        with opener.open(r,timeout=10) as response:
            assert response.status==expected
            assert response.headers['Strict-Transport-Security']
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        assert e.code==expected,(e.code,expected)
        return {}
assert call('/healthz')['status']=='ok'
call('/api/bootstrap',expected=401)
session=call('/api/auth/login',{'user':'ci-tls-user','password':'fixture-tls-password'})
assert any(c.name=='__Host-orbit_session' and c.secure and c.path=='/' for c in jar)
call('/api/auth/session')
call('/api/projects',{'name':'TLS fixture','idea':'Verify TLS and CSRF gates'},expected=403)
call('/api/projects',{'name':'TLS fixture','idea':'Verify TLS and CSRF gates'},csrf=session['csrf_token'],expected=403,request_origin='https://wrong.invalid')
assert call('/api/projects',{'name':'TLS fixture','idea':'Verify TLS and CSRF gates'},csrf=session['csrf_token'],expected=201)['project_id']
call('/api/auth/logout',{},csrf=session['csrf_token'])
call('/api/auth/session',expected=401)
print('TLS container smoke PASS: verified certificate, Secure cookie, authorization and CSRF')
