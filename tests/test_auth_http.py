import sqlite3
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import auth_store,auth_http
class AuthHTTPTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        auth_store.ensure_schema(self.c)
        auth_store.create_user(self.c,'alice','long-password-123')
        self.h={'Origin':'http://127.0.0.1:8787','X-ORBIT-UI':'1'}
    def tearDown(self):self.c.close()
    def login(self):
        status,data,headers=auth_http.handle(self.c,'/api/auth/login',self.h,{'user':'alice','password':'long-password-123'},8787)
        self.assertEqual(status,200)
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.h['Cookie']=headers['Set-Cookie'].split(';')[0]
        return data
    def test_session_logout(self):
        data=self.login()
        self.assertEqual(auth_http.session(self.c,self.h)[0],200)
        self.assertEqual(auth_http.handle(self.c,'/api/auth/logout',self.h,{},8787)[0],403)
        self.h['X-ORBIT-CSRF']=data['csrf_token']
        self.assertEqual(auth_http.handle(self.c,'/api/auth/logout',self.h,{},8787)[0],200)
        self.assertEqual(auth_http.session(self.c,self.h)[0],401)
    def test_cross_origin(self):
        self.h['Origin']='https://evil.invalid'
        self.assertEqual(auth_http.handle(self.c,'/api/auth/login',self.h,{},8787)[0],403)
    def test_wrong_password(self):
        self.assertEqual(auth_http.handle(self.c,'/api/auth/login',self.h,{'user':'alice','password':'wrong-password-123'},8787)[0],401)
    def test_throttle(self):
        for _ in range(10):auth_http.audit(self.c,'anonymous','login','denied')
        self.assertEqual(auth_http.handle(self.c,'/api/auth/login',self.h,{'user':'alice','password':'long-password-123'},8787)[0],429)
