from pathlib import Path
p=Path(__file__).resolve().parents[1]/'backend/main.py'
s=p.read_text(encoding='utf-8')
s=s.replace('from . import desktop','from . import desktop\nfrom . import accounts')
s=s.replace('def db():\n    con = sqlite3.connect(DATA / "bot.sqlite", timeout=20)', 'def db():\n    con = sqlite3.connect(workspace() / "bot.sqlite", timeout=20)')
start=s.index('def init():');end=s.index('    with db() as c:',start)
s=s[:start]+'''def workspace():
    u=accounts.user(); p=accounts.persona()
    return DATA/'users'/u['id']/'personas'/p['id']

def init():
    DATA.mkdir(parents=True,exist_ok=True)
    accounts.init(DATA)

def initialize_workspace(uid,pid,seed=False):
    ut=accounts.CURRENT_USER.set({'id':uid})
    pt=accounts.CURRENT_PERSONA.set({'id':pid})
    try:
        workspace().mkdir(parents=True,exist_ok=True)
        initialize_tables(seed)
    finally:
        accounts.CURRENT_PERSONA.reset(pt);accounts.CURRENT_USER.reset(ut)

def browser_config():
    saved=workspace()/'browser-settings.json'
    return json.loads(saved.read_text()) if saved.exists() else {'enabled':False,'allowed_hosts':[]}

def initialize_tables(seed=False):
'''+s[end:]
s=s.replace('if not c.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():','if seed and not c.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():')
s=s.replace('def auth(authorization: str = Header(default="")):\n    if not hmac.compare_digest(authorization, f"Bearer {TOKEN}"): raise HTTPException(401,"API token required")','def auth():\n    accounts.user(); accounts.persona()')
s=s.replace("DATA /", "workspace() /").replace("DATA/", "workspace()/")
# Fix the root workspace resolver, which must not recursively resolve itself.
s=s.replace("return workspace()/'users'/u['id']/'personas'/p['id']", "return DATA/'users'/u['id']/'personas'/p['id']")
s=s.replace("async def prevent_vault_caching(request,call_next):\n    response=await call_next(request)\n    if request.url.path.startswith('/api/vault/'):\n        response.headers['Cache-Control']='no-store'\n    return response", '''async def prevent_vault_caching(request,call_next):
    path=request.url.path
    public={'/api/health','/api/auth/login','/api/auth/register'}
    ut=pt=None
    try:
        if path.startswith('/api/') and path not in public:
            u=accounts.identify(DATA,request)
            ut=accounts.CURRENT_USER.set(u)
            if not path.startswith(('/api/auth/','/api/personas')):
                pid=request.headers.get('x-persona-id','') or u.get('key_persona')
                if not pid: raise HTTPException(400,'Choose a persona first')
                if u.get('key_persona') and pid!=u['key_persona']: raise HTTPException(403,'Ingestion key belongs to a different persona')
                pt=accounts.CURRENT_PERSONA.set(accounts.owned(DATA,u['id'],pid))
        response=await call_next(request)
        if path.startswith('/api/'): response.headers['Cache-Control']='no-store'
        return response
    except HTTPException as e: return JSONResponse(status_code=e.status_code,content={'detail':e.detail})
    finally:
        if pt is not None: accounts.CURRENT_PERSONA.reset(pt)
        if ut is not None: accounts.CURRENT_USER.reset(ut)''')
