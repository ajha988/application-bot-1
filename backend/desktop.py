"""Issue short-lived HttpOnly desktop sessions; nginx protects every noVNC route."""
import secrets
import threading
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response

SESSIONS={}
LOCK=threading.Lock()

def router(auth,enabled,secure):
    api=APIRouter(prefix='/api/desktop')
    @api.post('/session',dependencies=[Depends(auth)])
    def create(response: Response):
        if not enabled(): raise HTTPException(409,'Remote browser view is available only in the hosted container')
        token=secrets.token_urlsafe(32)
        with LOCK:
            for old in list(SESSIONS):
                if SESSIONS[old]<time.monotonic(): del SESSIONS[old]
            SESSIONS[token]=time.monotonic()+1800
        response.set_cookie('desktop_session',token,max_age=1800,httponly=True,secure=secure(),samesite='strict',path='/desktop')
        response.headers['Cache-Control']='no-store'
        return {'url':'/desktop/vnc.html?autoconnect=true&resize=scale&path=desktop/websockify','expires_in_seconds':1800}
    @api.get('/auth')
    def check(request: Request):
        # Called by an internal nginx subrequest with the original Cookie header.
        token=request.cookies.get('desktop_session','')
        with LOCK:
            if not enabled() or SESSIONS.get(token,0)<time.monotonic(): raise HTTPException(401,'Remote desktop session required')
        return Response(status_code=204,headers={'Cache-Control':'no-store'})
    @api.post('/logout',dependencies=[Depends(auth)])
    def logout(response: Response):
        with LOCK: SESSIONS.clear()
        response.delete_cookie('desktop_session',path='/desktop',secure=secure(),httponly=True,samesite='strict')
        return {'ok':True,'note':'New browser-view connections are blocked. Close existing viewer tabs to end their WebSocket sessions.'}
    return api
