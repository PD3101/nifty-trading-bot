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
    logger.info("Has enctoken cookie: %s", 'enctoken' in cookies)
    return page, context, browser


async def fetch_in_page(page, url):
    """Fetch a URL from inside the console page (carries cookies + Cloudflare)."""
    return await page.evaluate("""async (url) => {
        try {
            const r = await fetch(url, {
                headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}
            });
            const text = await r.text();
            return {status: r.status, body: text};
        } catch (e) {
            return {status: -1, body: String(e)};
        }
    }""", url)


async def try_tradebook_endpoints(page):
    """Try plausible console tradebook URLs via in-page fetch; return JSON list or None."""
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
        status, body = await fetch_in_page(page, url)
        snippet = body[:200].replace('\n', ' ')
        logger.info("FETCH %s -> %s :: %s", url.split('?')[0], status, snippet)
        if status == 200 and body.lstrip().startswith('['):
            try:
                return json.loads(body)
            except Exception:
                pass
    return None


async def main():
    import playwright.async_api as pw_api

    async with pw_api.async_playwright() as p:
        page, context, browser = await login_kite_web(p)

        # Load console tradebook page once (passes Cloudflare, sets console cookies).
        try:
            await page.goto('https://console.zerodha.com/reports/tradebook',
                            wait_until='domcontentloaded', timeout=45000)
            await page.wait_for_timeout(8000)
            logger.info("Console tradebook page loaded: %s", page.url)
        except Exception as e:
            logger.warning("console nav error: %s", e)

        trades = await try_tradebook_endpoints(page)
        await browser.close()

        if trades:
            print(f"TRADEBOOK_TRADES:{len(trades)}")
            print(json.dumps(trades, indent=2, default=str)[:500000])
        else:
            logger.error("Could not fetch tradebook from console")
            sys.exit(3)


if __name__ == '__main__':
    asyncio.run(main())