s=s.replace("    async with SESSION_LOCK:\n        await close_all()\n        saved=", "    async with SESSION_LOCK:\n        saved=")
s=s.replace("        os.environ['BROWSER_ENABLED']='true' if body.enabled else 'false'\n        os.environ['ALLOWED_APPLICATION_HOSTS']=','.join(hosts)\n",'')
s=s.replace("Any open job browsers were closed.","Settings apply to future browser preparation.")
s=s.replace("os.getenv('BROWSER_ENABLED','false').lower()=='true'", "browser_config()['enabled']")
s=s.replace("[x.strip() for x in os.getenv('ALLOWED_APPLICATION_HOSTS','').split(',') if x.strip()]", "browser_config()['allowed_hosts']")
s=s.replace("os.getenv('REMOTE_DESKTOP_ENABLED')=='true'", "False")
s=s.replace('os.getenv("BROWSER_ENABLED","false").lower()=="true"',"browser_config()['enabled']")
s=s.replace('Path(j["resume"]).with_name("preview.png"),credentials)', 'Path(j["resume"]).with_name("preview.png"),credentials,browser_config()[\'allowed_hosts\'])')
s=s.replace("nonce=secrets.token_hex(4)", "nonce=secrets.token_hex(16)")
s=s.replace("profile()['email'].endswith('@example.com')", "profile()['email'].endswith('@example.com')")
s=s.replace("    answers: dict[str,str] = Field(default_factory=dict)", "    answers: dict[str,str] = Field(default_factory=dict)\n    whatsapp_number: str = Field(default='',max_length=20,pattern=r'^\\d*$')")
s=s.replace('app.include_router(desktop.router(auth,lambda:os.getenv(\'REMOTE_DESKTOP_ENABLED\')==\'true\',lambda:os.getenv(\'DESKTOP_SECURE_COOKIE\',\'true\')==\'true\'))','')
s=s.replace("app.include_router(desktop.router(auth,lambda:False,lambda:os.getenv('DESKTOP_SECURE_COOKIE','true')=='true'))", "")
s=s.replace('app.include_router(vault.router(db,auth,now))', "app.include_router(vault.router(db,auth,now))\napp.include_router(accounts.router(lambda:DATA,initialize_workspace,lambda:os.getenv('APP_ENV')=='production'))\n\n@app.post('/api/desktop/session',dependencies=[Depends(auth)])\ndef persona_desktop():\n    raise HTTPException(409,'Shared desktop access is disabled for multi-user safety. Use authenticated per-job screenshots; interactive remote review requires an isolated worker.')")
# Register private job routing for webhook lookup across otherwise isolated databases.
s=s.replace('    event(c,jid,"discovered","Job added to inbox"); return jid', '''    event(c,jid,"discovered","Job added to inbox")
    with accounts.database(DATA) as registry:
        registry.execute('INSERT INTO job_routes VALUES(?,?,?)',(jid,accounts.user()['id'],accounts.persona()['id']))
    return jid''')
# Webhook processing installs the exact owner/persona context, then validates recipient routing.
needle='                with db() as c:\n                    if c.execute("SELECT 1 FROM messages WHERE id=?",(mid,)).fetchone(): continue'
s=s.replace('                owner=os.getenv("WHATSAPP_OWNER_NUMBER","")\n                if not owner or message.get("from")!=owner: continue\n','')
start=s.index('                with db() as c:',s.index('async def whatsapp'))
end=s.index('    return {"results":results}',start)
block=s[start:end]
block='\n'.join('    '+line if line.strip() else line for line in block.split('\n'))
before='''                command=message.get('text',{}).get('body','').strip().split()
                if len(command)<2: continue
                with accounts.database(DATA) as registry:
                    route=registry.execute('SELECT * FROM job_routes WHERE job_id=?',(command[1],)).fetchone()
                if not route: continue
                ut=accounts.CURRENT_USER.set({'id':route['user_id']})
                pt=accounts.CURRENT_PERSONA.set({'id':route['persona_id']})
                try:
                    owner=profile().get('whatsapp_number','')
                    if not owner or message.get('from')!=owner: continue
'''
after='''                finally:
                    accounts.CURRENT_PERSONA.reset(pt); accounts.CURRENT_USER.reset(ut)
'''
s=s[:start]+before+block+after+s[end:]
s=s.replace('required=[os.getenv(k) for k in ["WHATSAPP_ACCESS_TOKEN","WHATSAPP_PHONE_NUMBER_ID","WHATSAPP_OWNER_NUMBER"]]', 'required=[os.getenv("WHATSAPP_ACCESS_TOKEN"),os.getenv("WHATSAPP_PHONE_NUMBER_ID"),profile().get("whatsapp_number")]')
p.write_text(s,encoding='utf-8')
