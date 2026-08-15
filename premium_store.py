"""
Forward real-premium logger — accumulates REAL NIFTY option LTPs over time.

WHY THIS EXISTS
---------------
Kite's historical_data API does NOT serve premiums for EXPIRED weekly options
(only the live/next expiry). So a multi-week *real-option* backtest is impossible
to pull on demand. The fix: capture live LTPs on every runner invocation (the bot
already runs every 5 min during market hours) and persist them to a CSV. Over
coming weeks this becomes a genuine, growing real-premium history that future
backtests read directly — no Kite historical API, no manual export.

The runner calls `log_live_premiums(...)` each market-hours run. The optimizer's
`--store premiums.csv` reads the accumulated file as the real-premium source.

CSV schema: timestamp, expiry, strike, type, ltp
  - timestamp : IST datetime of the quote
  - expiry    : option expiry (YYYY-MM-DD)
  - strike    : int strike
  - type      : CALL | PUT
  - ltp       : real last traded price from Kite quote
"""

import os
import logging
from datetime import datetime

import pandas as pd
import pytz

logger = logging.getLogger('premium_store')

IST = 'Asia/Kolkata'
DEFAULT_PATH = os.path.join(os.path.dirname(__file__), 'premiums.csv')
DEFAULT_BAND = 10  # strikes each side of spot (×50 pts = ±500 pts)


# ---------------------------------------------------------------------------
# Token resolution (batched — one NFO instruments call, not one per strike)
# ---------------------------------------------------------------------------
def _resolve_band_tokens(kite, expiry, center_strike, band):
    """Return [(strike, 'CALL'|'PUT', token), ...] for a strike band around
    `center_strike`. Resolves once from the NFO instrument list (format-agnostic
    via expiry + strike + instrument_type)."""
    from kite_fetcher import next_weekly_expiry
    if expiry is None:
        expiry = next_weekly_expiry()
    exp_s = expiry.isoformat() if hasattr(expiry, 'isoformat') else str(expiry)
    lo = int(round(center_strike / 50) * 50) - band * 50
    hi = int(round(center_strike / 50) * 50) + band * 50
    strikes = list(range(lo, hi + 1, 50))

    insts = kite.instruments('NFO')
    tok_map = {}
    for i in insts:
        ie = i.get('expiry')
        ie_s = ie.isoformat() if hasattr(ie, 'isoformat') else str(ie)
        if (i.get('name') == 'NIFTY' and i.get('exchange') == 'NFO'
                and i.get('instrument_type') in ('CE', 'PE')
                and i.get('strike') is not None
                and float(i['strike']) in strikes
                and ie_s == exp_s):
            tok_map[(int(float(i['strike'])), i['instrument_type'])] = i['instrument_token']

    out = []
    for s in strikes:
        for typ, ityp in (('CALL', 'CE'), ('PUT', 'PE')):
            tok = tok_map.get((s, ityp))
            if tok:
                out.append((s, typ, tok))
    return out


