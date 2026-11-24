import sqlite3
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import auth_store as a
class AuthTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        a.ensure_schema(self.c)
        a.create_user(self.c,'alice','long-password-123')
        a.grant(self.c,'alice','project-a','reviewer')
    def tearDown(self):self.c.close()
    def test_login_logout(self):
        token=a.login(self.c,'alice','long-password-123')
        self.assertEqual(a.principal(self.c,token),'alice')
        a.logout(self.c,token)
        self.assertIsNone(a.principal(self.c,token))
    def test_wrong_password(self):
        with self.assertRaises(PermissionError):a.login(self.c,'alice','wrong-password-123')
    def test_scope_and_audit(self):
        self.assertTrue(a.authorize(self.c,'alice','project-a','approve'))
        self.assertFalse(a.authorize(self.c,'alice','project-b','read'))
        self.assertFalse(a.authorize(self.c,'alice','project-a','publish'))
        self.assertEqual(self.c.execute('SELECT outcome FROM auth_audit ORDER BY id').fetchall(),[('allowed',),('denied',),('denied',)])
    def test_expired(self):
        token=a.login(self.c,'alice','long-password-123')
        self.c.execute('UPDATE auth_sessions SET expires=0')
        self.assertIsNone(a.principal(self.c,token))
