"""
Pull the user's FULL Kite Console tradebook (F&O, historical) automatically.

Kite Connect's public API only returns TODAY's trades. This script logs into
the Kite web app + console (SSO), opens the console tradebook page, and
intercepts the page's OWN network requests to capture the tradebook data
(and the CSRF mechanism the app uses).

Intended to run in GitHub Actions (has the Kite login secrets).
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
    """Login to the Kite web app; return (page, context, browser)."""
    import pyotp

    client_id = os.getenv('KITE_CLIENT_ID')
    password = os.getenv('KITE_PASSWORD')
    totp_secret = os.getenv('KITE_TOTP_SECRET')
    if not all([client_id, password, totp_secret]):
        raise RuntimeError("Set KITE_CLIENT_ID, KITE_PASSWORD, KITE_TOTP_SECRET")

    totp = pyotp.TOTP(totp_secret)
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    logger.info("Navigating to kite.zerodha.com...")
    await page.goto('https://kite.zerodha.com/', wait_until='networkidle', timeout=30000)
    await page.wait_for_selector('#userid', timeout=10000)

    await page.fill('#userid', client_id)
    await page.fill('#password', password)
    await page.click('button[type="submit"]')

    try:
        await page.wait_for_selector('input[type="number"]', timeout=15000)
        totp_input = await page.query_selector('input[type="number"]')
        if totp_input:
            await totp_input.fill(totp.now())
            await page.wait_for_timeout(500)
        try:
            btn = await page.wait_for_selector('button:has-text("continue"):not([disabled]), '
                                               'button:has-text("Continue"):not([disabled])', timeout=8000)
            await btn.click()
        except Exception:
            buttons = await page.query_selector_all('button')
            for btn in buttons:
                try:
                    text = (await btn.inner_text()) or ''
                except Exception:
                    continue
                if 'continue' in text.lower() or 'submit' in text.lower():
                    await btn.click()
                    break
    except Exception as e:
        logger.info("No TOTP page / already logged in: %s", e)

    await page.wait_for_url('**/dashboard**', timeout=20000)
    logger.info("Kite dashboard loaded: %s", page.url)
    return page, context, browser


async def console_ssos(page):
    """Log the console in via SSO using the Kite session."""
    try:
        await page.goto('https://console.zerodha.com/', wait_until='domcontentloaded', timeout=45000)
        await page.wait_for_timeout(4000)
        logger.info("Console URL: %s | %s", page.url, await page.title())
        login_btn = await page.query_selector(
            'a[href*="login"], button:has-text("Login"), a:has-text("Login"), button:has-text("Continue")')
        if login_btn:
            logger.info("Clicking console login (SSO)")
            await login_btn.click()
            await page.wait_for_timeout(8000)
        logger.info("Console after SSO: %s | %s", page.url, await page.title())
    except Exception as e:
        logger.warning("console SSO error: %s", e)


async def main():
    import playwright.async_api as pw_api

    captured_reqs = []
    captured_resps = []

    async with pw_api.async_playwright() as p:
        page, context, browser = await login_kite_web(p)
        await console_ssos(page)

        async def on_request(req):
            url = req.url
            if '/api/reports/' in url:
                hdrs = {k: v for k, v in req.headers.items()}
                captured_reqs.append({'method': req.method, 'url': url, 'headers': hdrs})
                logger.info("REQ %s %s", req.method, url)
                logger.info("    headers: %s", json.dumps({k: (v[:60]) for k, v in hdrs.items()}))

        async def on_response(resp):
            url = resp.url
            if '/api/reports/' in url:
                try:
                    body = await resp.text()
                except Exception:
                    body = ''
                captured_resps.append({'status': resp.status, 'url': url, 'body': body[:300000]})
                logger.info("RESP %s %s (%d bytes)", resp.status, url, len(body))

        page.on('request', on_request)
        page.on('response', on_response)

        # Open the tradebook page — it fires its own data requests on load.
        await page.goto('https://console.zerodha.com/reports/tradebook',
                        wait_until='domcontentloaded', timeout=45000)
        await page.wait_for_timeout(25000)
        logger.info("Tradebook page: %s | %s", page.url, await page.title())

        await browser.close()

    # Print captured requests (to learn the CSRF mechanism)
    if not captured_reqs:
        logger.error("No /api/reports/ requests captured")
        sys.exit(3)

    # Emit the trade data from any response that looks like a trade list
    found = False
    for r in captured_resps:
        body = r['body']
        if body.lstrip().startswith('['):
            try:
                trades = json.loads(body)
                print(f"TRADEBOOK_TRADES:{len(trades)}")
                print(json.dumps(trades, indent=2, default=str)[:600000])
                found = True
            except Exception:
                pass
    if not found:
        print("CAPTURED_REQUEST_HEADERS")
        for r in captured_reqs:
            print(json.dumps(r)[:2000])


if __name__ == '__main__':
    asyncio.run(main())
