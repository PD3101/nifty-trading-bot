"""
Pre-market briefing for GitHub Actions (or any host).

At 09:00 IST on trading days, sends a Telegram message with:
  - International markets snapshot (yfinance — investing.com blocks live scraping)
  - Latest news headlines (investing.com RSS feed — works without auth)

Runs via .github/workflows/market_briefing.yml (cron 30 3 * * 1-5 = 09:00 IST).
"""

import sys
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO

import yfinance as yf

from market_timing import MarketTimingManager
from telegram_notifier import TelegramNotifier

# (label, yahoo symbol, emoji)
EQUITIES = [
    ('S&P 500',    '^GSPC',  '🇺🇸'),
    ('Dow Jones',  '^DJI',   '🇺🇸'),
    ('NASDAQ',     '^IXIC',  '🇺🇸'),
    ('Nikkei 225', '^N225',  '🇯🇵'),
    ('Hang Seng',  '^HSI',   '🇭🇰'),
    ('NIFTY 50',   '^NSEI',  '🇮🇳'),
    ('Sensex',     '^BSESN', '🇮🇳'),
]
FUTURES = [
    ('S&P 500 Fut',  'ES=F', '📈'),
    ('NASDAQ Fut',   'NQ=F', '📈'),
]
COMMODITIES = [
    ('Gold',     'GC=F',  '🥇'),
    ('Crude Oil', 'CL=F', '🛢️'),
    ('USD/INR',  'INR=X', '💱'),
    ('US 10Y',   '^TNX',  '🏛️'),
]

# investing.com RSS news feeds (order = priority)
NEWS_FEEDS = [
    'https://www.investing.com/rss/news_25.rss',   # Stock Market News
    'https://www.investing.com/rss/news.rss',      # All News
]


def fetch_quote(symbol, days=5):
    """Return (last_close, change_pct) or (None, None)."""
    df = yf.Ticker(symbol).history(period=f'{days}d', interval='1d', auto_adjust=False)
    if df is None or df.empty:
        return None, None
    last = float(df['Close'].iloc[-1])
    prev = float(df['Close'].iloc[-2]) if len(df) > 1 else None
    chg = (last - prev) / prev * 100 if prev else None
    return last, chg


def fetch_markets(tickers):
    """Return (formatted_lines, raw_data_dict); skip symbols that fail."""
    lines, raw = [], {}
    for label, symbol, emoji in tickers:
        try:
            last, chg = fetch_quote(symbol)
            if last is None:
                continue
            chg_str = f"({chg:+.2f}%)" if chg is not None else "(--)"
            lines.append(f"{emoji} <b>{label}:</b> {last:,.2f} {chg_str}")
            raw[symbol] = (last, chg)
        except Exception:
            continue
    return lines, raw


def fetch_news(limit=6):
    """Pull latest headlines from investing.com RSS feeds."""
    import requests
    seen, headlines = set(), []
    for url in NEWS_FEEDS:
        try:
            resp = requests.get(url, timeout=12, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
            })
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            for item in root.iter('item'):
                title = item.findtext('title')
                if not title:
                    continue
                title = re.sub(r'\s+', ' ', title).strip()
                # Dedupe on exact title OR same story (first 8 words)
                key = title.lower()
                prefix = ' '.join(key.split()[:8])
                if key in seen or prefix in seen:
                    continue
                seen.add(key)
                seen.add(prefix)
                headlines.append(title)
                if len(headlines) >= limit:
                    return headlines
        except Exception:
            continue
    return headlines


def compute_gift_nifty():
    """
    Approximate GIFT NIFTY = NIFTY spot × (1 + S&P 500 futures overnight change).

    GIFT NIFTY (NSE IFSC futures) is the key overnight sentiment driver for
    Indian markets. Unfortunately:
      - Yahoo Finance has no ticker for it
      - NSE IFSC (nseifsc.com) is DNS-unreachable from this network
      - investing.com blocks all scraping (HTTP 403)

    This approximation captures the dominant relationship: US futures move
    overnight is the primary driver of where GIFT NIFTY opens.
    If a reliable API becomes available, replace this function.
    """
    nifty_close, _ = fetch_quote('^NSEI')
    es_chg = fetch_quote('ES=F')[1]   # S&P 500 futures day-over-day %
    if nifty_close is not None and es_chg is not None:
        implied = nifty_close * (1 + es_chg / 100)
        return implied, es_chg
    return None, None


def _score(change, thresholds):
    """Map a change_pct to -2..+2 using (low, high) thresholds."""
    low, high = thresholds
    if change > high:
        return 2
    if change > low:
        return 1
    if change < -high:
        return -2
    if change < -low:
        return -1
    return 0


