"""
Pull the user's FULL Kite Console tradebook (F&O, historical) automatically.

Kite Connect's public API (kite.trades()) only exposes TODAY's trades, so the
console tradebook must be fetched via the authenticated web session. This
script:
  1. Headless-logins to Kite web (KITE_CLIENT_ID/PASSWORD/TOTP secrets).
  2. Captures the `enctoken` cookie.
  3. Fetches the Console tradebook for the F&O segment over a date range —
     first via direct console API calls, then (fallback) by loading the
     console tradebook page and intercepting its own API responses.
  4. Prints the trades as JSON (consumed by the trade book updater).

Intended to run in GitHub Actions (has the Kite login secrets). The data is
the user's own account data.
"""

import asyncio
import json
import logging
import os
import sys
import urllib.request
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('tradebook')

IST_OFFSET = timedelta(hours=5, minutes=30)


async def login_and_get_enctoken(p):
    """Headless Kite web login → (enctoken, page, context) or raise."""
    import pyotp
    from playwright.async_api import async_playwright

    client_id = os.getenv('KITE_CLIENT_ID')
    password = os.getenv('KITE_PASSWORD')
    totp_secret = os.getenv('KITE_TOTP_SECRET')
    if not all([client_id, password, totp_secret]):
        raise RuntimeError("Set KITE_CLIENT_ID, KITE_PASSWORD, KITE_TOTP_SECRET env vars")

    totp = pyotp.TOTP(totp_secret)
    browser = await p.chromium.launch(headless=True)
    context = await browser.new_context()
    page = await context.new_page()

    # Kite web app login. Try both hosts; the form uses #userid/#password.
    urls = ['https://kite.zerodha.com/', 'https://kite.trade/']
    for url in urls:
        try:
            logger.info("Opening %s", url)
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            break
        except Exception as e:
            logger.warning("goto %s failed: %s", url, e)

    await page.wait_for_timeout(3000)
    logger.info("URL after open: %s | title: %s", page.url, await page.title())

    need_login = (
        'login' in page.url.lower()
        or await page.query_selector('#userid')
        or await page.query_selector('#password')
    )
    if need_login:
        uid = await page.query_selector('#userid')
        pwd = await page.query_selector('#password')
        if not uid or not pwd:
            body = await page.content()
            logger.error("Login form not found. URL=%s Body=%s", page.url, body[:1200])
            raise RuntimeError("Login form not found")
        await uid.fill(client_id)
        await pwd.fill(password)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(5000)

        totp_input = await page.query_selector('input[type="number"]')
        if totp_input:
            await totp_input.fill(totp.now())
            await page.wait_for_timeout(800)
        buttons = await page.query_selector_all('button')
        for btn in buttons:
            try:
                t = (await btn.inner_text()) or ''
            except Exception:
                continue
            if 'continue' in t.lower():
                await btn.click()
                break
        await page.wait_for_timeout(8000)
        logger.info("Post-login URL: %s | title: %s", page.url, await page.title())
    else:
        logger.info("Already on a logged-in page.")

    enctoken = None
    cookies = await context.cookies()
    logger.info("Cookies: %s", [{'name': c['name'], 'domain': c['domain']} for c in cookies])
    for c in cookies:
        if c['name'] == 'enctoken':
            enctoken = c['value']
            logger.info("Captured enctoken (domain=%s)", c['domain'])

    return enctoken, page, context, browser


def call_api(enctoken, url, use_header=False):
    """Hit a console endpoint with the enctoken (cookie or Authorization header)."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
    }
    if use_header:
        headers['Authorization'] = f'enctoken {enctoken}'
        req = urllib.request.Request(url, headers=headers)
    else:
        headers['Cookie'] = f'enctoken={enctoken}'
        req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return resp.status, body
    except Exception as e:
        return getattr(e, 'code', 'ERR'), str(e)


async def try_direct_api(enctoken):
    """Try plausible console tradebook endpoints; return JSON list or None."""
    now_ist = datetime.utcnow() + IST_OFFSET
    start = (now_ist - timedelta(days=14)).strftime('%Y-%m-%d')
    end = now_ist.strftime('%Y-%m-%d')

    candidates = [
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO&start_date={start}&end_date={end}',
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO&from={start}&to={end}',
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO',
        'https://console.zerodha.com/api/reports/tradebook',
    ]
    for url in candidates:
        for use_header in (False, True):
            status, body = call_api(enctoken, url, use_header=use_header)
            snippet = body[:150].replace('\n', ' ')
            logger.info("GET %s [hdr=%s] -> %s :: %s", url.split('?')[0], use_header, status, snippet)
            if status == 200 and body.lstrip().startswith('['):
                try:
                    return json.loads(body)
                except Exception:
                    return None
    return None


async def fetch_via_browser(page, context):
    """Load the console tradebook page and capture its own API responses."""
    captured = {}

    async def on_response(resp):
        url = resp.url
        if 'tradebook' in url or ('reports' in url and 'segment' in url):
            try:
                body = await resp.text()
                captured[url] = body[:500000]
            except Exception:
                pass

    page.on('response', on_response)
    logger.info("Navigating to console tradebook page...")
    try:
        await page.goto('https://console.zerodha.com/reports/tradebook',
                        wait_until='domcontentloaded', timeout=45000)
        await page.wait_for_timeout(15000)
    except Exception as e:
        logger.warning("console nav error: %s", e)

    logger.info("Captured %d response(s): %s", len(captured), list(captured.keys()))
    for url, body in captured.items():
        if body.lstrip().startswith('['):
            try:
                return json.loads(body)
            except Exception:
                pass
    # Fall back: dump any captured bodies for diagnosis
    for url, body in captured.items():
        print(f"CAPTURED {url}")
        print(body[:200000])
    return None


async def main():
    import playwright.async_api as pw_api
    async with pw_api.async_playwright() as p:
        enctoken, page, context, browser = await login_and_get_enctoken(p)

        trades = None
        if enctoken:
            trades = await try_direct_api(enctoken)

        if not trades:
            logger.info("Direct API failed — trying in-browser interception...")
            trades = await fetch_via_browser(page, context)

        await browser.close()

        if trades:
            print(f"TRADEBOOK_TRADES:{len(trades)}")
            print(json.dumps(trades, indent=2, default=str)[:500000])
        else:
            logger.error("Could not fetch tradebook from any method")
            sys.exit(3)


if __name__ == '__main__':
    asyncio.run(main())
