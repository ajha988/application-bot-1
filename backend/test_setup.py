from fastapi.testclient import TestClient
from backend import main

def test_profile_is_private_and_real_browser_requires_verified_details(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setenv('BROWSER_ENABLED','false')
    with TestClient(main.app) as c:
        c.headers['Authorization']='Bearer '+main.TOKEN
        assert not c.get('/api/setup/status').json()['profile_ready']
        p=c.get('/api/profile').json(); p['name']='Test Candidate';p['email']='synthetic@test.invalid'
        assert c.put('/api/profile',json=p).status_code==200
        assert c.get('/api/setup/status').json()['profile_ready']
        assert c.get('/api/profile',headers={'Authorization':'Bearer wrong'}).status_code==401
        assert (tmp_path/'profile.json').exists()
        assert c.put('/api/setup/browser',json={'enabled':True,'allowed_hosts':['127.0.0.1']}).status_code==422
        assert c.put('/api/setup/browser',json={'enabled':False,'allowed_hosts':['careers.example.com']}).status_code==200
        assert c.get('/api/setup/status').json()['allowed_hosts']==['careers.example.com']