def _latest_premium_via_history(kite, token, now_ist):
    """Real last premium from intraday historical data (proven Kite endpoint).

    Used as a fallback when kite.quote returns empty — which it does on
    holidays and has been observed empty on trading days too. Returns float
    or None. Uses naive IST wall-clock so Kite parses the window correctly.
    """
    try:
        frm = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        frm = frm.replace(tzinfo=None)
        to = now_ist.replace(tzinfo=None)
        candles = kite.historical_data(
            instrument_token=token, from_date=frm, to_date=to, interval='minute')
        if not candles:
            return None
        return float(pd.DataFrame(candles)['close'].iloc[-1])
    except Exception as e:
        logger.warning(f"premium_store: historical fallback failed (tok={token}): {e}")
        return None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log_live_premiums(kite, center_strike, expiry=None, band=DEFAULT_BAND,
                      ts=None, path=DEFAULT_PATH):
    """Fetch LTPs for a band of strikes of the live expiry and append to the
    store. Returns the number of rows written (0 on failure / no data).

    Safe to call every run: de-duplicates on (timestamp, expiry, strike, type).
    """
    if center_strike is None or center_strike <= 0:
        return 0
    try:
        tokens = _resolve_band_tokens(kite, expiry, center_strike, band)
        if not tokens:
            logger.warning("premium_store: no option tokens resolved; skipping log")
            return 0
        logger.info(f"premium_store: resolved {len(tokens)} option tokens "
                    f"(center={center_strike}, band={band})")
        exp_s = (expiry.isoformat() if hasattr(expiry, 'isoformat') else str(expiry)
                 if expiry else None)
        if exp_s is None:
            from kite_fetcher import next_weekly_expiry
            exp_s = next_weekly_expiry().isoformat()

        ts = ts or datetime.now(pytz.timezone(IST))
        if ts.tzinfo is None:
            ts = pytz.timezone(IST).localize(ts)

        # Primary: fast bulk LTP quote. Fallback: intraday historical_data
        # (proven to work for the live expiry even when quote returns empty).
        rows = []
        q = {}
        try:
            q = kite.quote([f"NFO:{t}" for _, _, t in tokens])
        except Exception as e:
            logger.warning(f"premium_store: kite.quote error: {e}")
        if q:
            for strike, typ, tok in tokens:
                rec = q.get(f"NFO:{tok}")
                if rec and rec.get('last_price') is not None:
                    rows.append((ts, exp_s, int(strike), typ, float(rec['last_price'])))
        if not rows:
            logger.info(f"premium_store: quote empty/unusable for {len(tokens)} "
                        f"tokens; falling back to historical_data")
            import time
            for strike, typ, tok in tokens:
                p = _latest_premium_via_history(kite, tok, ts)
                if p is not None:
                    rows.append((ts, exp_s, int(strike), typ, p))
                time.sleep(0.05)  # avoid Kite historical rate limits

        if not rows:
            return 0

        df_new = pd.DataFrame(rows, columns=['timestamp', 'expiry', 'strike', 'type', 'ltp'])
        if os.path.exists(path):
            df_old = pd.read_csv(path)
            # dedupe on the 4-key identity
            df_old['timestamp'] = pd.to_datetime(df_old['timestamp']).astype(str)
            df_new['timestamp'] = df_new['timestamp'].astype(str)
            seen = set(map(tuple, df_old[['timestamp', 'expiry', 'strike', 'type']].values))
            df_new = df_new[~df_new[['timestamp', 'expiry', 'strike', 'type']].apply(tuple, axis=1).isin(seen)]
            df = pd.concat([df_old, df_new], ignore_index=True)
        else:
            df = df_new
        df.to_csv(path, index=False)
        logger.info(f"premium_store: +{len(df_new)} rows → {path} (total {len(df)})")
        return len(df_new)
    except Exception as e:
        logger.warning(f"premium_store log failed: {e}")
        return 0


# ---------------------------------------------------------------------------
# Reading (optimizer-facing)
# ---------------------------------------------------------------------------
def build_store_lookup(path=DEFAULT_PATH, expiry=None):
    """Read the accumulated store and return a callable compatible with the
    optimizer's opt_lookup interface: (strike, opt_type, timestamp) -> premium|None.

    If `expiry` is given, only that expiry's rows are used (so a backtest of a
    specific week reads the premiums that were actually live then).
    """
    if not os.path.exists(path):
        logger.warning(f"premium_store: {path} not found; opt_lookup will be None")
        return None
    od = pd.read_csv(path)
    if expiry is not None:
        exp_s = expiry.isoformat() if hasattr(expiry, 'isoformat') else str(expiry)
        od = od[od['expiry'] == exp_s]
    if len(od) == 0:
        return None
    od['timestamp'] = pd.to_datetime(od['timestamp'])
    od['strike'] = od['strike'].astype(int)
    od['type'] = od['type'].astype(str).str.upper()

    lookup = {}
    for (strike, typ), g in od.groupby(['strike', 'type']):
        s = pd.Series(g['ltp'].values, index=pd.DatetimeIndex(g['timestamp'].values))
        s.index = s.index.tz_localize(IST) if s.index.tz is None else s.index.tz_convert(IST)
        lookup[(int(strike), typ)] = s.sort_index()

    def premium(strike, opt, ts):
        s = lookup.get((int(strike), opt.upper()))
        if s is None or len(s) == 0:
            return None
        v = s.sort_index().asof(ts)
        return float(v) if v == v else None
    return premium


def store_summary(path=DEFAULT_PATH):
    """Human-readable summary of the accumulated store (for logging/alerts)."""
    if not os.path.exists(path):
        return "premium_store: empty (no data captured yet)"
    od = pd.read_csv(path)
    n_days = pd.to_datetime(od['timestamp']).dt.date.nunique()
    expiries = sorted(od['expiry'].astype(str).unique().tolist())
    return (f"premium_store: {len(od)} rows, {n_days} trading days, "
            f"{len(expiries)} expiries [{expiries[0]}…{expiries[-1]}]")
