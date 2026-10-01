import json
import pytest
from fastapi.testclient import TestClient
from backend import main, vault

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    vault.SESSIONS.clear()
    with TestClient(main.app) as c:
        c.headers['Authorization']='Bearer '+main.TOKEN
        yield c
    vault.SESSIONS.clear()

def unlock(c):
    response=c.post('/api/vault/unlock',json={'master_password':'test master passphrase 123'})
    assert response.status_code==200
    c.headers['X-Vault-Session']=response.json()['session']

def test_encrypted_storage_and_scope(client):
    assert client.get('/api/vault/credentials').status_code==423
    unlock(client)
    body={'label':'Demo career account','login_url':'https://careers.example.com/tenant/login','scope':'/tenant','username':'test-user@example.com','password':'test-password-only'}
    r=client.post('/api/vault/credentials',json=body)
    assert r.status_code==200
    metadata=client.get('/api/vault/credentials').json()
    assert 'password' not in json.dumps(metadata) and 'username' not in json.dumps(metadata)
    with main.db() as c:
        raw=c.execute('SELECT secret FROM credentials').fetchone()['secret']
        assert b'test-password-only' not in raw and b'test-user@example.com' not in raw
    token=client.headers['X-Vault-Session']
    assert vault.credentials_for(main.db,'https://careers.example.com/tenant/job-2',token)['password']=='test-password-only'
    assert vault.credentials_for(main.db,'https://careers.example.com/tenant-other/job',token) is None
    assert vault.credentials_for(main.db,'https://other.example.com/tenant/job',token) is None
    assert client.post('/api/vault/credentials',json={**body,'password':'updated-test-secret'}).status_code==200
    assert len(client.get('/api/vault/credentials').json())==1
    assert client.delete('/api/vault/credentials/'+r.json()['id']).status_code==200

def test_lock_wrong_password_auth_and_session_expiry(client,monkeypatch):
    unlock(client)
    token=client.headers['X-Vault-Session']
    assert client.get('/api/vault/status',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert client.post('/api/vault/unlock',json={'master_password':'a wrong passphrase 123'}).status_code==403
    assert client.post('/api/vault/lock').status_code==200
    assert client.get('/api/vault/credentials').status_code==423
    unlock(client)
    token=client.headers['X-Vault-Session']
    vault.SESSIONS[token]['expires']=0
    assert client.get('/api/vault/credentials').status_code==423

def test_no_plaintext_in_validation_and_invalid_urls(client):
    unlock(client)
    body={'label':'Test','login_url':'http://example.com/login','scope':'/','username':'u','password':'should-never-appear'}
    r=client.post('/api/vault/credentials',json=body)
    assert r.status_code==422 and 'should-never-appear' not in r.text
    malformed=client.post('/api/vault/unlock',json={'master_password':{'value':'never-echo-this-secret'}})
    assert malformed.status_code==422 and 'never-echo-this-secret' not in malformed.text
    assert client.get('/api/vault/status').headers['cache-control']=='no-store'
    assert client.post('/api/vault/unlock',json={'master_password':'short'}).status_code==422
