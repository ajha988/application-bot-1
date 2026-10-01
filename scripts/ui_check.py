"""Optional local browser smoke test, requires Playwright Chromium installed."""
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(viewport={"width":1440,"height":1080})
    page.goto('http://127.0.0.1:8000')
    page.get_by_role('button').filter(has_text='Northstar Demo').click()
    page.get_by_role('button',name='Parse JD & score').click()
    page.get_by_role('button',name='Generate tailored resume').click()
    page.get_by_role('button',name='Prepare form').click()
    page.get_by_role('button',name='I reviewed all fields · request approval').click()
    page.get_by_role('button',name='Approve revision 1').wait_for()
    assert page.get_by_text('awaiting approval',exact=True).count()>=1
    page.screenshot(path=str(Path(__file__).resolve().parents[1]/'dashboard-preview.png'),full_page=True)
    browser.close()
