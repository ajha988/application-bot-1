"""Local encrypted credential storage. Keys live only in expiring process memory."""
import base64
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import urlparse
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, SecretStr
from . import accounts

SESSIONS = {}
GUARD = threading.RLock()
TTL = 1800
FAILURES = []

def canonical(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise HTTPException(422,'Use an HTTPS career-site URL without credentials or a custom port')
    return parsed.hostname.lower(), parsed.path or '/'

def scope_matches(path, scope):
    return scope=='/' or path==scope or path.startswith(scope+'/')

def key_for(password,salt):
    return Fernet(base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256',password.encode(),salt,1200000,32)))

def scope_key(): return (accounts.user()['id'],accounts.persona()['id'])

def session(token):
    with GUARD:
        for old in list(SESSIONS):
            if SESSIONS[old]['expires']<time.monotonic(): del SESSIONS[old]
        item=SESSIONS.get(token)
        if not item or item.get('scope')!=scope_key(): raise HTTPException(423,'Unlock the credential vault first (sessions expire after 30 minutes)')
        return item['cipher']

def init(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS vault_meta(id INTEGER PRIMARY KEY, salt BLOB, verifier BLOB);
    CREATE TABLE IF NOT EXISTS credentials(id TEXT PRIMARY KEY, host TEXT, scope TEXT, label TEXT, secret BLOB, updated_at TEXT, UNIQUE(host,scope));''')

def credentials_for(db,url,token):
    cipher=session(token)
    host,path=canonical(url)
    with db() as c:
        rows=c.execute('SELECT * FROM credentials WHERE host=? ORDER BY length(scope) DESC',(host,)).fetchall()
        for row in rows:
            if scope_matches(path,row['scope']):
                try: return json.loads(cipher.decrypt(row['secret']))
                except InvalidToken: raise HTTPException(409,'Credential record could not be decrypted')
    return None

class Unlock(BaseModel):
    master_password: SecretStr
class Credential(BaseModel):
    login_url: str = Field(max_length=2000)
    scope: str = Field(default='/',max_length=500)
    label: str = Field(min_length=1,max_length=100)
    username: SecretStr
    password: SecretStr

def router(db,auth,now):
    api=APIRouter(prefix='/api/vault',dependencies=[])
    # All routes require the portal API token; secret operations also require an unlocked vault session.
    from fastapi import Depends
    api.dependencies=[Depends(auth)]
    @api.get('/status')
    def status(x_vault_session: str=Header(default='')):
        with db() as c: configured=c.execute('SELECT 1 FROM vault_meta').fetchone() is not None
        try: session(x_vault_session); unlocked=True
        except HTTPException: unlocked=False
        return {'configured':configured,'unlocked':unlocked,'session_minutes':30}
    @api.post('/unlock')
    def unlock(body: Unlock):
        with GUARD:
            FAILURES[:]=[t for t in FAILURES if time.monotonic()-t<60]
            if len(FAILURES)>=5: raise HTTPException(429,'Too many unlock attempts. Wait one minute before trying again.')
        password=body.master_password.get_secret_value()
        if not 12<=len(password)<=1024: raise HTTPException(422,'Master password must contain 12–1024 characters')
        with db() as c:
            meta=c.execute('SELECT * FROM vault_meta WHERE id=1').fetchone()
            salt=meta['salt'] if meta else secrets.token_bytes(16)
            cipher=key_for(password,salt)
            if meta:
                try: cipher.decrypt(meta['verifier'])
                except InvalidToken:
                    with GUARD: FAILURES.append(time.monotonic())
                    raise HTTPException(403,'Incorrect master password')
            else: c.execute('INSERT INTO vault_meta VALUES(1,?,?)',(salt,cipher.encrypt(b'application-bot-vault-v1')))
        token=secrets.token_urlsafe(32)
        with GUARD:
            FAILURES.clear()
            for old in list(SESSIONS):
                if SESSIONS[old]['scope']==scope_key(): del SESSIONS[old]
            SESSIONS[token]={'cipher':cipher,'expires':time.monotonic()+TTL,'scope':scope_key()}
        return {'session':token,'expires_in_seconds':TTL}
    @api.post('/lock')
    def lock(x_vault_session: str=Header(default='')):
        with GUARD:
            if SESSIONS.get(x_vault_session,{}).get('scope')==scope_key(): SESSIONS.pop(x_vault_session,None)
        return {'ok':True}
    @api.get('/credentials')
    def listing(x_vault_session: str=Header(default='')):
        session(x_vault_session)
        with db() as c:
            return [dict(r) for r in c.execute('SELECT id,host,scope,label,updated_at FROM credentials ORDER BY label')]
    @api.post('/credentials')
    def save(body: Credential,x_vault_session: str=Header(default='')):
        cipher=session(x_vault_session); host,path=canonical(body.login_url)
        scope=body.scope.rstrip('/') or '/'
        if not scope.startswith('/') or any(x in scope for x in ['..','%','?','#','\\']) or not scope_matches(path,scope):
            raise HTTPException(422,'Scope must be a plain path prefix containing the login URL; use a tenant path for shared ATS hosts')
        if not body.username.get_secret_value() or not body.password.get_secret_value(): raise HTTPException(422,'Username and password are required')
        secret=cipher.encrypt(json.dumps({'login_url':body.login_url,'host':host,'scope':scope,'username':body.username.get_secret_value(),'password':body.password.get_secret_value()}).encode())
        with db() as c:
            old=c.execute('SELECT id FROM credentials WHERE host=? AND scope=?',(host,scope)).fetchone()
            cid=old['id'] if old else secrets.token_hex(8)
            c.execute('INSERT OR REPLACE INTO credentials VALUES(?,?,?,?,?,?)',(cid,host,scope,body.label,secret,now()))
        return {'id':cid,'saved':True}
    @api.delete('/credentials/{cid}')
    def delete(cid,x_vault_session: str=Header(default='')):
        session(x_vault_session)
        with db() as c:
            if not c.execute('DELETE FROM credentials WHERE id=?',(cid,)).rowcount: raise HTTPException(404,'Credential not found')
        return {'ok':True}
    return api
