import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, HttpUrl
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from .automation import prepare_browser, close_session, close_all, SESSION_LOCK
from . import vault
from . import desktop
from . import accounts

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATA = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
TOKEN = os.getenv("API_TOKEN", "local-demo-change-me")
STATES = {
 "discovered": {"matched", "rejected"}, "matched": {"resume_ready", "rejected"},
 "resume_ready": {"needs_input", "awaiting_approval", "rejected"},
 "needs_input": {"awaiting_approval", "rejected"}, "awaiting_approval": {"approved", "rejected", "needs_input"},
 "approved": {"submitted", "rejected", "needs_input"}, "submitted": {"interview", "rejected", "follow_up"},
 "follow_up": {"interview", "rejected", "submitted"}, "interview": {"offer", "rejected", "follow_up"},
 "offer": set(), "rejected": set()}

def now(): return datetime.now(timezone.utc).isoformat()
@contextmanager
def db():
    con = sqlite3.connect(workspace() / "bot.sqlite", timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback(); raise
    finally: con.close()

def workspace():
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
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, url TEXT UNIQUE, company TEXT, role TEXT, location TEXT, jd TEXT, source TEXT, status TEXT, score INTEGER DEFAULT 0, matched_skills TEXT DEFAULT '[]', resume TEXT, revision INTEGER DEFAULT 0, approval_revision INTEGER, approval_token TEXT, interview_date TEXT, next_action TEXT DEFAULT '', created_at TEXT);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, job_id TEXT, kind TEXT, detail TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS answers(job_id TEXT, question TEXT, answer TEXT, PRIMARY KEY(job_id,question));
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, job_id TEXT, body TEXT, status TEXT, created_at TEXT);''')
        vault.init(c)
    with db() as c:
        if seed and not c.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():
            for job in json.loads((ROOT / "sample-jobs.json").read_text())["jobs"]: insert(c, job)

def event(c, jid, kind, detail):
    c.execute("INSERT INTO events(job_id,kind,detail,created_at) VALUES(?,?,?,?)", (jid, kind, detail, now()))
def get(c, jid):
    row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row: raise HTTPException(404, "Job not found")
    return dict(row)
def transition(c, jid, status, detail):
    j = get(c,jid)
    if status not in STATES[j["status"]]: raise HTTPException(409, f"Cannot move {j['status']} to {status}")
    c.execute("UPDATE jobs SET status=? WHERE id=?", (status,jid)); event(c,jid,status,detail)
def insert(c, j):
    existing = c.execute("SELECT id FROM jobs WHERE url=?", (str(j["url"]),)).fetchone()
    if existing: return existing["id"]
    jid = uuid.uuid4().hex[:12]
    c.execute("INSERT INTO jobs(id,url,company,role,location,jd,source,status,created_at) VALUES(?,?,?,?,?,?,?,'discovered',?)", (jid,str(j["url"]),j["company"],j["role"],j.get("location",""),j.get("jd",""),j.get("source","api"),now()))
    event(c,jid,"discovered","Job added to inbox")
    with accounts.database(DATA) as registry:
        registry.execute('INSERT INTO job_routes VALUES(?,?,?)',(jid,accounts.user()['id'],accounts.persona()['id']))
    return jid
def auth():
    accounts.user(); accounts.persona()
def profile():
    saved=workspace()/'profile.json'
    source=saved if saved.exists() else ROOT / 'sample-profile.json'
    if not source.is_absolute(): source=ROOT/source
    return json.loads(source.read_text(encoding="utf-8"))

@asynccontextmanager
async def lifespan(app):
    if os.getenv('APP_ENV')=='production' and (TOKEN=='local-demo-change-me' or len(TOKEN)<32):
        raise RuntimeError('Production requires a unique API_TOKEN of at least 32 characters')
    init(); yield
    await close_all()
app = FastAPI(title="Application Bot MVP", lifespan=lifespan)

@app.middleware('http')
async def prevent_vault_caching(request,call_next):
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
        if ut is not None: accounts.CURRENT_USER.reset(ut)

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    # Vault request bodies may contain secrets: never echo validator input values.
    if request.url.path.startswith('/api/vault/'):
        return JSONResponse(status_code=422,content={'detail':'Invalid vault request. Check required fields and their types.'})
    return JSONResponse(status_code=422,content={'detail':[{'loc':e['loc'],'msg':e['msg'],'type':e['type']} for e in exc.errors()]})

class JobIn(BaseModel):
    url: HttpUrl
    company: str = Field(min_length=1,max_length=200)
    role: str = Field(min_length=1,max_length=200)
    location: str = ""
    jd: str = Field(default="",max_length=100000)
    source: str = "api"
class Batch(BaseModel): jobs: list[JobIn] = Field(max_length=100)
class Decision(BaseModel): decision: Literal["approve","reject"]; revision: int
class Answer(BaseModel): question: str = Field(min_length=1,max_length=500); answer: str = Field(min_length=1,max_length=5000)
class Tracking(BaseModel): interview_date: datetime | None = None; next_action: str = Field(default="",max_length=2000)
class Confirmation(BaseModel): evidence: str = Field(min_length=5,max_length=2000)
class Experience(BaseModel):
    company: str = Field(min_length=1,max_length=200)
    title: str = Field(min_length=1,max_length=200)
    dates: str = Field(min_length=1,max_length=100)
    bullets: list[str] = Field(max_length=50)
class MasterProfile(BaseModel):
    name: str = Field(min_length=1,max_length=200)
    email: str = Field(min_length=3,max_length=254)
    phone: str = Field(max_length=50)
    location: str = Field(max_length=200)
    summary: str = Field(max_length=4000)
    skills: list[str] = Field(max_length=100)
    experience: list[Experience] = Field(max_length=30)
    education: list[str] = Field(default_factory=list,max_length=30)
    answers: dict[str,str] = Field(default_factory=dict)
    whatsapp_number: str = Field(default='',max_length=20,pattern=r'^\d*$')
class BrowserSettings(BaseModel):
    enabled: bool
    allowed_hosts: list[str] = Field(max_length=50)

@app.put('/api/setup/browser',dependencies=[Depends(auth)])
async def browser_settings(body: BrowserSettings):
    hosts=list(dict.fromkeys(h.strip().lower() for h in body.allowed_hosts if h.strip()))
    import ipaddress
    for host in hosts:
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) or '.' not in host or host.endswith(('.local','.localhost','.internal')):
            raise HTTPException(422,'Enter exact public hostnames without URLs, wildcards or paths')
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise HTTPException(422,'IP addresses are not supported as career hosts')
    if body.enabled and not hosts: raise HTTPException(422,'Add a career hostname before enabling preparation')
    async with SESSION_LOCK:
        saved={'enabled':body.enabled,'allowed_hosts':hosts}
        with db():
            pending=workspace()/'browser-settings.pending'; pending.write_text(json.dumps(saved)); pending.replace(workspace()/'browser-settings.json')
    return {'ok':True,'note':'Browser settings saved. Settings apply to future browser preparation.'}

@app.get('/api/profile',dependencies=[Depends(auth)])
def read_profile(): return profile()
@app.put('/api/profile',dependencies=[Depends(auth)])
def save_profile(body: MasterProfile):
    target=workspace()/'profile.json'
    temporary=workspace()/'profile.pending'
    with db():
        temporary.write_text(body.model_dump_json(indent=2),encoding='utf-8')
        temporary.replace(target)
    return {'ok':True,'note':'Verified profile saved locally. Existing resumes remain unchanged.'}
@app.get('/api/setup/status',dependencies=[Depends(auth)])
def setup_status():
    p=profile()
    sample=p['name']=='Sample Candidate' or p['email'].endswith('@example.com')
    return {'profile_ready':not sample,'browser_enabled':browser_config()['enabled'],
        'allowed_hosts':browser_config()['allowed_hosts'],
        'whatsapp_configured':all(os.getenv(k) for k in ['WHATSAPP_APP_SECRET','WHATSAPP_VERIFY_TOKEN','WHATSAPP_ACCESS_TOKEN','WHATSAPP_PHONE_NUMBER_ID','WHATSAPP_OWNER_NUMBER']),
        'gmail_configured':all(os.getenv(k) for k in ['GMAIL_CLIENT_ID','GMAIL_CLIENT_SECRET','GMAIL_REFRESH_TOKEN']),
        'submission_mode':'manual_after_approval','remote_desktop_enabled':False}
class EmailEvent(BaseModel):
    message_id: str
    job_id: str
    kind: Literal["confirmation","recruiter","interview","rejection","follow_up"]
    summary: str
    interview_date: datetime | None = None

@app.get("/api/health")
def health(): return {"ok": True,"submission_mode":"manual_after_approval"}
@app.get("/api/jobs", dependencies=[Depends(auth)])
def jobs():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM jobs ORDER BY created_at DESC")]
@app.post("/api/jobs/ingest", dependencies=[Depends(auth)])
def ingest(body: Batch):
    with db() as c: return {"ids":[insert(c,j.model_dump(mode="json")) for j in body.jobs]}
@app.get("/api/metrics", dependencies=[Depends(auth)])
def metrics():
    with db() as c: return {r["status"]:r["n"] for r in c.execute("SELECT status,count(*) n FROM jobs GROUP BY status")}
@app.get("/api/jobs/{jid}", dependencies=[Depends(auth)])
def detail(jid):
    with db() as c:
        j=get(c,jid)
        j["timeline"]=[dict(r) for r in c.execute("SELECT * FROM events WHERE job_id=? ORDER BY id",(jid,))]
        j["answers"]=[dict(r) for r in c.execute("SELECT question,answer FROM answers WHERE job_id=?",(jid,))]
        return j
@app.post("/api/jobs/{jid}/match", dependencies=[Depends(auth)])
def match(jid):
    with db() as c:
        j=get(c,jid); text=j["jd"].lower(); skills=profile()["skills"]
        if not text.strip(): raise HTTPException(422,"Supply JD text through ingestion before matching")
        hits=[s for s in skills if re.search(r"(?<!\w)"+re.escape(s.lower())+r"(?!\w)",text)]
        score=round(100*len(hits)/max(len(skills),1))
        transition(c,jid,"matched","Transparent keyword scaffold: overlap with saved profile skills; not a hiring probability")
        c.execute("UPDATE jobs SET score=?,matched_skills=? WHERE id=?",(score,json.dumps(hits),jid))
        return {"score":score,"matched_skills":hits}

def make_resume(p,j,target):
    hits=json.loads(j["matched_skills"])
    # Only reorder exact source facts; never create a new achievement or skill.
    skills=sorted(p["skills"],key=lambda s:s not in hits)
    lines=[p["name"],f"{p['email']} | {p['phone']} | {p['location']}",p["summary"],"Skills: "+", ".join(skills)]
    for exp in p["experience"]:
        lines += [f"{exp['title']} — {exp['company']} | {exp['dates']}"]
        lines += sorted(exp["bullets"],key=lambda b:-sum(s.lower() in b.lower() for s in hits))
    lines += p.get("education",[])
    pdf=canvas.Canvas(str(target)); y=800
    for line in lines:
        for segment in simpleSplit(line,"Helvetica",10,480):
            if y<50: pdf.showPage(); y=800
            pdf.setFont("Helvetica",10); pdf.drawString(50,y,segment); y-=16
        y-=8
    pdf.save()
    target.with_suffix(".json").write_text(json.dumps({"source_profile":p,"ordered_lines":lines,"job_id":j["id"]},indent=2),encoding="utf-8")

@app.post("/api/jobs/{jid}/resume", dependencies=[Depends(auth)])
def resume(jid):
    with db() as c:
        j=get(c,jid)
        if j["status"]!="matched": raise HTTPException(409,"Match job first")
        directory=workspace() / "resumes" / jid; directory.mkdir(parents=True,exist_ok=True)
        path=directory / "resume.pdf"; make_resume(profile(),j,path)
        transition(c,jid,"resume_ready","Resume generated by reordering verified profile facts")
        c.execute("UPDATE jobs SET resume=?,revision=revision+1 WHERE id=?",(str(path),jid))
    return {"ok":True}
@app.get("/api/jobs/{jid}/resume", dependencies=[Depends(auth)])
def download(jid):
    with db() as c: j=get(c,jid)
    if not j["resume"]: raise HTTPException(404,"Generate a resume first")
    return FileResponse(j["resume"],media_type="application/pdf",filename=f"{jid}-resume.pdf")
@app.get("/api/jobs/{jid}/screenshot", dependencies=[Depends(auth)])
def screenshot(jid):
    with db() as c: get(c,jid)
    path=workspace() / "resumes" / jid / "preview.png"
    if not path.exists(): raise HTTPException(404,"No screenshot available")
    return FileResponse(path)
@app.post("/api/jobs/{jid}/prepare", dependencies=[Depends(auth)])
async def prepare(jid, x_vault_session: str = Header(default="")):
    with db() as c:
        j=get(c,jid)
        if j["status"] not in {"resume_ready","needs_input"}: raise HTTPException(409,"Generate resume first or return to manual intervention")
    credentials=vault.credentials_for(db,j["url"],x_vault_session) if x_vault_session else None
    if browser_config()['enabled']:
        if profile()['name']=='Sample Candidate' or profile()['email'].endswith('@example.com'):
            raise HTTPException(409,'Save your verified master profile in Setup before preparing real applications')
        try:
            async with SESSION_LOCK:
                result=await prepare_browser(j["url"],profile(),Path(j["resume"]),Path(j["resume"]).with_name("preview.png"),credentials,browser_config()['allowed_hosts'])
        except Exception as e: result={"manual":True,"reason":f"Browser paused: {type(e).__name__}. Check allowed hosts/browser installation and complete manually."}
    else: result={"manual":True,"reason":"Demo preparation only. Real browser disabled. Review and complete the application manually."}
    with db() as c:
        current=get(c,jid)
        if current['status'] not in {'resume_ready','needs_input'}: raise HTTPException(409,'Application changed during browser preparation; result discarded')
        if current['status']=='needs_input': event(c,jid,'preparation_retry',json.dumps(result))
        else: transition(c,jid,"needs_input",json.dumps(result))
    return result
@app.post('/api/jobs/{jid}/close-browser',dependencies=[Depends(auth)])
async def close_browser(jid):
    with db() as c: get(c,jid)
    async with SESSION_LOCK: await close_session(jid)
    return {'ok':True}
@app.post("/api/jobs/{jid}/answer", dependencies=[Depends(auth)])
def answer(jid,body: Answer):
    with db() as c: save_answer(c,jid,body.question,body.answer)
    return {"ok":True}
def save_answer(c,jid,question,answer):
    j=get(c,jid)
    if j["status"] not in {"resume_ready","needs_input","awaiting_approval","approved"}: raise HTTPException(409,"Application cannot be edited in this state")
    if j["status"] in {"awaiting_approval","approved"}: transition(c,jid,"needs_input","Answer changed; approval invalidated")
    c.execute("INSERT OR REPLACE INTO answers VALUES(?,?,?)",(jid,question,answer))
    c.execute("UPDATE jobs SET revision=revision+1,approval_revision=NULL,approval_token=NULL WHERE id=?",(jid,))
    event(c,jid,"answer",f"{question}: {answer}")
@app.post("/api/jobs/{jid}/ready", dependencies=[Depends(auth)])
def ready(jid):
    with db() as c:
        transition(c,jid,"awaiting_approval","User marked application reviewed and ready; mandatory field validation is manual")
        nonce=secrets.token_hex(16)
        c.execute("UPDATE jobs SET approval_token=? WHERE id=?",(nonce,jid))
        j=get(c,jid)
        body=f"{j['company']} — {j['role']}: review resume and application. Reply APPROVE {jid} {nonce} or REJECT {jid} {nonce}. Approval permits manual submission only."
        c.execute("INSERT INTO outbox(job_id,body,status,created_at) VALUES(?,?,'pending',?)",(jid,body,now()))
    return {"message":body}
def decide(c,jid,decision,revision,source):
    j=get(c,jid)
    if j["status"]!="awaiting_approval" or j["revision"]!=revision: raise HTTPException(409,"Approval is stale or application is not awaiting approval")
    transition(c,jid,"approved" if decision=="approve" else "rejected",f"Explicit {source} decision for revision {revision}; no submission performed")
    c.execute("UPDATE jobs SET approval_revision=?,approval_token=NULL WHERE id=?",(revision,jid))
@app.post("/api/jobs/{jid}/decision", dependencies=[Depends(auth)])
def decision(jid,body: Decision):
    with db() as c: decide(c,jid,body.decision,body.revision,"portal")
    return {"ok":True,"submission":"Manual submission only"}
@app.post("/api/jobs/{jid}/confirm-submission", dependencies=[Depends(auth)])
def confirm(jid,body: Confirmation):
    with db() as c:
        j=get(c,jid)
        if j["status"]!="approved" or j["approval_revision"]!=j["revision"]: raise HTTPException(409,"Current explicit approval required")
        transition(c,jid,"submitted","User reports manual submission: "+body.evidence)
    return {"ok":True}
@app.patch("/api/jobs/{jid}/tracking", dependencies=[Depends(auth)])
def tracking(jid,body: Tracking):
    with db() as c:
        get(c,jid); c.execute("UPDATE jobs SET interview_date=?,next_action=? WHERE id=?",(body.interview_date.isoformat() if body.interview_date else None,body.next_action,jid)); event(c,jid,"tracking",body.model_dump_json())
    return {"ok":True}

@app.post("/api/email/events", dependencies=[Depends(auth)])
def email(body: EmailEvent):
    with db() as c:
        if c.execute("SELECT 1 FROM messages WHERE id=?",("email:"+body.message_id,)).fetchone(): return {"duplicate":True}
        j=get(c,body.job_id)
        # Emails cannot approve or authorize submission. Confirmation remains evidence only.
        dest={"interview":"interview","rejection":"rejected","follow_up":"follow_up"}.get(body.kind)
        if dest and dest in STATES[j["status"]]: transition(c,body.job_id,dest,"Email hook: "+body.summary)
        else: event(c,body.job_id,"email_"+body.kind,body.summary)
        if body.interview_date: c.execute("UPDATE jobs SET interview_date=? WHERE id=?",(body.interview_date.isoformat(),body.job_id))
        c.execute("INSERT INTO messages VALUES(?)",("email:"+body.message_id,))
        c.execute("INSERT INTO outbox(job_id,body,status,created_at) VALUES(?,?,'pending',?)",(body.job_id,body.kind+": "+body.summary,now()))
    return {"ok":True}
@app.get("/api/integrations", dependencies=[Depends(auth)])
def integrations(): return {"gmail":"OAuth/polling scaffold; ingest normalized events via /api/email/events", "whatsapp_send_enabled":os.getenv("WHATSAPP_SEND_ENABLED")=="true","browser_enabled":browser_config()["enabled"]}
@app.get("/webhooks/whatsapp")
def verify(request: Request):
    q=request.query_params; token=os.getenv("WHATSAPP_VERIFY_TOKEN","")
    if token and q.get("hub.mode")=="subscribe" and hmac.compare_digest(q.get("hub.verify_token",""),token): return PlainTextResponse(q.get("hub.challenge",""))
    raise HTTPException(403,"Verification failed")
@app.post("/webhooks/whatsapp")
async def whatsapp(request: Request):
    raw=await request.body(); secret=os.getenv("WHATSAPP_APP_SECRET","")
    signature="sha256="+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
    if not secret or not hmac.compare_digest(request.headers.get("x-hub-signature-256",""),signature): raise HTTPException(403,"Invalid webhook signature")
    try: payload=json.loads(raw)
    except ValueError: raise HTTPException(400,"Invalid JSON")
    results=[]
    for entry in payload.get("entry",[]):
        for change in entry.get("changes",[]):
            for message in change.get("value",{}).get("messages",[]):
                mid="wa:"+message.get("id","")
                if mid=="wa:": continue
                command=message.get('text',{}).get('body','').strip().split()
                if len(command)<2: continue
                with accounts.database(DATA) as registry:
                    route=registry.execute('SELECT * FROM job_routes WHERE job_id=?',(command[1],)).fetchone()
                if not route: continue
                ut=accounts.CURRENT_USER.set({'id':route['user_id']})
                pt=accounts.CURRENT_PERSONA.set({'id':route['persona_id']})
                try:
                    owner=profile().get('whatsapp_number','')
                    if not owner or message.get('from')!=owner: continue
                    with db() as c:
                        if c.execute("SELECT 1 FROM messages WHERE id=?",(mid,)).fetchone(): continue
                        parts=message.get("text",{}).get("body","").strip().split(maxsplit=3)
                        try:
                            if len(parts)<3: raise HTTPException(422,"Use APPROVE/REJECT <job-id> <token> or ANSWER <job-id> <question> | <answer>")
                            cmd,jid=parts[0].upper(),parts[1]; j=get(c,jid)
                            if cmd in {"APPROVE","REJECT"}:
                                if len(parts)!=3 or not j["approval_token"] or not hmac.compare_digest(parts[2],j["approval_token"]): raise HTTPException(409,"Invalid or expired approval token")
                                decide(c,jid,cmd.lower(),j["revision"],"WhatsApp")
                            elif cmd=="ANSWER":
                                text=message["text"]["body"].split(maxsplit=2)[2]
                                if "|" not in text: raise HTTPException(422,"Separate question and answer with |")
                                question,value=text.split("|",1)
                                validated=Answer(question=question.strip(),answer=value.strip())
                                save_answer(c,jid,validated.question,validated.answer)
                            else: raise HTTPException(422,"Unknown command")
                            results.append({"id":mid,"ok":True})
                        except (HTTPException,ValueError) as e:
                            results.append({"id":mid,"error":getattr(e,"detail",str(e))})
                        c.execute("INSERT INTO messages VALUES(?)",(mid,))
                finally:
                    accounts.CURRENT_PERSONA.reset(pt); accounts.CURRENT_USER.reset(ut)
    return {"results":results}
@app.get("/api/notifications", dependencies=[Depends(auth)])
def notifications():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM outbox ORDER BY id DESC")]
@app.post("/api/notifications/{nid}/send", dependencies=[Depends(auth)])
async def send(nid: int):
    if os.getenv("WHATSAPP_SEND_ENABLED")!="true": raise HTTPException(409,"Outbound disabled; notification is stored in local outbox")
    required=[os.getenv("WHATSAPP_ACCESS_TOKEN"),os.getenv("WHATSAPP_PHONE_NUMBER_ID"),profile().get("whatsapp_number")]
    if not all(required): raise HTTPException(409,"Configure Meta credentials")
    with db() as c:
        row=c.execute("SELECT * FROM outbox WHERE id=?",(nid,)).fetchone()
        if not row: raise HTTPException(404,"Notification not found")
        if row["status"]!="pending": raise HTTPException(409,"Already sent or sending; verify uncertain delivery manually")
        c.execute("UPDATE outbox SET status='sending' WHERE id=?",(nid,))
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r=await client.post(f"https://graph.facebook.com/{os.getenv('WHATSAPP_GRAPH_VERSION','v25.0')}/{required[1]}/messages",headers={"Authorization":f"Bearer {required[0]}"},json={"messaging_product":"whatsapp","to":required[2],"type":"text","text":{"body":row["body"]}})
            r.raise_for_status()
    except Exception:
        with db() as c: c.execute("UPDATE outbox SET status='delivery_uncertain' WHERE id=?",(nid,))
        raise HTTPException(502,"Delivery uncertain. Verify with Meta before retrying; free-form messages require an open customer service window.")
    with db() as c: c.execute("UPDATE outbox SET status='sent' WHERE id=?",(nid,))
    return {"ok":True}

DIST=ROOT / "frontend" / "dist"
app.include_router(vault.router(db,auth,now))
app.include_router(accounts.router(lambda:DATA,initialize_workspace,lambda:os.getenv('APP_ENV')=='production'))

@app.post('/api/desktop/session',dependencies=[Depends(auth)])
def persona_desktop():
    raise HTTPException(409,'Shared desktop access is disabled for multi-user safety. Use authenticated per-job screenshots; interactive remote review requires an isolated worker.')

if DIST.exists(): app.mount("/",StaticFiles(directory=DIST,html=True),name="portal")
