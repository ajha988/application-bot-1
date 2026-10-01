"""Preparation only: no submit or navigation button clicks exist in this module."""
import os
from urllib.parse import urlparse
from playwright.async_api import async_playwright
import re
from .vault import canonical, scope_matches
import asyncio

SESSIONS={}
SESSION_LOCK=asyncio.Lock()

async def close_session(jid):
    session=SESSIONS.pop(jid,None)
    if session:
        try: await session['browser'].close()
        finally: await session['playwright'].stop()

async def close_all():
    for jid in list(SESSIONS): await close_session(jid)

async def challenge_visible(page):
    tokens=page.locator('textarea[name="g-recaptcha-response"], textarea[name="h-captcha-response"]')
    for token in await tokens.all():
        if await token.input_value(): return False
    captcha=page.locator('iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible, [data-testid="captcha"]:visible')
    return await captcha.count()>0 or await page.get_by_text(re.compile(r'^(verify you are human|complete the captcha|security verification)$',re.I)).filter(visible=True).count()>0

async def reuse_login(page, credentials):
    """Recognized login forms only; never click an application submit button."""
    host,path=canonical(page.url)
    if host!=credentials['host'] or not scope_matches(path,credentials['scope']):
        return 'Saved credential scope does not match this page; manual login required'
    password=page.locator('input[type="password"]:visible')
    if await password.count()!=1: return 'No unambiguous login form; manual login required'
    action=await password.evaluate('(input) => input.form ? input.form.action : location.href')
    action_host,action_path=canonical(action)
    if action_host!=credentials['host'] or not scope_matches(action_path,credentials['scope']):
        return 'Login form posts outside the saved credential scope; manual login required'
    username=page.locator('input[type="email"]:visible, input[autocomplete="username"]:visible')
    if await username.count()!=1: return 'Username field is ambiguous; manual login required'
    await username.fill(credentials['username'])
    await password.fill(credentials['password'])
    button=page.get_by_role('button',name=re.compile(r'^(sign in|log in|login)$',re.I))
    if await button.count()!=1:
        await password.fill('')
        return 'Login button is ambiguous; manual login required'
    await button.click()
    await page.wait_for_timeout(1200)
    if await page.locator('input[type="password"]:visible').count():
        return 'Login requires manual attention; check credentials or MFA'
    return None

class GenericAdapter:
    fields = {"name": ["Full name", "Name"], "email": ["Email", "Email address"], "phone": ["Phone", "Phone number"]}
    async def fill(self, page, profile, resume):
        filled = []
        for key, labels in self.fields.items():
            for label in labels:
                locator = page.get_by_label(label, exact=True)
                if await locator.count() == 1 and await locator.is_visible():
                    await locator.fill(profile[key]); filled.append(key); break
        uploads = page.locator('input[type="file"]')
        if await uploads.count() == 1:
            await uploads.set_input_files(str(resume)); filled.append("resume")
        return filled

class GreenhouseAdapter(GenericAdapter):
    fields = {**GenericAdapter.fields, "name": ["Full name", "Name"]}
class LeverAdapter(GenericAdapter):
    pass
class WorkdayAdapter(GenericAdapter):
    """Authentication and multi-step forms require manual intervention."""
    pass

def adapter_for(url):
    host = urlparse(url).hostname or ""
    return (GreenhouseAdapter if "greenhouse" in host else LeverAdapter if "lever" in host else WorkdayAdapter if "workday" in host else GenericAdapter)()

async def prepare_browser(url, profile, resume, screenshot, credentials=None,allowed_hosts=None):
    allowed = set(allowed_hosts or [])
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.password:
        raise ValueError("Application URL must use HTTPS on an explicitly allowed host")
    jid=screenshot.parent.name
    session=SESSIONS.get(jid)
    if session and not session['browser'].is_connected():
        await close_session(jid); session=None
    if not session:
        if len(SESSIONS)>=3:
            raise ValueError('Close another job browser before opening a fourth session')
        p=await async_playwright().start()
        try:
            browser=await p.chromium.launch(headless=os.getenv('APP_ENV')=='production')
        except Exception:
            await p.stop(); raise
        context=await browser.new_context()
        page=await context.new_page()
        SESSIONS[jid]={'playwright':p,'browser':browser,'context':context,'page':page}
    else:
        browser=session['browser']; context=session['context']; page=session['page']
    credential_host=credentials['host'] if credentials else SESSIONS[jid].get('credential_host')
    SESSIONS[jid]['credential_host']=credential_host
    await context.unroute('**/*')
    # Block requests to any unapproved host (including redirects/private network targets).
    async def guard(route):
        target = urlparse(route.request.url)
        # Never send form credentials to another resource/authentication host.
        if credential_host and route.request.method not in {'GET','HEAD','OPTIONS'} and target.hostname!=credential_host:
            await route.abort(); return
        if target.scheme == "https" and target.hostname in allowed:
            await route.continue_()
        else:
            await route.abort()
    await context.route("**/*", guard)
    try:
        if not session or page.is_closed():
            if page.is_closed():
                page=await context.new_page(); SESSIONS[jid]['page']=page
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        content = (await page.content()).lower()
        if await challenge_visible(page):
            return {"manual": True, "reason": "CAPTCHA detected; complete manually"}
        login_visible=await page.locator('input[type="password"]:visible').count()
        if not login_visible and credentials and any(x in content for x in ['sign in','log in','login']):
            await page.goto(credentials['login_url'],wait_until='domcontentloaded',timeout=30000)
            content=(await page.content()).lower()
            if await challenge_visible(page):
                return {'manual':True,'reason':'CAPTCHA detected at login; complete manually'}
            login_visible=await page.locator('input[type="password"]:visible').count()
            if not login_visible:
                return {'manual':True,'reason':'Saved login page has no recognized password form; complete manually'}
        if login_visible:
            if not credentials: return {"manual":True,"reason":"Login required. Save credentials and unlock the vault, then retry preparation."}
            issue=await reuse_login(page,credentials)
            if issue: return {"manual":True,"reason":issue}
            await page.goto(url,wait_until='domcontentloaded',timeout=30000)
            content=(await page.content()).lower()
        if await challenge_visible(page) or await page.locator('input[autocomplete="one-time-code"]:visible, input[type="password"]:visible').count():
            return {"manual":True,"reason":"CAPTCHA, MFA or login still required; complete manually"}
        filled = await adapter_for(url).fill(page, profile, resume)
        await page.screenshot(path=str(screenshot), full_page=True)
        return {"manual": True, "reason": "Browser is open for your review. Complete missing fields or login manually, then retry preparation. Submit yourself only after approval.", "filled": filled}
    finally:
        pass # Session stays open for manual login, CAPTCHA, review and approved manual submission.
