# NIFTY Options Trading System

Automated NIFTY options signal generator using Zerodha Kite Connect for real NIFTY futures data. Runs on GitHub Actions, sends alerts via Telegram.

## Strategy Rules

### Chart & Indicators
- **Chart:** NIFTY Current Month FUTURES, 3-minute timeframe (via Kite Connect)
- **Indicators:** VWAP + VWMA-20 + Supertrend (all on FUT 3m chart)
- **Flow:** FUT chart (signal) → SPOT price (strike) → Options chart (execution)

### Entry Rules (3 Minutes)
1. No trade before 9:45 AM IST
2. **CE entry:** Price ABOVE all 3 indicators (VWAP, VWMA-20, Supertrend green)
3. **PE entry:** Price BELOW all 3 indicators (VWAP, VWMA-20, Supertrend red)
4. Price between any indicators = No Trade Zone
5. **Pullback trigger:** Wait for pullback to VWMA-20, enter on bounce/rejection
6. **No chase:** Skip if 4+ consecutive candles already in same direction

### Strike Selection
- Default: 1 strike ITM (50 pts for NIFTY) from SPOT price
- ATM allowed ONLY on high-conviction setups (strong OI support)
- Strict NO to OTM

### Exit Rules
- **Stoploss:** Supertrend LEVEL of entry candle (price value, not direction flip)
- **Target:** 1:2 Risk-Reward ratio
- **Hybrid exit:** Book 50% at 1:1 RR, trail remaining 50% for 1:2+

### Risk Management
- Max 2-3 trades per day
- Max 1-2 losing trades per day → STOP trading
- Lunch hours 12:30–2:00 PM avoided
- NIFTY expiry: **Tuesday** (weekly)

## Architecture

```
┌──────────────┐
│ cron-job.org │──── 08:25 IST ────┐ (external trigger, primary)
└──────────────┘                   │
                                   ▼
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────┐
│  Kite Connect   │────▶│  GitHub Actions       │────▶│  Telegram   │
│  (NIFTY Futures │     │  (every 5 min chain)  │     │  (alerts)   │
│   3m candles)   │     │  Auto-login TOTP      │     └─────────────┘
└─────────────────┘     │  Self-chaining:       │
                        │  each run triggers     │
                        │  the next via API      │
                        └──────────────────────┘
```

### Reliability (3 layers)
1. **cron-job.org** (external, primary) — fires workflow_dispatch at 08:25 IST
2. **GH Actions schedule crons** (backup) — 08:25 + 09:00 + */5 min
3. **Self-chain** — once any run fires, chains every 5 min until 15:30 IST

## Data Source

**Zerodha Kite Connect** — actual NIFTY futures data (not spot index).
- NIFTY26AUGFUT (August 2026 contract)
- 3-minute OHLCV candles
- Auto-selects nearest month contract
- Token refreshes daily via headless browser + TOTP

## Pre-Market Briefing

Sent twice daily via Telegram:
- **08:25 AM IST** — Early brief (international markets, GIFT NIFTY, commodities, news)
- **09:00 AM IST** — Final brief with fresh data

Includes a **Market Trend Prediction** scoring 7 factors:
| Factor | Weight | Direction |
|---|---|---|
| GIFT NIFTY | 30% | Higher = bullish |
| US Futures (S&P + NASDAQ) | 20% | Higher = bullish |
| NIFTY 50 prev close | 15% | Higher = bullish |
| Crude Oil | 10% | Lower = bullish (India import bill) |
| USD/INR | 10% | Lower = bullish (stronger INR) |
| Gold | 5% | Lower = bullish (risk-on) |
| US 10Y yield | 5% | Lower = bullish (risk-on for EMs) |

Output: 🟢 BULLISH / 🔴 BEARISH / 🟡 MIXED with key drivers.

## Files

| File | Purpose |
|---|---|
| `github_actions_runner.py` | Main bot — runs on GitHub Actions, scan mode, entry/exit logic |
| `kite_fetcher.py` | Kite Connect data fetcher + auto-login via TOTP |
| `chain_next_run.py` | Self-chaining — triggers next GH Actions run via API |
| `strategy.py` | Entry/exit logic (3m only, pullback trigger, 1:2 RR) |
| `indicators.py` | VWAP, VWMA-20, Supertrend calculations |
| `config.py` | All strategy parameters |
| `backtester.py` | Backtesting engine (uses Kite data) |
| `dashboard.py` | Streamlit dashboard (loads pre-computed results) |
| `market_briefing.py` | Pre-market brief + trend prediction (GIFT NIFTY + news + markets) |
| `market_timing.py` | Market hours, holidays, lunch break |
| `telegram_notifier.py` | Telegram alert formatting |

## Workflows

| Workflow | Schedule | Purpose |
|---|---|---|
| `nifty-trade-bot` | 08:25 IST + every 5 min | Market scan, entry/exit signals |
| `nifty-market-briefing` | 08:25 + 09:00 IST | Pre-market brief with trend prediction |

## Setup

### Prerequisites
- Zerodha account with Kite Connect API access
- Telegram bot (BotFather)
- Google Authenticator (for TOTP auto-login)
- GitHub account
- cron-job.org account (free, for reliable external trigger)

### Environment Variables (GitHub Secrets)
```
TELEGRAM_BOT_TOKEN    # Telegram bot token
TELEGRAM_CHAT_ID      # Your Telegram chat ID
KITE_API_KEY          # Kite Connect API key
KITE_API_SECRET       # Kite Connect API secret
KITE_ACCESS_TOKEN     # Auto-refreshed daily
KITE_CLIENT_ID        # Zerodha client ID
KITE_PASSWORD         # Zerodha password
KITE_TOTP_SECRET      # Google Authenticator secret
```

### Local Development
```bash
pip install -r requirements.txt
python -m playwright install chromium --with-deps
python kite_fetcher.py login  # One-time token generation
python backtester.py          # Run backtest
streamlit run dashboard.py    # Launch dashboard
```

### On-Demand Scan
Trigger a scan outside market hours via GitHub Actions:
```bash
gh workflow run nifty-trade-bot --ref main -f scan_today=true
```
Fetches real Kite data and reports all strategy signals for the latest trading day.

## Telegram Alerts

| Alert | When |
|---|---|
| 🌅 Pre-market brief | 08:25 + 09:00 AM IST daily |
| 📊 Trend prediction | Included in brief (🟢/🔴/🟡) |
| 🟢 Bot online | 08:25 AM IST daily |
| 🟢/🔴 Entry | Signal triggered (live market) |
| 📊 Partial exit | 1:1 RR hit (book 50%) |
| ✅/❌ Full exit | 1:2 target or stoploss |
| 🛑 Daily stop | Max trades/losses reached |

All P&L shown per lot (65 qty × premium).

## Backtest Results (Kite NIFTY Futures)

10-day backtest (Jul 30 – Aug 7, 2026):
- **9 trades** | **3W / 6L** | **Win Rate 33%**
- **Total P&L: ₹+3,021 per lot**
- **Avg Win: ₹4,408** | **Avg Loss: ₹-1,701**
- **Reward-to-Risk: 2.6:1**

## License

Proprietary. Unauthorized distribution prohibited.
