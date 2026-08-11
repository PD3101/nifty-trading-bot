"""
Pull the user's FULL Kite Console tradebook (F&O, historical) automatically.

Kite Connect's public API (kite.trades()) only exposes TODAY's trades, so the
console tradebook must be fetched via the authenticated web session. This
script logs into the Kite web app (kite.zerodha.com), then makes the console
API calls from INSIDE the authenticated browser page (in-page fetch carries
the enctoken cookie + passes Cloudflare bot-check).

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

    try:
        await page.wait_for_url('**/dashboard**', timeout=20000)
        logger.info("Dashboard loaded: %s", page.url)
    except Exception:
        logger.warning("Did not reach dashboard. URL: %s", page.url)

    cookies = {c['name']: c['value'] for c in await context.cookies()}
    enctoken = cookies.get('enctoken')
    logger.info("Has enctoken cookie: %s", bool(enctoken))
    if enctoken:
        # The web login sets enctoken on kite.zerodha.com; replicate it for
        # the console domain so console.zerodha.com gets authenticated too.
        try:
            await context.add_cookies([{
                'name': 'enctoken', 'value': enctoken,
                'domain': 'zerodha.com', 'path': '/',
            }])
            logger.info("Added enctoken cookie for .zerodha.com")
        except Exception as e:
            logger.warning("Could not add console cookie: %s", e)
    return page, context, browser


async def fetch_in_page(page, url, csrf=None):
    """Fetch a URL from inside the console page (carries cookies + Cloudflare)."""
    csrf_arg = csrf or ''
    result = await page.evaluate("""async ({url, csrf}) => {
        try {
            const headers = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'};
            if (csrf) headers['X-CSRFToken'] = csrf;
            const r = await fetch(url, {headers});
            const text = await r.text();
            return {status: r.status, ok: r.ok, len: text.length, head: text.slice(0, 400)};
        } catch (e) {
            return {status: -1, ok: false, len: 0, head: 'EXC: ' + String(e)};
        }
    }""", {'url': url, 'csrf': csrf_arg})
    logger.info("EVAL %s -> %s", url.split('?')[0], json.dumps(result))
    return result


async def try_tradebook_endpoints(page, csrf, cookies):
    """Try plausible console tradebook URLs via in-page fetch; return JSON list or None."""
    now_ist = datetime.utcnow() + IST_OFFSET
    start = (now_ist - timedelta(days=14)).strftime('%Y-%m-%d')
    end = now_ist.strftime('%Y-%m-%d')

    candidates = [
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO&start_date={start}&end_date={end}',
        f'https://console.zerodha.com/api/reports/tradebook?segment=FO',
        'https://console.zerodha.com/api/reports/tradebook',
    ]
    for url in candidates:
        result = await fetch_in_page(page, url, csrf)
        head = result.get('head', '')
        if result.get('status') == 200 and result.get('len', 0) > 0 and head.lstrip().startswith('['):
            # fetch the full body
            full = await page.evaluate("""async ({url, csrf}) => {
                const h = {'X-Requested-With':'XMLHttpRequest','Accept':'application/json'};
                if (csrf) h['X-CSRFToken'] = csrf;
                return await (await fetch(url, {headers:h})).text();
            }""", {'url': url, 'csrf': csrf or ''})
            try:
                return json.loads(full)
            except Exception:
                pass
    return None


async def main():
    import playwright.async_api as pw_api

    async with pw_api.async_playwright() as p:
        page, context, browser = await login_kite_web(p)

        # 1) Log into the console via SSO (it reuses the Kite web session).
        try:
            await page.goto('https://console.zerodha.com/', wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(5000)
            logger.info("Console URL after goto: %s", page.url)
            # If a login page is shown, click through (SSO via existing Kite session).
            login_btn = await page.query_selector('a[href*="login"], button:has-text("Login"), '
                                                  'button:has-text("Continue"), a:has-text("Login")')
            if login_btn:
                logger.info("Console login prompt found — clicking through SSO")
                await login_btn.click()
                await page.wait_for_timeout(8000)
            logger.info("Console after SSO: %s | %s", page.url, await page.title())
        except Exception as e:
            logger.warning("console login nav error: %s", e)

        # 2) Open the tradebook page.
        try:
            await page.goto('https://console.zerodha.com/reports/tradebook',
                            wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(8000)
            logger.info("Tradebook page: %s | %s", page.url, await page.title())
        except Exception as e:
            logger.warning("tradebook nav error: %s", e)

        # 3) Grab the CSRF token (cookie or meta) for the console API.
        console_cookies = {c['name']: c['value'] for c in await context.cookies()}
        csrf = console_cookies.get('csrf') or console_cookies.get('_csrf')
        logger.info("Console cookies: %s", [{'name': k, 'has': bool(v)} for k, v in console_cookies.items()])
        if not csrf:
            try:
                csrf = await page.evaluate(
                    """() => { const m = document.querySelector('meta[name="csrf-token"]'); return m ? m.getAttribute('content') : null; }""")
            except Exception:
                pass
        logger.info("CSRF token found: %s", bool(csrf))

        trades = await try_tradebook_endpoints(page, csrf, console_cookies)
        await browser.close()

        if trades:
            print(f"TRADEBOOK_TRADES:{len(trades)}")
            print(json.dumps(trades, indent=2, default=str)[:500000])
        else:
            logger.error("Could not fetch tradebook from console")
            sys.exit(3)


if __name__ == '__main__':
    asyncio.run(main())
