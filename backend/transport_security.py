"""Explicit TLS deployment configuration; never trust forwarded headers."""
import ipaddress
import re
import ssl
from urllib.parse import urlsplit
from dataclasses import dataclass

@dataclass(frozen=True)
class Transport:
    origin:str
    cert:str
    key:str
    @property
    def secure(self):return bool(self.origin)
    def origins(self,port):
        return {self.origin} if self.secure else {f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    def hosts(self,port):
        return {urlsplit(x).netloc for x in self.origins(port)}
    def context(self):
        if not self.secure:raise ValueError('TLS not configured')
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert,self.key)
        return context

def load(env):
    origin=env.get('ORBIT_HTTPS_ORIGIN','')
    cert=env.get('ORBIT_TLS_CERT','')
    key=env.get('ORBIT_TLS_KEY','')
    if not any((origin,cert,key)):return Transport('','','')
    if not all((origin,cert,key)):raise ValueError('HTTPS origin, TLS certificate and key must all be configured')
    try:
        u=urlsplit(origin)
        port=u.port
        if u.scheme!='https' or not u.hostname or u.username is not None or u.password is not None or u.path or u.query or u.fragment or u.netloc!=u.netloc.lower():raise ValueError()
        if not re.fullmatch(r'[a-z0-9.-]+',u.hostname) or any(ord(ch)<33 or ord(ch)==127 for ch in origin):raise ValueError()
        if u.netloc != u.hostname+((':'+str(port)) if port and port!=443 else ''):raise ValueError()
    except ValueError:raise ValueError('HTTPS origin must be canonical, e.g. https://localhost:8443') from None
    return Transport(origin,cert,key)

def request_allowed(transport,headers,port,peer):
    try:
        if not transport.secure and not ipaddress.ip_address(peer).is_loopback:return False
    except ValueError:return False
    if headers.get('Host','').lower() not in transport.hosts(port):return False
    origin=headers.get('Origin')
    return origin is None or origin in transport.origins(port)
