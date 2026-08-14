"""
Kite Connect data fetcher — fetches NIFTY futures 3m candles.

Replaces yfinance (which only has spot data) with actual NIFTY futures
data from Zerodha Kite Connect. This is critical because the strategy
runs on the FUTURES chart, not the spot index.

Handles:
- Credential loading (from env vars or kite_credentials.json)
- Auto-selecting the nearest month NIFTY futures contract
- Fetching 3m OHLCV candles
- Token refresh via TOTP auto-login (for GitHub Actions automation)
"""

import json
import os
import sys
import logging
from datetime import datetime, timedelta

import pandas as pd
import pytz

import config

logger = logging.getLogger('kite_fetcher')

IST = pytz.timezone('Asia/Kolkata')


def load_credentials():
    """Load Kite credentials from env vars or kite_credentials.json.

    The persisted kite_credentials.json (cached & restored across GitHub
    Actions runs) is the source of truth for the ACCESS TOKEN. The env
    KITE_ACCESS_TOKEN is a static secret that goes stale, which forced a
    fresh login on EVERY run and logged the user out of other Kite devices
    every ~2 minutes. Prefer the file token so one login is reused for its
    full ~24h validity; env creds are only a fallback when no file exists.
    """
    api_key = os.getenv('KITE_API_KEY')
    api_secret = os.getenv('KITE_API_SECRET')
    access_token = os.getenv('KITE_ACCESS_TOKEN')

    # Prefer the persisted (refreshed) token from the cache file.
    cred_file = os.path.join(os.path.dirname(__file__), 'kite_credentials.json')
    file_creds = None
    if os.path.exists(cred_file):
        try:
            with open(cred_file) as f:
                file_creds = json.load(f)
        except Exception:
            file_creds = None

    if file_creds and file_creds.get('access_token'):
        api_key = file_creds.get('api_key') or api_key
        api_secret = file_creds.get('api_secret') or api_secret
        access_token = file_creds['access_token']
        return api_key, api_secret, access_token

    # Fallback to env vars (e.g. first deploy, before any token is cached).
    if api_key and api_secret and access_token:
        return api_key, api_secret, access_token

    return None, None, None


def get_kite_client():
    """Initialize and return an authenticated KiteConnect client.
    Auto-refreshes token if expired or missing."""
    from kiteconnect import KiteConnect

    api_key, api_secret, access_token = load_credentials()

    if not api_key:
        raise RuntimeError("KITE_API_KEY not found in env or kite_credentials.json")

    # Try existing token first
    if access_token:
        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        try:
            # Test if token is valid by making a simple API call
            kite.profile()
            return kite
        except Exception:
            logger.info("Token expired, refreshing...")

    # Token missing or expired — auto-refresh via headless browser
    logger.info("Auto-refreshing Kite token via headless browser + TOTP...")
    try:
        new_token = refresh_token(api_key, api_secret)

        # Save refreshed token
        creds = {'api_key': api_key, 'api_secret': api_secret, 'access_token': new_token}
        cred_file = os.path.join(os.path.dirname(__file__), 'kite_credentials.json')
        with open(cred_file, 'w') as f:
            json.dump(creds, f, indent=2)

        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(new_token)
        logger.info(f"Token refreshed successfully for {kite.profile().get('user_name', 'unknown')}")
        return kite

    except Exception as e:
        raise RuntimeError(f"Failed to refresh Kite token: {e}")


def get_nearest_nifty_fut(kite):
    """Find the nearest-month NIFTY futures contract."""
    instruments = kite.instruments("NFO")
    today = datetime.now(IST).date()

    nifty_fut = [
        i for i in instruments
        if i.get('name') == 'NIFTY'
        and i.get('instrument_type') == 'FUT'
        and i.get('exchange') == 'NFO'
        and i['expiry'] > today
    ]

    if not nifty_fut:
        raise RuntimeError("No NIFTY futures contracts found")

    # Nearest expiry first
    nifty_fut.sort(key=lambda x: x['expiry'])
    return nifty_fut[0]


def format_weekly_symbol(expiry_date, strike, option_type):
    """NSE weekly option tradingsymbol, e.g. NIFTY21AUG24800CE."""
    mon = expiry_date.strftime('%d%b').upper()
    suffix = 'CE' if option_type == 'CALL' else 'PE'
    return f"NIFTY{mon}{int(strike)}{suffix}"


def next_weekly_expiry(from_date=None):
    """Next date whose weekday == config.EXPIRY_DAY (⚠️ verify vs NSE calendar)."""
    from_date = from_date or datetime.now(IST).date()
    d = from_date
    for _ in range(7):
        if d.weekday() == config.EXPIRY_DAY:
            return d
        d += timedelta(days=1)
    return from_date


