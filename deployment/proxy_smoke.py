#!/usr/bin/env python3
"""Local smoke: verify peer TLS, login throttling and untrusted Host rejection."""
import ssl,sys,urllib.request,urllib.error,json
origin='https://localhost:9443'
ctx=ssl.create_default_context(cafile=sys.argv[1])
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))
def request(path,headers=None,data=None):
    req=urllib.request.Request(origin+path,headers=headers or {},data=data)
    try:
        with opener.open(req,timeout=10) as r:return r.status
    except urllib.error.HTTPError as e:
        code=e.code;e.close();return code
assert request('/healthz')==200
assert request('/healthz',{'Host':'attacker.invalid','X-Forwarded-Host':'localhost:9443'})==421
headers={'Origin':origin,'Content-Type':'application/json','X-ORBIT-UI':'1'}
body=json.dumps({'user':'missing-ci-user','password':'fixture-invalid-password'}).encode()
statuses=[request('/api/auth/login',headers,body) for _ in range(12)]
assert 401 in statuses and 429 in statuses,statuses
assert request('/healthz')==200
print('PROXY SMOKE PASS: trusted TLS, Host enforcement and 429 login rate limit',statuses)
