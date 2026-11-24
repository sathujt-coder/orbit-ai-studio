"""Local authentication primitives. No HTTP session integration yet."""
import hashlib
import hmac
import secrets
import time
import re

ROLES={'owner':{'read','write','approve','publish','manage'},'developer':{'read','write'},'reviewer':{'read','approve'},'viewer':{'read'}}
def ensure_schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS auth_users(id TEXT PRIMARY KEY,password_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1)')
    c.execute('CREATE TABLE IF NOT EXISTS auth_memberships(user_id TEXT NOT NULL,project_id TEXT NOT NULL,role TEXT NOT NULL,PRIMARY KEY(user_id,project_id))')
    c.execute('CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires INTEGER NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS auth_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,project_id TEXT NOT NULL,action TEXT NOT NULL,outcome TEXT NOT NULL,created_at INTEGER NOT NULL)')
def password_hash(password):
    if not isinstance(password,str) or not 12<=len(password)<=256: raise ValueError('Password length 12-256 required')
    salt=secrets.token_bytes(16)
    return salt.hex()+':'+hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()
def check_password(password,stored):
    if not isinstance(password,str) or not 12<=len(password)<=256:return False
    try:
        salt,digest=stored.split(':')
        actual=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError):return False
def create_user(c,user,password):
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{3,100}',user):raise ValueError('Invalid user')
    c.execute('INSERT INTO auth_users(id,password_hash) VALUES(?,?)',(user,password_hash(password)))
def grant(c,user,project,role):
    if role not in ROLES:raise ValueError('Unknown role')
    if not c.execute('SELECT 1 FROM auth_users WHERE id=? AND active=1',(user,)).fetchone():raise ValueError('Unknown user')
    c.execute('INSERT INTO auth_memberships VALUES(?,?,?) ON CONFLICT(user_id,project_id) DO UPDATE SET role=excluded.role',(user,project,role))
def login(c,user,password):
    row=c.execute('SELECT password_hash FROM auth_users WHERE id=? AND active=1',(user,)).fetchone()
    if not row or not check_password(password,row[0]):raise PermissionError('Invalid credentials')
    token=secrets.token_urlsafe(32)
    c.execute('INSERT INTO auth_sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user,int(time.time())+3600))
    return token
def principal(c,token):
    if not isinstance(token,str) or len(token)>128:return None
    row=c.execute('SELECT s.user_id FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),int(time.time()))).fetchone()
    return row[0] if row else None
def logout(c,token):
    c.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
def authorize(c,user,project,action):
    row=c.execute('SELECT m.role FROM auth_memberships m JOIN auth_users u ON u.id=m.user_id WHERE m.user_id=? AND m.project_id=? AND u.active=1',(user,project)).fetchone()
    allowed=bool(row and action in ROLES.get(row[0],set()))
    c.execute('INSERT INTO auth_audit(actor,project_id,action,outcome,created_at) VALUES(?,?,?,?,?)',(user or 'anonymous',project,action,'allowed' if allowed else 'denied',int(time.time())))
    return allowed
