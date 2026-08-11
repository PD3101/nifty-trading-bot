"""
Pull the user's FULL Kite Console tradebook (F&O, historical) automatically.

Kite Connect's public API (kite.trades()) only exposes TODAY's trades, so the
console tradebook must be fetched via the authenticated web session. This
script:
  1. Headless-logins to Kite using the SAME proven flow as the bot's
     refresh_token() (KITE_CLIENT_ID/PASSWORD/TOTP secrets).
  2. Captures the `enctoken` session cookie.
  3. Fetches the Console tradebook for the F&O segment over a date range.
  4. Prints the trades as JSON (consumed by the trade book updater).

Intended to run in GitHub Actions (has the Kite login secrets). The data is
the user's own account data.
"""

import asyncio
import json
import logging
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('tradebook')

IST_OFFSET = timedelta(hours=5, minutes=30)


async def login_and_get_cookies(p, kite_login_url):
    """Copy of the bot's proven refresh_token login; returns cookies dict + page."""
    import pyotp

    client_id = os.getenv('KITE_CLIENT_ID')
    password = os.getenv('KITE_PASSWORD')
    totp_secret = os.getenv('KITE_TOTP_SECRET')
    if not all([client_id, password, totp_secret]):
        raise RuntimeError("Set KITE_CLIENT_ID, KITE_PASSWORD, KITE_TOTP_SECRET env vars")

    totp = pyotp.TOTP(totp_secret)
    request_token = None

    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()

    async def capture_redirect(request):
        nonlocal request_token
        if 'request_token' in request.url:
            m = re.search(r'request_token=([a-zA-Z0-9]+)', request.url)
            if m:
                request_token = m.group(1)

    page.on('request', capture_redirect)

    await page.goto(kite_login_url, timeout=30000)
    await page.wait_for_timeout(5000)

    await page.fill('#userid', client_id)
    await page.fill('#password', password)
    await page.click('button[type="submit"]')
    await page.wait_for_timeout(5000)

    totp_input = await page.query_selector('input[type="number"]')
    if totp_input:
        await totp_input.fill(totp.now())

    buttons = await page.query_selector_all('button')
    for btn in buttons:
        text = await btn.inner_text()
        if 'continue' in text.lower() or 'submit' in text.lower():
            await btn.click()
            break

    await page.wait_for_timeout(8000)

    context = page.context
    cookies = await context.cookies()
    logger.info("Cookie names/domains: %s",
                [{'name': c['name'], 'domain': c['domain']} for c in cookies])
    cookie_dict = {c['name']: c['value'] for c in cookies}

    await browser.close()
    return cookie_dict, request_token


def call_api(enctoken, url):
    """Hit a console endpoint with the enctoken sent as a Cookie header."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'Cookie': f'enctoken={enctoken}',
        'X-Requested-With': 'XMLHttpRequest',
    }
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
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO',
        'https://console.zerodha.com/api/reports/tradebook',
        f'https://console.zerodha.com/reports/tradebook?segment=FO&start_date={start}&end_date={end}',
    ]
    for url in candidates:
        status, body = call_api(enctoken, url)
        snippet = body[:150].replace('\n', ' ')
        logger.info("GET %s -> %s :: %s", url, status, snippet)
        if status == 200 and body.lstrip().startswith('['):
            try:
                return json.loads(body)
            except Exception:
                return None
    return None


async def main():
    from kiteconnect import KiteConnect
    import playwright.async_api as pw_api

    api_key = os.getenv('KITE_API_KEY')
    api_secret = os.getenv('KITE_API_SECRET')
    if not api_key:
        raise RuntimeError("KITE_API_KEY not set")

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()

    async with pw_api.async_playwright() as p:
        cookies, request_token = await login_and_get_cookies(p, login_url)

    enctoken = cookies.get('enctoken')
    logger.info("request_token captured: %s | enctoken present: %s",
                bool(request_token), bool(enctoken))

    trades = None
    if enctoken:
        trades = await try_direct_api(enctoken)

    if trades:
        print(f"TRADEBOOK_TRADES:{len(trades)}")
        print(json.dumps(trades, indent=2, default=str)[:500000])
    else:
        logger.error("Could not fetch tradebook (enctoken=%s, request_token=%s)",
                     bool(enctoken), bool(request_token))
        sys.exit(3)


if __name__ == '__main__':
    asyncio.run(main())
