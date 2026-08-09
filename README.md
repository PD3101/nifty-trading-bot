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
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Kite Connect   │────▶│  GitHub Actions   │────▶│  Telegram   │
│  (NIFTY Futures │     │  (every 5 min)    │     │  (alerts)   │
│   3m candles)   │     │  Auto-login TOTP  │     └─────────────┘
└─────────────────┘     └──────────────────┘
                               │
                        ┌──────▼──────┐
                        │   Streamlit  │
                        │   Dashboard  │
                        │  (backtest)  │
                        └─────────────┘
```

## Data Source

**Zerodha Kite Connect** — actual NIFTY futures data (not spot index).
- NIFTY26AUGFUT (August 2026 contract)
- 3-minute OHLCV candles
- Auto-selects nearest month contract
- Token refreshes daily via headless browser + TOTP

## Files

| File | Purpose |
|---|---|
| `github_actions_runner.py` | Main bot — runs on GitHub Actions every 5 min |
| `kite_fetcher.py` | Kite Connect data fetcher + auto-login |
| `strategy.py` | Entry/exit logic (3m only, pullback trigger, 1:2 RR) |
| `indicators.py` | VWAP, VWMA-20, Supertrend calculations |
| `config.py` | All strategy parameters |
| `backtester.py` | Backtesting engine (uses Kite data) |
| `dashboard.py` | Streamlit dashboard (loads pre-computed results) |
| `market_briefing.py` | Pre-market brief (GIFT NIFTY + news + markets) |
| `market_timing.py` | Market hours, holidays, lunch break |
| `telegram_notifier.py` | Telegram alert formatting |

## Setup

### Prerequisites
- Zerodha account with Kite Connect API access
- Telegram bot (BotFather)
- Google Authenticator (for TOTP auto-login)
- GitHub account

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

## Dashboard

Live at: https://nifty-trading-bot-xxxxx.streamlit.app

Shows backtest results from actual NIFTY futures data (Kite Connect).
Updated with each code push to GitHub.

## Telegram Alerts

| Alert | When |
|---|---|
| 🌅 Pre-market brief | 9:00 AM IST daily |
| 🟢 Bot online | 9:30 AM IST daily |
| 🟢/🔴 Entry | Signal triggered |
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
