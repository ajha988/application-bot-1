import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from backend import main

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DATA",tmp_path)
    monkeypatch.setenv("BROWSER_ENABLED","false")
    monkeypatch.setenv("WHATSAPP_APP_SECRET","test-secret")
    monkeypatch.setenv("WHATSAPP_OWNER_NUMBER","10000000000")
    with TestClient(main.app) as c:
        c.headers["Authorization"]="Bearer "+main.TOKEN
        yield c

def ready(c):
    j=c.get('/api/jobs').json()[0]; jid=j['id']
    for step in ['match','resume','prepare','ready']:
        assert c.post(f'/api/jobs/{jid}/{step}').status_code==200
    return c.get('/api/jobs/'+jid).json()

def test_approval_gate_and_invalidation(client):
    j=ready(client); url='/api/jobs/'+j['id']
    assert client.post(url+'/confirm-submission',json={'evidence':'confirmation 123'}).status_code==409
    assert client.post(url+'/decision',json={'decision':'approve','revision':j['revision']+1}).status_code==409
    assert client.post(url+'/decision',json={'decision':'approve','revision':j['revision']}).status_code==200
    assert client.get(url).json()['status']=='approved'
    assert client.post(url+'/answer',json={'question':'Notice period','answer':'30 days'}).status_code==200
    assert client.post(url+'/confirm-submission',json={'evidence':'confirmation 123'}).status_code==409
    assert client.post(url+'/ready').status_code==200
    updated=client.get(url).json()
    client.post(url+'/decision',json={'decision':'approve','revision':updated['revision']})
    assert client.post(url+'/confirm-submission',json={'evidence':'User observed confirmation #123'}).status_code==200
    assert client.post('/api/email/events',json={'message_id':'m1','job_id':j['id'],'kind':'interview','summary':'Invitation','interview_date':'2026-10-12T12:00:00Z'}).status_code==200
    assert client.get(url).json()['status']=='interview'

def test_resume_provenance_and_duplicate_ingest(client):
    j=ready(client)
    pdf=client.get('/api/jobs/'+j['id']+'/resume')
    assert pdf.content.startswith(b'%PDF')
    artifact=json.loads((main.DATA/'resumes'/j['id']/'resume.json').read_text())
    for exp in main.profile()['experience']:
        for bullet in exp['bullets']: assert bullet in artifact['ordered_lines']
    body={'jobs':[{'url':j['url'],'company':j['company'],'role':j['role']}]}
    assert client.post('/api/jobs/ingest',json=body).json()['ids']==[j['id']]
    assert client.get('/api/jobs',headers={'Authorization':'Bearer wrong'}).status_code==401

def test_signed_whatsapp_explicit_nonce_and_replay(client):
    j=ready(client)
    payload={'entry':[{'changes':[{'value':{'messages':[{'id':'wa-1','from':'10000000000','text':{'body':f"APPROVE {j['id']} {j['approval_token']}"}}]}}]}]}
    raw=json.dumps(payload).encode(); signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
    assert client.post('/webhooks/whatsapp',content=raw).status_code==403
    assert client.post('/webhooks/whatsapp',content=raw,headers={'x-hub-signature-256':signature}).json()['results'][0]['ok']
    assert client.post('/webhooks/whatsapp',content=raw,headers={'x-hub-signature-256':signature}).json()['results']==[]
    assert client.get('/api/jobs/'+j['id']).json()['status']=='approved'

def test_email_never_grants_approval(client):
    j=ready(client)
    body={'message_id':'m1','job_id':j['id'],'kind':'confirmation','summary':'Application received'}
    assert client.post('/api/email/events',json=body).status_code==200
    assert client.post('/api/email/events',json=body).json()['duplicate']
    assert client.get('/api/jobs/'+j['id']).json()['status']=='awaiting_approval'
