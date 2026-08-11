"""
Diagnose how console.zerodha.com/reports/tradebook loads its data.

Logs in (Kite web + console SSO), opens the tradebook page, and prints:
  - every XHR/fetch request (method, url, resourceType, headers)
  - every JSON response (status, url, body snippet)
  - the page HTML (to spot server-rendered data / date inputs / download button)
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('tradebook')

IST_OFFSET = timedelta(hours=5, minutes=30)


async def login_kite_web(p):
    import pyotp
    client_id = os.getenv('KITE_CLIENT_ID')
    password = os.getenv('KITE_PASSWORD')
    totp_secret = os.getenv('KITE_TOTP_SECRET')
    if not all([client_id, password, totp_secret]):
        raise RuntimeError("Missing KITE_CLIENT_ID/PASSWORD/TOTP_SECRET")
    totp = pyotp.TOTP(totp_secret)
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto('https://kite.zerodha.com/', wait_until='networkidle', timeout=30000)
    await page.wait_for_selector('#userid', timeout=10000)
    await page.fill('#userid', client_id)
    await page.fill('#password', password)
    await page.click('button[type="submit"]')
    try:
        await page.wait_for_selector('input[type="number"]', timeout=15000)
        ti = await page.query_selector('input[type="number"]')
        if ti:
            await ti.fill(totp.now())
            await page.wait_for_timeout(500)
        try:
            btn = await page.wait_for_selector('button:has-text("continue"):not([disabled]), '
                                               'button:has-text("Continue"):not([disabled])', timeout=8000)
            await btn.click()
        except Exception:
            for btn in await page.query_selector_all('button'):
                try:
                    t = (await btn.inner_text()) or ''
                except Exception:
                    continue
                if 'continue' in t.lower() or 'submit' in t.lower():
                    await btn.click()
                    break
    except Exception:
        pass
    await page.wait_for_url('**/dashboard**', timeout=20000)
    logger.info("Kite dashboard: %s", page.url)
    return page, context, browser


async def console_ssos(page):
    try:
        await page.goto('https://console.zerodha.com/', wait_until='domcontentloaded', timeout=45000)
        await page.wait_for_timeout(4000)
        btn = await page.query_selector(
            'a[href*="login"], button:has-text("Login"), a:has-text("Login"), button:has-text("Continue")')
        if btn:
            await btn.click()
            await page.wait_for_timeout(8000)
        logger.info("Console after SSO: %s | %s", page.url, await page.title())
    except Exception as e:
        logger.warning("console SSO: %s", e)


async def main():
    import playwright.async_api as pw_api

    async with pw_api.async_playwright() as p:
        page, context, browser = await login_kite_web(p)
        await console_ssos(page)

        requests = []
        responses = []

        async def on_request(req):
            if req.resource_type in ('xhr', 'fetch'):
                requests.append({'method': req.method, 'url': req.url})

        async def on_response(resp):
            ct = resp.headers.get('content-type', '')
            if 'json' in ct or 'api/report' in resp.url:
                try:
                    body = await resp.text()
                except Exception:
                    body = ''
                responses.append({'status': resp.status, 'url': resp.url,
                                  'ct': ct, 'body': body[:2000]})

        page.on('request', on_request)
        page.on('response', on_response)

        await page.goto('https://console.zerodha.com/reports/tradebook',
                        wait_until='domcontentloaded', timeout=45000)
        await page.wait_for_timeout(25000)

        html = await page.content()
        logger.info("Tradebook page: %s | HTML length=%d", page.url, len(html))

        await browser.close()

    # Emit diagnostics
    print("=== XHR/FETCH REQUESTS ===")
    for r in requests:
        print(json.dumps(r))
    print("=== JSON/REPORT RESPONSES ===")
    for r in responses:
        print(json.dumps(r)[:1500])
    print("=== HTML markers ===")
    import re
    for m in re.findall(r'<input[^>]*date[^>]*>|download|Download|start_date|end_date|data-range|range', html, re.I)[:40]:
        print(m)
    print("HTML_LEN", len(html))


if __name__ == '__main__':
    asyncio.run(main())
