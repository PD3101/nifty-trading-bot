"""
Pull the user's FULL Kite Console tradebook (F&O, historical) automatically.

Kite Connect's public API (kite.trades()) only exposes TODAY's trades, so the
console tradebook must be fetched via the authenticated web session. This
script logs into the Kite WEB APP (kite.zerodha.com), captures the
enctoken cookie, then fetches the console tradebook for the F&O segment.

Intended to run in GitHub Actions (has the Kite login secrets).
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


async def login_kite_web(p):
    """Login to the Kite web app (kite.zerodha.com); return (enctoken, page, context, browser)."""
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
    logger.info("Loaded: %s | %s", page.url, await page.title())

    # Fill credentials — the web login form uses #userid and #password
    try:
        await page.wait_for_selector('#userid', timeout=10000)
    except Exception:
        logger.error("Kite login form not found at %s. Content: %s", page.url, (await page.content())[:800])
        await browser.close()
        return None, None, None, None

    await page.fill('#userid', client_id)
    await page.fill('#password', password)
    await page.click('button[type="submit"]')

    # Wait for TOTP page (or dashboard if no 2FA)
    try:
        await page.wait_for_selector('input[type="number"], input[type="text"][autocomplete="one-time-code"]',
                                     timeout=15000)
        logger.info("TOTP page loaded at %s", page.url)
        totp_input = await page.query_selector('input[type="number"]')
        if not totp_input:
            totp_input = await page.query_selector('input[autocomplete="one-time-code"]')
        if totp_input:
            await totp_input.fill(totp.now())
            await page.wait_for_timeout(500)
        # click continue/submit
        try:
            btn = await page.wait_for_selector('button:has-text("continue"):not([disabled]), '
                                               'button:has-text("Continue"):not([disabled])',
                                               timeout=8000)
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
        logger.info("No separate TOTP page; may already be logged in or 2FA not required: %s", e)

    # Wait for dashboard
    try:
        await page.wait_for_url('**/dashboard**', timeout=20000)
        logger.info("Dashboard loaded: %s", page.url)
    except Exception:
        logger.warning("Did not reach dashboard. Current URL: %s", page.url)

    cookies = await context.cookies()
    logger.info("Cookies: %s", [{'name': c['name'], 'domain': c['domain']} for c in cookies])
    cookie_dict = {c['name']: c['value'] for c in cookies}
    enctoken = cookie_dict.get('enctoken')

    return enctoken, page, context, browser


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
    ]
    for url in candidates:
        status, body = call_api(enctoken, url)
        snippet = body[:200].replace('\n', ' ')
        logger.info("GET %s -> %s :: %s", url.split('?')[0], status, snippet)
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
    for url, body in captured.items():
        print(f"CAPTURED {url}")
        print(body[:200000])
    return None


async def main():
    import playwright.async_api as pw_api

    async with pw_api.async_playwright() as p:
        enctoken, page, context, browser = await login_kite_web(p)

        if not enctoken:
            logger.error("No enctoken captured.")
            sys.exit(2)

        trades = await try_direct_api(enctoken)

        if not trades:
            logger.info("Direct API failed — trying in-browser interception...")
            trades = await fetch_via_browser(page, context)

        await browser.close()

        if trades:
            print(f"TRADEBOOK_TRADES:{len(trades)}")
            print(json.dumps(trades, indent=2, default=str)[:500000])
        else:
            logger.error("All methods failed to fetch tradebook")
            sys.exit(3)


if __name__ == '__main__':
    asyncio.run(main())
