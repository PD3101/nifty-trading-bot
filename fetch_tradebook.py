"""
Pull the user's FULL Kite Console tradebook (F&O, historical) automatically.

Logs into Kite web + console (SSO), opens the tradebook page, captures the
working request headers from the page's own heatmap call, then calls the
tradebook data endpoint with the same headers (and a date range) via an
in-page fetch. Prints the trades as JSON.

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

    heatmap_headers = {}

    async with pw_api.async_playwright() as p:
        page, context, browser = await login_kite_web(p)
        await console_ssos(page)

        async def on_request(req):
            if 'heatmap' in req.url or 'tradebook' in req.url:
                heatmap_headers.update({k: v for k, v in req.headers.items()})
                logger.info("CAPTURED HEADERS from %s: %s", req.url,
                            json.dumps({k: v[:40] for k, v in req.headers.items()}))

        page.on('request', on_request)

        await page.goto('https://console.zerodha.com/reports/tradebook',
                        wait_until='domcontentloaded', timeout=45000)
        await page.wait_for_timeout(12000)

        # Call the tradebook data endpoint with the page's own headers + date range
        now_ist = datetime.utcnow() + IST_OFFSET
        start = (now_ist - timedelta(days=14)).strftime('%Y-%m-%d')
        end = now_ist.strftime('%Y-%m-%d')
        candidates = [
            f'https://console.zerodha.com/api/reports/tradebook?segment=FO&start_date={start}&end_date={end}',
            f'https://console.zerodha.com/api/reports/tradebook?segment=FO',
            'https://console.zerodha.com/api/reports/tradebook',
        ]
        found = None
        for url in candidates:
            result = await page.evaluate(
                """async ({url, headers}) => {
                    try {
                        const r = await fetch(url, {headers: headers, credentials: 'include'});
                        const text = await r.text();
                        return {status: r.status, len: text.length, head: text.slice(0, 300)};
                    } catch (e) {
                        return {status: -1, len: 0, head: 'EXC: ' + String(e)};
                    }
                }""",
                {'url': url, 'headers': dict(heatmap_headers)})
            logger.info("DATA %s -> %s", url.split('?')[0], json.dumps(result))
            if result.get('status') == 200 and result.get('head', '').lstrip().startswith('['):
                full = await page.evaluate(
                    """async ({url, headers}) => await (await fetch(url, {headers: headers, credentials: 'include'})).text()""",
                    {'url': url, 'headers': dict(heatmap_headers)})
                try:
                    found = json.loads(full)
                    break
                except Exception:
                    pass

        await browser.close()

    if found:
        print(f"TRADEBOOK_TRADES:{len(found)}")
        print(json.dumps(found, indent=2, default=str)[:600000])
    else:
        logger.error("Could not fetch tradebook data")
        sys.exit(3)


if __name__ == '__main__':
    asyncio.run(main())
