from fastapi.testclient import TestClient
from backend import main,desktop

def test_desktop_auth_is_short_lived_and_requires_api_access(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DATA',tmp_path)
    monkeypatch.setenv('REMOTE_DESKTOP_ENABLED','true')
    monkeypatch.setenv('DESKTOP_SECURE_COOKIE','true')
    desktop.SESSIONS.clear()
    with TestClient(main.app) as c:
        assert c.post('/api/desktop/session').status_code==401
        assert c.get('/api/desktop/auth').status_code==401
        c.headers['Authorization']='Bearer '+main.TOKEN
        r=c.post('/api/desktop/session')
        assert r.status_code==200
        assert 'HttpOnly' in r.headers['set-cookie'] and 'Secure' in r.headers['set-cookie']
        token=r.cookies.get('desktop_session')
        headers={'Cookie':'desktop_session='+token}
        assert c.get('/api/desktop/auth',headers=headers).status_code==204
        desktop.SESSIONS[token]=0
        assert c.get('/api/desktop/auth',headers=headers).status_code==401
    desktop.SESSIONS.clear()
