"""
Pull the user's FULL Kite Console tradebook (F&O, historical) automatically.

Kite Connect's public API (kite.trades()) only exposes TODAY's trades, so the
console tradebook must be fetched via the web session. This script:
  1. Headless-logins to Kite web (KITE_CLIENT_ID/PASSWORD/TOTP secrets).
  2. Captures the `enctoken` cookie.
  3. Calls the Console tradebook API for the F&O segment over a date range.
  4. Prints the trades as JSON (consumed by the trade book updater).

Intended to run in GitHub Actions (has the Kite login secrets). Fetched data
is the user's own account data.
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


async def login_and_get_enctoken():
    """Headless Kite web login → return the enctoken string (or None)."""
    import pyotp
    from playwright.async_api import async_playwright

    client_id = os.getenv('KITE_CLIENT_ID')
    password = os.getenv('KITE_PASSWORD')
    totp_secret = os.getenv('KITE_TOTP_SECRET')
    if not all([client_id, password, totp_secret]):
        raise RuntimeError("Set KITE_CLIENT_ID, KITE_PASSWORD, KITE_TOTP_SECRET env vars")

    totp = pyotp.TOTP(totp_secret)
    enctoken = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        logger.info("Opening Kite web login...")
        await page.goto('https://kite.trade/', wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)

        # If already logged in (cookies), we may land on dashboard directly.
        if page.url.startswith('https://kite.trade/dashboard'):
            logger.info("Already logged in.")
        else:
            await page.fill('#userid', client_id)
            await page.fill('#password', password)
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(4000)

            totp_input = await page.query_selector('input[type="number"]')
            if totp_input:
                await totp_input.fill(totp.now())
                await page.wait_for_timeout(1000)
            buttons = await page.query_selector_all('button')
            for btn in buttons:
                text = await btn.inner_text()
                if 'continue' in text.lower():
                    await btn.click()
                    break
            await page.wait_for_timeout(6000)

        # Read cookies — enctoken is set on the zerodha/kite domain after login.
        cookies = await context.cookies()
        for c in cookies:
            if c['name'] == 'enctoken':
                enctoken = c['value']
                logger.info(f"Captured enctoken (domain={c['domain']})")
        if not enctoken:
            logger.warning("enctoken cookie not found; cookies present: %s",
                           [c['name'] for c in cookies])
        await browser.close()

    return enctoken


def call_console_api(enctoken, url):
    """Hit a console.zerodha.com endpoint with the enctoken cookie."""
    import urllib.request

    req = urllib.request.Request(url, headers={
        'Cookie': f'enctoken={enctoken}',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'X-Requested-With': 'XMLHttpRequest',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return resp.status, body
    except Exception as e:
        return getattr(e, 'code', 'ERR'), str(e)


async def main():
    enctoken = await login_and_get_enctoken()
    if not enctoken:
        logger.error("No enctoken — cannot fetch console tradebook")
        sys.exit(2)

    # Date range: last 10 days (covers 31-Jul … 11-Aug) in IST.
    now_ist = datetime.utcnow() + IST_OFFSET
    start = (now_ist - timedelta(days=10)).strftime('%Y-%m-%d')
    end = now_ist.strftime('%Y-%m-%d')

    # Try plausible console tradebook report endpoints.
    attempts = [
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO&start_date={start}&end_date={end}',
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO',
        'https://console.zerodha.com/api/reports/tradebook',
    ]
    for url in attempts:
        status, body = call_console_api(enctoken, url)
        logger.info("GET %s -> %s (%d bytes)", url.split('?')[0], status, len(body))
        if status == 200 and ('trade' in body.lower() or body.lstrip().startswith('[')):
            print(f"ENDPOINT_OK {url.split('?')[0]}")
            print(body[:200000])
            return
        else:
            print(f"ATTEMPT {status} {url.split('?')[0]} :: {body[:300]}")


if __name__ == '__main__':
    asyncio.run(main())
