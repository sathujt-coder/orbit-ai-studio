import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import transport_security as t
import auth_http
class TLSTests(unittest.TestCase):
    def test_local_defaults(self):
        x=t.load({})
        self.assertTrue(t.request_allowed(x,{'Host':'localhost:8787'},8787,'127.0.0.1'))
        self.assertFalse(t.request_allowed(x,{'Host':'localhost:8787'},8787,'10.0.0.2'))
    def test_tls_origin_exact(self):
        x=t.load({'ORBIT_HTTPS_ORIGIN':'https://localhost:8443','ORBIT_TLS_CERT':'cert','ORBIT_TLS_KEY':'key'})
        self.assertTrue(t.request_allowed(x,{'Host':'localhost:8443','Origin':'https://localhost:8443'},8443,'10.0.0.2'))
        self.assertFalse(t.request_allowed(x,{'Host':'localhost:8443','Origin':'http://localhost:8443'},8443,'10.0.0.2'))
        self.assertFalse(t.request_allowed(x,{'Host':'bad.invalid','X-Forwarded-Host':'localhost:8443'},8443,'10.0.0.2'))
        self.assertIn('__Host-orbit_session=',auth_http.cookie('fixture',3600,True))
        self.assertIn('; Secure',auth_http.cookie('fixture',3600,True))
        self.assertEqual(auth_http.token_from({'Cookie':'orbit_session_v2=old'},True),'')
    def test_partial_config(self):
        with self.assertRaises(ValueError):t.load({'ORBIT_HTTPS_ORIGIN':'https://localhost:8443'})