def compute_trend_prediction(gift_chg, sp_fut, nq_fut, nifty_chg,
                             crude_chg, usdinr_chg, us10y_chg, gold_chg):
    """
    Score each indicator and return (emoji, label, reasoning).
    Scores range -2 (very bearish) to +2 (very bullish).
    """
    parts = []  # (weight, score, reason)

    # GIFT NIFTY — strongest predictor of NIFTY open (30%)
    if gift_chg is not None:
        s = _score(gift_chg, (0.1, 0.3))
        parts.append((0.30, s, f"GIFT NIFTY {gift_chg:+.2f}%"))

    # US futures avg — overnight risk sentiment (20%)
    fut_vals = [x for x in (sp_fut, nq_fut) if x is not None]
    if fut_vals:
        avg = sum(fut_vals) / len(fut_vals)
        s = _score(avg, (0.2, 0.5))
        label = "US futures green" if avg > 0.05 else "US futures red" if avg < -0.05 else "US futures flat"
        parts.append((0.20, s, label))

    # NIFTY 50 prev close (15%)
    if nifty_chg is not None:
        s = _score(nifty_chg, (0.3, 0.6))
        parts.append((0.15, s, None))

    # Crude — lower is better for India import bill (10%)
    if crude_chg is not None:
        s = -_score(crude_chg, (0.5, 1.5))  # inverted: up = bad
        label = "crude soft" if crude_chg < -0.3 else "crude up" if crude_chg > 0.3 else None
        parts.append((0.10, s, label))

    # USD/INR — lower = stronger INR = good for FII flows (10%)
    if usdinr_chg is not None:
        s = -_score(usdinr_chg, (0.05, 0.15))  # inverted: INR up = bad
        parts.append((0.10, s, None))

    # Gold — higher = risk-off = bearish for equities (5%)
    if gold_chg is not None:
        s = -_score(gold_chg, (0.2, 0.6))  # inverted: gold up = bad
        parts.append((0.05, s, None))

    # US 10Y yield — lower = risk-on = good for EMs (5%)
    if us10y_chg is not None:
        s = -_score(us10y_chg, (0.5, 1.5))  # inverted: yield up = bad
        parts.append((0.05, s, None))

    # News crude keyword scan (5%)
    if parts:
        total_w = sum(w for w, _, _ in parts)
        # Renormalize weights to sum to 0.95 (leaving 5% for news if present)
        norm = 0.95 / total_w if total_w > 0 else 1
        parts = [(w * norm, s, r) for w, s, r in parts]

    if not parts:
        return '🟡', 'MIXED', 'Insufficient data'

    total_w = sum(w for w, _, _ in parts)
    weighted = sum(w * s for w, s, _ in parts) / total_w

    if weighted > 0.3:
        emoji, label = '🟢', 'BULLISH'
    elif weighted < -0.3:
        emoji, label = '🔴', 'BEARISH'
    else:
        emoji, label = '🟡', 'MIXED'

    reasoning = ' · '.join(r for _, _, r in parts if r) or 'No strong signals'
    return emoji, label, reasoning


def build_message():
    timing = MarketTimingManager()
    now = timing.get_ist_time()
    today_str = now.strftime('%A, %d %b %Y')

    equities, eq_raw = fetch_markets(EQUITIES)
    futures, fut_raw = fetch_markets(FUTURES)
    commodities, com_raw = fetch_markets(COMMODITIES)
    gift_nifty, gift_nifty_chg = compute_gift_nifty()
    news = fetch_news()

    # Extract raw change pcts for trend prediction
    nifty_chg = eq_raw.get('^NSEI', (None, None))[1]
    sp_fut_chg = fut_raw.get('ES=F', (None, None))[1]
    nq_fut_chg = fut_raw.get('NQ=F', (None, None))[1]
    crude_chg = com_raw.get('CL=F', (None, None))[1]
    usdinr_chg = com_raw.get('INR=X', (None, None))[1]
    us10y_chg = com_raw.get('^TNX', (None, None))[1]
    gold_chg = com_raw.get('GC=F', (None, None))[1]

    pred_emoji, pred_label, pred_reason = compute_trend_prediction(
        gift_nifty_chg, sp_fut_chg, nq_fut_chg, nifty_chg,
        crude_chg, usdinr_chg, us10y_chg, gold_chg,
    )

    parts = [
        "🌅 <b>NIFTY PRE-MARKET BRIEF</b>",
        f"📅 {today_str}\n",
    ]

    # GIFT NIFTY — the most important pre-market indicator for Indian markets
    if gift_nifty is not None:
        parts += [
            "🇮🇳 <b>GIFT NIFTY (implied):</b> "
            f"{gift_nifty:,.2f} <i>(US futures {gift_nifty_chg:+.2f}%)</i>",
            "    <i>— computed from NIFTY close + S&P 500 futures overnight move</i>\n",
        ]

    parts += ["🌍 <b>INTERNATIONAL MARKETS</b>", *equities]

    if futures:
        parts += ["", "📈 <b>FUTURES</b>", *futures]
    if commodities:
        parts += ["", "💰 <b>COMMODITIES / FX</b>", *commodities]

    # Trend prediction
    parts += [
        "",
        f"📊 <b>MARKET TREND PREDICTION</b>",
        f"{pred_emoji} <b>{pred_label}</b> — {pred_reason}",
    ]

    if news:
        parts += ["", "📰 <b>LATEST NEWS</b> <i>(investing.com)</i>",
                  *(f"• {h}" for h in news)]

    parts += [
        "",
        "⏰ Markets open <b>09:15</b> · trading starts <b>09:45</b> IST",
    ]
    return "\n".join(parts)


def main():
    notifier = TelegramNotifier()
    if not notifier.enabled:
        print("Telegram not configured")
        sys.exit(1)

    timing = MarketTimingManager()
    now = timing.get_ist_time()

    # Skip on weekends / NSE holidays (briefing only on trading days)
    if not timing.is_weekday(now) or timing.is_holiday(now):
        print("Not a trading day - skipping briefing")
        return

    msg = build_message()
    ok = notifier.send_message(msg)
    print(f"Briefing sent: {ok}")


if __name__ == '__main__':
    main()
