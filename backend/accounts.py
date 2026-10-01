"""Account identity and persona ownership are checked before workspace access."""
import base64
import hashlib
import hmac
import secrets
import sqlite3
import time
from contextlib import contextmanager
from contextvars import ContextVar
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, SecretStr

CURRENT_USER=ContextVar('account',default=None)
CURRENT_PERSONA=ContextVar('persona',default=None)
ATTEMPTS={}

@contextmanager
def database(root):
    root.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(root/'accounts.sqlite',timeout=20)
    c.row_factory=sqlite3.Row
    try:
        c.execute('BEGIN IMMEDIATE');yield c;c.commit()
    except Exception: c.rollback();raise
    finally: c.close()

def init(root):
    with database(root) as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,created_at REAL);
        CREATE TABLE IF NOT EXISTS account_sessions(token_hash TEXT PRIMARY KEY,user_id TEXT,csrf TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS personas(id TEXT PRIMARY KEY,user_id TEXT,name TEXT,domain TEXT,created_at REAL);
        CREATE TABLE IF NOT EXISTS ingest_keys(token_hash TEXT PRIMARY KEY,user_id TEXT,persona_id TEXT,created_at REAL);''')
        c.execute('CREATE TABLE IF NOT EXISTS job_routes(job_id TEXT PRIMARY KEY,user_id TEXT,persona_id TEXT)')

def password_hash(value,salt=None):
    salt=salt or secrets.token_bytes(16)
    key=hashlib.pbkdf2_hmac('sha256',value.encode(),salt,1200000)
    return base64.b64encode(salt).decode()+':'+base64.b64encode(key).decode()
def verify(value,encoded):
    salt,_=encoded.split(':')
    return hmac.compare_digest(password_hash(value,base64.b64decode(salt)),encoded)
def user():
    item=CURRENT_USER.get()
    if not item: raise HTTPException(401,'Sign in to your account')
    return item
def persona():
    item=CURRENT_PERSONA.get()
    if not item: raise HTTPException(400,'Choose a persona first')
    return item

def identify(root,request):
    bearer=request.headers.get('authorization','')
    raw=bearer[7:] if bearer.startswith('Bearer ') else request.cookies.get('app_session','')
    if not raw: raise HTTPException(401,'Sign in to your account')
    hashed=hashlib.sha256(raw.encode()).hexdigest()
    with database(root) as c:
        row=c.execute('SELECT s.*,u.username FROM account_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',(hashed,time.time())).fetchone()
        if row:
            if not bearer and request.method not in {'GET','HEAD','OPTIONS'} and not hmac.compare_digest(request.headers.get('x-csrf-token',''),row['csrf']):
                raise HTTPException(403,'Session security token missing; sign in again')
            return {'id':row['user_id'],'username':row['username'],'csrf':row['csrf'],'key_persona':None}
        row=c.execute('SELECT k.*,u.username FROM ingest_keys k JOIN users u ON u.id=k.user_id WHERE token_hash=?',(hashed,)).fetchone()
        if row and request.method=='POST' and request.url.path in {'/api/jobs/ingest','/api/email/events'}:
            return {'id':row['user_id'],'username':row['username'],'csrf':None,'key_persona':row['persona_id']}
    raise HTTPException(401,'Session expired or invalid credentials')

def owned(root,uid,pid):
    with database(root) as c:
        row=c.execute('SELECT * FROM personas WHERE id=? AND user_id=?',(pid,uid)).fetchone()
        if not row: raise HTTPException(404,'Persona not found')
        return dict(row)

class Login(BaseModel):
    username: str = Field(min_length=3,max_length=80,pattern=r'^[a-zA-Z0-9_.@+-]+$')
    password: SecretStr
class PersonaIn(BaseModel):
    name: str = Field(min_length=1,max_length=60)
    domain: str = Field(min_length=1,max_length=100)

def router(root,initialize,secure):
    api=APIRouter()
    def throttle(request):
        ip=request.client.host if request.client else 'local'
        recent=[t for t in ATTEMPTS.get(ip,[]) if time.monotonic()-t<60]
        if len(recent)>=10: raise HTTPException(429,'Too many sign-in attempts. Try again in one minute.')
        ATTEMPTS[ip]=recent+[time.monotonic()]
    def establish(c,uid,response):
        token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
        c.execute('INSERT INTO account_sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,csrf,time.time()+172800))
        response.set_cookie('app_session',token,max_age=172800,httponly=True,secure=secure(),samesite='strict',path='/')
        return {'session_token':token,'csrf_token':csrf}
    @api.post('/api/auth/register')
    def register(body: Login,request: Request,response: Response):
        throttle(request)
        password=body.password.get_secret_value()
        if not 12<=len(password)<=1024: raise HTTPException(422,'Account password must be 12–1024 characters')
        with database(root()) as c:
            if c.execute('SELECT 1 FROM users WHERE username=?',(body.username.lower(),)).fetchone(): raise HTTPException(409,'Username unavailable')
            uid=secrets.token_hex(16);pid=secrets.token_hex(16)
            c.execute('INSERT INTO users VALUES(?,?,?,?)',(uid,body.username.lower(),password_hash(password),time.time()))
            c.execute('INSERT INTO personas VALUES(?,?,?,?,?)',(pid,uid,'Audit','Audit & risk',time.time()))
            login=establish(c,uid,response)
        initialize(uid,pid,True)
        return {**login,'user':{'id':uid,'username':body.username.lower()},'persona':owned(root(),uid,pid)}
    @api.post('/api/auth/login')
    def login(body: Login,request: Request,response: Response):
        throttle(request)
        with database(root()) as c:
            row=c.execute('SELECT * FROM users WHERE username=?',(body.username.lower(),)).fetchone()
            # Equal expensive work for unknown users prevents an obvious timing oracle.
            good=verify(body.password.get_secret_value(),row['password_hash']) if row else verify(body.password.get_secret_value(),password_hash('synthetic-invalid-password'))
            if not row or not good: raise HTTPException(401,'Incorrect username or password')
            session=establish(c,row['id'],response)
            return {**session,'user':{'id':row['id'],'username':row['username']}}
    @api.get('/api/auth/me')
    def me():
        u=user();return {'user':{'id':u['id'],'username':u['username']},'csrf_token':u['csrf']}
    @api.post('/api/auth/logout')
    def logout(request: Request,response: Response):
        u=user()
        raw=request.headers.get('authorization','').removeprefix('Bearer ') or request.cookies.get('app_session','')
        with database(root()) as c: c.execute('DELETE FROM account_sessions WHERE user_id=? AND token_hash=?',(u['id'],hashlib.sha256(raw.encode()).hexdigest()))
        response.delete_cookie('app_session',path='/')
        return {'ok':True}
    @api.get('/api/personas')
    def listing():
        with database(root()) as c: return [dict(r) for r in c.execute('SELECT * FROM personas WHERE user_id=? ORDER BY created_at',(user()['id'],))]
    @api.post('/api/personas')
    def create(body: PersonaIn):
        uid=user()['id'];pid=secrets.token_hex(16)
        with database(root()) as c:
            if c.execute('SELECT count(*) FROM personas WHERE user_id=?',(uid,)).fetchone()[0]>=4: raise HTTPException(409,'Each account can have at most four personas')
            c.execute('INSERT INTO personas VALUES(?,?,?,?,?)',(pid,uid,body.name,body.domain,time.time()))
        initialize(uid,pid,False)
        return owned(root(),uid,pid)
    @api.patch('/api/personas/{pid}')
    def rename(pid,body: PersonaIn):
        owned(root(),user()['id'],pid)
        with database(root()) as c: c.execute('UPDATE personas SET name=?,domain=? WHERE id=?',(body.name,body.domain,pid))
        return owned(root(),user()['id'],pid)
    @api.post('/api/personas/{pid}/ingestion-key')
    def issue(pid):
        uid=user()['id'];owned(root(),uid,pid);key=secrets.token_urlsafe(40)
        with database(root()) as c:
            c.execute('DELETE FROM ingest_keys WHERE persona_id=?',(pid,))
            c.execute('INSERT INTO ingest_keys VALUES(?,?,?,?)',(hashlib.sha256(key.encode()).hexdigest(),uid,pid,time.time()))
        return {'key':key,'persona_id':pid,'scope':'job ingestion and email events only','note':'Shown once. Creating another key revokes the previous key.'}
    return api
