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
    """Return formatted lines for a ticker group; skip symbols that fail."""
    lines = []
    for label, symbol, emoji in tickers:
        try:
            last, chg = fetch_quote(symbol)
            if last is None:
                continue
            chg_str = f"({chg:+.2f}%)" if chg is not None else "(--)"
            lines.append(f"{emoji} <b>{label}:</b> {last:,.2f} {chg_str}")
        except Exception:
            continue
    return lines


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


def build_message():
    timing = MarketTimingManager()
    now = timing.get_ist_time()
    today_str = now.strftime('%A, %d %b %Y')

    equities = fetch_markets(EQUITIES)
    futures = fetch_markets(FUTURES)
    commodities = fetch_markets(COMMODITIES)
    news = fetch_news()

    parts = [
        "🌅 <b>NIFTY PRE-MARKET BRIEF</b>",
        f"📅 {today_str}\n",
        "🌍 <b>INTERNATIONAL MARKETS</b>",
        *equities,
    ]

    if futures:
        parts += ["", "📈 <b>FUTURES</b>", *futures]
    if commodities:
        parts += ["", "💰 <b>COMMODITIES / FX</b>", *commodities]
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