def resolve_weekly_option(kite, expiry_date, strike, option_type):
    """Return (tradingsymbol, instrument_token) for the NIFTY weekly option, or (sym, None)."""
    sym = format_weekly_symbol(expiry_date, strike, option_type)
    try:
        instruments = kite.instruments("NFO")
        for i in instruments:
            if i.get('tradingsymbol') == sym and i.get('exchange') == 'NFO':
                return i['tradingsymbol'], i['instrument_token']
    except Exception as e:
        logger.error(f"Option resolve failed: {e}")
    return sym, None


def fetch_3m_data(lookback_days=5):
    """
    Fetch NIFTY futures 3m candles from Kite Connect.

    Returns:
        pd.DataFrame with columns [open, high, low, close, volume]
        and datetime index (IST timezone), or None on failure.
    """
    try:
        kite = get_kite_client()
        contract = get_nearest_nifty_fut(kite)

        logger.info(f"Using {contract['tradingsymbol']} "
                     f"(token={contract['instrument_token']}, "
                     f"expiry={contract['expiry']}, "
                     f"lot={contract['lot_size']})")

        to_date = datetime.now(IST)
        from_date = to_date - timedelta(days=lookback_days)

        candles = kite.historical_data(
            instrument_token=contract['instrument_token'],
            from_date=from_date.strftime('%Y-%m-%d'),
            to_date=to_date.strftime('%Y-%m-%d'),
            interval='3minute'
        )

        if not candles:
            logger.error("No candle data returned from Kite")
            return None

        df = pd.DataFrame(candles)
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df.index.name = None  # Avoid ambiguity with 'date' column in VWAP calc
        df.columns = [c.lower() for c in df.columns]

        # Ensure timezone is IST
        if df.index.tz is None:
            df.index = df.index.tz_localize('Asia/Kolkata')
        else:
            df.index = df.index.tz_convert('Asia/Kolkata')

        # Keep only OHLCV
        df = df[['open', 'high', 'low', 'close', 'volume']]

        logger.info(f"Fetched {len(df)} candles: {df.index[0]} to {df.index[-1]}")
        return df

    except Exception as e:
        logger.error(f"Failed to fetch Kite data: {e}")
        return None


def refresh_token(api_key, api_secret):
    """
    Fully automated Kite token refresh using headless browser + TOTP.

    Requires env vars: KITE_CLIENT_ID, KITE_PASSWORD, KITE_TOTP_SECRET
    Returns: access_token string
    """
    import asyncio
    import pyotp
    import re
    from kiteconnect import KiteConnect

    client_id = os.getenv('KITE_CLIENT_ID')
    password = os.getenv('KITE_PASSWORD')
    totp_secret = os.getenv('KITE_TOTP_SECRET')

    if not all([client_id, password, totp_secret]):
        raise RuntimeError(
            "Set KITE_CLIENT_ID, KITE_PASSWORD, KITE_TOTP_SECRET env vars"
        )

    async def _login():
        from playwright.async_api import async_playwright
        totp = pyotp.TOTP(totp_secret)
        kite = KiteConnect(api_key=api_key)
        request_token = None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            async def capture_redirect(request):
                nonlocal request_token
                if 'request_token' in request.url:
                    m = re.search(r'request_token=([a-zA-Z0-9]+)', request.url)
                    if m:
                        request_token = m.group(1)

            page.on('request', capture_redirect)

            await page.goto(kite.login_url(), timeout=30000)
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
            await browser.close()

        if not request_token:
            raise RuntimeError("Failed to capture request_token from login")

        token_data = kite.generate_session(request_token, api_secret=api_secret)
        return token_data['access_token']

    return asyncio.run(_login())


def manual_login():
    """Interactive login flow — generates access token."""
    from kiteconnect import KiteConnect

    api_key = os.getenv('KITE_API_KEY', input("API Key: "))
    api_secret = os.getenv('KITE_API_SECRET', input("API Secret: "))

    kite = KiteConnect(api_key=api_key)
    print(f"\nOpen this URL in your browser:\n{kite.login_url()}\n")
    request_token = input("Paste the request_token from the redirect URL: ")

    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data['access_token']

    creds = {
        'api_key': api_key,
        'api_secret': api_secret,
        'access_token': access_token,
    }
    with open('kite_credentials.json', 'w') as f:
        json.dump(creds, f, indent=2)

    print(f"\n✅ Token saved! Access token: {access_token[:20]}...")
    return access_token


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == 'login':
        manual_login()
    else:
        df = fetch_3m_data()
        if df is not None:
            print(f"\nFetched {len(df)} candles")
            print(f"Range: {df.index[0]} to {df.index[-1]}")
            print(f"\nLatest 5 candles:")
            print(df.tail())
