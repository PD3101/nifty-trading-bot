# NIFTY 50 Options Buying Bot — Complete Project Documentation

> Single source of truth for the entire project: strategy, architecture, code,
> configuration, data flows, the Kite real-data limitation + fix, the RA-grade
> analysis findings, CI/CD workflows, secrets, compliance, and how to run it.
>
> Repo: `PD3101/nifty-trading-bot` · Language: Python 3.11 · Data: Zerodha Kite Connect
> · Deploy: GitHub Actions (alert-only, no order placement)

---

## 1. What this project is

An **alert-only** NIFTY 50 options **buying** bot (long CALLs / long PUTs) for the
Indian F&O segment. It runs entirely on GitHub Actions, reads live market data
from Zerodha Kite Connect, evaluates a systematic price-action strategy, and sends
**Telegram alerts** when an entry/exit condition is met. It **never places orders**
— the human executes manually.

| Attribute | Value |
|---|---|
| Asset | NIFTY 50 index options (weekly, Tuesday expiry) |
| Side | Buy CALL / Buy PUT only |
| Mode | Alert-only (no order placement) |
| Data source | Zerodha Kite Connect (futures 3m, spot, 15m; option LTP) |
| Deploy | GitHub Actions, self-chaining 5-minute scans in IST market hours |
| Notifications | Telegram |
| Strategy style | Pullback-to-VWMA-20 bounce, with 15m trend bias |

---

## 2. Trading strategy (the user's confirmed architecture)

The user's strategy is intentionally **simple** and uses a **two-chart** design:

### 2.1 The three timeframes
| Chart | Instrument | Interval | Role |
|---|---|---|---|
| **Spot** | NIFTY 50 index | 3m | Strike selection + entry timing + "moment of market" |
| **Futures** | NIFTY current-month futures | 3m | Entry triggers: VWAP + VWMA-20 + Supertrend |
| **Futures (HTF)** | NIFTY current-month futures | 15m | Trend **bias only** (Supertrend direction) |

- **SL reference = Supertrend LEVEL on the 3m FUTURES chart** (price value, not a direction flip).
- **Strike selection uses the SPOT index** (per `config.SPOT_FOR_STRIKE = True`), not the futures close.
- **15m HTF** is a *gate*, not a trigger: only take trades **with** the 15m Supertrend direction.

### 2.2 Entry conditions
**CALL** (mirror for PUT):
1. Close **above** VWAP, VWMA-20, and Supertrend level.
2. Supertrend direction = bullish (green).
3. **Pullback**: in the last `PULLBACK_LOOKBACK` (3) candles, price touched VWMA-20 (within `PULLBACK_TOLERANCE` = 0.15%).
4. **Bounce**: current candle closes above all three indicators.
5. **No-chase**: skip if the last `NO_CHASE_CANDLES` (4) candles all closed the same direction.
6. **HTF gate**: 15m Supertrend direction must be bullish (for CALL).

### 2.3 Exit
- **Stoploss**: futures close crosses the Supertrend **level** of the entry candle (price-based, not premium-based).
- **Target**: `1:1` to `1:1.5` maximum (`config.RR_RATIO = 1.5`).
- **Hybrid exit** (`HYBRID_EXIT_ENABLED`): book **50%** at 1:1, trail the remaining 50% for the 1:1.5 target.
- **Break-even trail** (`BREAKEVEN_TRAIL_ENABLED`): after 1:1 is booked, exit at entry cost if price slips back (protects profit).

### 2.4 Strike selection
- `config.STRIKE_SELECTION = "delta"` → pick the strike whose Black-Scholes delta
  ≈ `TARGET_DELTA = 0.55` (≈ ATM, maximum gamma). `DELTA_LOOK = 4` strikes either
  side of spot are scanned. This replaces the old fixed "1 strike ITM" offset.

### 2.5 Risk / schedule guards
| Guard | Setting |
|---|---|
| No trades before | 09:45 IST (`TRADING_START`) |
| Lunch skip | 12:30–14:00 IST |
| Hard no-new-entry | after 14:30 IST (`NO_ENTRY_AFTER`) |
| Max trades/day | 3 (`MAX_TRADES_PER_DAY`) |
| Max losses/day → stop | 2 (`MAX_LOSSES_PER_DAY`) |
| Max positions | 1 (`MAX_POSITIONS`) |
| Capital per trade | ₹50,000 (`CAPITAL_PER_TRADE`) |
| Lot size | 65 units (`LOT_SIZE`, user-confirmed) |
| Weekly expiry | Tuesday (`EXPIRY_DAY = 1`, user-confirmed) |
| Daily loss cap | ₹25,000 (`DAILY_LOSS_CAP_INR`) |
| Capital guard | on (`CAPITAL_GUARD_ENABLED`) — blocks if notional > budget |

---

## 3. Repository structure

```
nifty-trading-bot/
├── config.py                  # ALL strategy/risk params (single source of truth)
├── indicators.py              # VWAP, VWMA-20, Supertrend
├── option_pricer.py           # Black-Scholes price/delta/IV + F&O cost model
├── strategy.py                # StrategyEngine (entry/exit/strike/HTF logic)
├── kite_fetcher.py            # Kite client, token refresh, data + option resolution
├── backtester.py              # BS-priced backtest engine + RA metrics
├── strategy_optimizer.py      # Adversarial optimization harness (§12–§21)
├── premium_store.py           # FORWARD real-premium logger (new)
├── github_actions_runner.py   # Live one-shot runner (state, alerts, logging)
├── telegram_notifier.py      # Telegram send wrapper
├── market_timing.py           # IST clock, trading hours, holidays
├── fetch_tradebook.py         # Pull executed trades from Kite console → trade book
├── fetch_today_trades.py      # Today's trades fetch
├── chain_next_run.py          # Self-chain next 5-min GH Actions scan
├── .github/workflows/
│   ├── trade_bot.yml          # Live 5-min scanner
│   ├── strategy_optimize.yml  # Weekly adversarial optimizer
│   └── market_briefing.yml    # Pre-market briefing
└── PROJECT_DOCUMENTATION.md   # This file
```

### 3.1 `config.py` — verified parameter reference
Values below are **user-confirmed** unless noted; do not "correct" them from
generic NSE knowledge — the user explicitly overrode NSE general assumptions.

| Parameter | Value | Note |
|---|---|---|
| `LOT_SIZE` | **65** | 1 lot = 65 units (user-confirmed; NOT 75) |
| `EXPIRY_DAY` | **1 (Tuesday)** | weekly expiry (user-confirmed; NOT Thursday) |
| `HIGHER_TIMEFRAME` | `"15m"` | HTF bias timeframe |
| `HTF_TREND_ENABLED` | `True` | gate entries to 15m trend |
| `HTF_TIMEFRAME` / `HTF_USE` | `"15m"` / `"FUT"` | |
| `SPOT_FOR_STRIKE` | `True` | strike selection uses NIFTY spot index |
| `RR_RATIO` | `1.5` | target capped at 1:1.5 |
| `STRIKE_SELECTION` | `"delta"` | delta/gamma-aware strike |
| `TARGET_DELTA` | `0.55` | CALL delta target (≈ATM) |
| `DELTA_LOOK` | `4` | strikes scanned either side of spot |
| `VWMA_LENGTH` | `20` | |
| `SUPERTREND_PERIOD` | `10` | |
| `SUPERTREND_MULTIPLIER` | `3.0` | |
| `PULLBACK_TOLERANCE` | `0.0015` | 0.15% of VWMA-20 |
| `PULLBACK_LOOKBACK` | `3` | |
| `NO_CHASE_CANDLES` | `4` | |
| `HYBRID_EXIT_ENABLED` | `True` | book 50% at 1:1 |
| `PARTIAL_BOOK_PERCENT` | `50` | |
| `MAX_POSITIONS` | `1` | |
| `CAPITAL_PER_TRADE` | `50000` | ₹ |
| `POSITION_SIZE_LOTS` | `1` | |
| `CAPITAL_GUARD_ENABLED` | `True` | |
| `BREAKEVEN_TRAIL_ENABLED` | `True` | |
| `DAILY_LOSS_CAP_INR` | `25000` | |
| `MAX_TRADES_PER_DAY` | `3` | |
| `MAX_LOSSES_PER_DAY` | `2` | |
| `REAL_OPTION_DATA` | `False` | BS fallback (forward store used instead) |
| `REGIME_FILTER_ENABLED` | `False` | gated/off by default |
| `REGIME_VOL_ZSCORE` | `2.0` | |
| `LIQUIDITY_FILTER_ENABLED` | `True` | skip premium < `MIN_PREMIUM` |
| `MIN_PREMIUM` | `5.0` | ₹ liquidity floor |
| `BS_RISK_FREE_RATE` | `0.06` | |
| `DAYS_TO_EXPIRY` | `7` | weeks-to-expiry for T |
| `IV_METHOD` | `"realized"` | rolling stdev of FUT returns |
| `IV_FLOOR` / `IV_CAP` | `0.08` / `0.60` | IV clamp |
| `IV_WINDOW` | `30` | bars for realized-vol estimate |
| `BROKERAGE_PER_ORDER` | `20.0` | ₹ flat |
| `STT_PCT` | `0.000625` | STT on options SELL |
| `EXCHANGE_CHARGE_PCT` | `0.0005` | |
| `STAMP_PCT` | `0.00003` | |
| `GST_PCT` | `0.18` | on (brokerage+exchange) |
| `SLIPPAGE_PCT` | `0.001` | per side |
| `MARKET_OPEN` / `MARKET_CLOSE` | `09:15` / `15:30` | |
| `TRADING_START` | `09:45` | |
| `LUNCH_START` / `LUNCH_END` | `12:30` / `14:00` | |
| `NO_ENTRY_AFTER` | `14:30` | IST |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | env | secrets |
| `DISCLAIMER` | str | appended to every alert |
| `BACKTEST_START_DATE` / `END_DATE` | `2026-08-01` / `2026-08-08` | |

---

## 4. How the code works

### 4.1 Live run (`github_actions_runner.py`)
1. Resolve IST time via `MarketTimingManager`.
2. Load/reset daily `bot_state.json` (counters, open position, daily P&L).
3. **Forward premium capture**: `maybe_log_premiums()` → every market-hours run
   logs a ±10-strike LTP band of the live expiry to `premiums.csv`.
4. Fetch 3m futures; compute indicators; resolve `spot` (NIFTY index or futures proxy).
5. Fetch 15m futures → `htf_trend_direction()` (Supertrend direction, closed bars only).
6. **Open position?** → evaluate exit (SL / 1:1 partial / 1:1.5 target / EOD force-close).
7. **Flat?** → `strategy.generate_signal()` → if signal, resolve option token, fetch
   real LTP (`live_option_premium`), apply capital guard + break-even trail, send
   Telegram **ENTRY** alert.
8. Persist state; `chain_next_run.py` schedules the next 5-minute scan.

### 4.2 Strategy engine (`strategy.py`)
- `check_pullback()` — recent candle touched VWMA-20.
- `check_no_chase()` — rejects 4+ consecutive same-direction candles.
- `check_call_entry()` / `check_put_entry()` — full indicator + pullback + no-chase.
- `htf_trend_direction(df_15m, t)` — 15m Supertrend direction via `asof()` on **closed**
  bars only (no look-ahead).
- `select_option_strike()` / `_select_strike_by_delta()` — delta-targeted strike.
- `generate_signal(row_3m, df_3m, idx, spot_price, htf_dir)` — returns signal dict
  (type, strike, Supertrend level for SL) with HTF gate applied.

### 4.3 Pricing (`option_pricer.py`)
- `bs_price`, `bs_delta`, `estimate_iv`, `price_option` — Black-Scholes, delta/theta aware.
- `option_costs` — full India F&O cost model (brokerage, STT-on-sell, exchange, stamp, GST, slippage).

### 4.4 Backtester (`backtester.py`)
- BS-priced trades + cost model → expectancy, profit factor, max drawdown, equity curve, **Monte Carlo** bootstrap, **walk-forward** OOS folds, **parameter-sensitivity** grid.
- `--mock` (synthetic GBM) validates harness logic only; `--real-options` prices from real Kite option history (BS fallback).
- `--check-connectivity` reports Kite auth, contract resolution, and the **option-historical-API subscription status**.

### 4.5 Optimization harness (`strategy_optimizer.py`)
Adversarial, SEBI-RA-grade. Sections implemented:
- **§5** Regime NO-TRADE filter · **§7** SL methods (supertrend / ATR / swing) ·
  **§8** Target-R multiples (1.0…3.0) · **§12** Ablation of {Supertrend, VWAP, VWMA} ·
  **§14** Out-of-sample (train/valid/test) · **§18** Losing-trade forensics ·
  **§21** CURRENT vs V2 final table.
- CLI: `--mock`, `--real-options`, `--csv`, `--opt-csv`, `--auto`, `--export-csv`,
  `--export-start/end/band`, `--notify`, `--htf-off`, `--store <path>`.

### 4.6 Forward real-premium logger (`premium_store.py`) — *the key fix*
- `log_live_premiums(kite, center_strike, …)` — batched NFO token resolve + `kite.quote`,
  append to `premiums.csv` (deduped on timestamp+expiry+strike+type).
- `build_store_lookup(path)` — returns a `(strike, opt_type, ts) → premium|None` callable,
  the **same interface** the optimizer expects; unknown strike → `None` → BS fallback.
- `store_summary()` — human-readable coverage stats.

---

## 5. Data flow

```
                 ┌──────────────────────── GitHub Actions ───────────────────────┐
                 │                                                                │
   Kite Connect  │   trade_bot.yml (every 5 min, IST hours)                      │
   (futures 3m,  │      │                                                         │
    spot, 15m,   │      ▼                                                         │
    option LTP) ─┼──▶ github_actions_runner.py                                    │
                 │      ├─ maybe_log_premiums() ──▶ premiums.csv (cache+artifact) │
                 │      ├─ strategy.generate_signal()                             │
                 │      └─ Telegram ENTRY/EXIT alert                              │
                 │                                                                │
                 │   strategy_optimize.yml (weekly + on-demand)                  │
                 │      ├─ export_csv() ──▶ fut.csv, opt.csv(live expiry), fut15 │
                 │      ├─ --store premiums.csv (forward real history)            │
                 │      └─ §12–§21 harness ──▶ Telegram analysis                 │
                 └────────────────────────────────────────────────────────────────┘
```

State (`bot_state.json`) and the premium store (`premiums.csv`) persist across runs
via GitHub Actions **cache** (and store also as a 90-day **artifact** for download).

---

## 6. Real option data — the Kite limitation & how it was solved

### 6.1 What was wrong
- `opt.csv` was **always empty** in backtests → all premiums were Black-Scholes
  estimates → win rates were *not tradeable*.
- Root cause #1 (code bug, **fixed**): `format_weekly_symbol` omitted the 2-digit
  year, so no NFO instrument matched. Resolution is now **format-agnostic**
  (expiry + strike + instrument_type) in both `resolve_weekly_option` and `export_csv`.
- Root cause #2 (**Kite platform constraint**): `kite.historical_data` returns
  **0 rows for EXPIRED weekly options**. Only the **live/next expiry** has retrievable
  premium history. A multi-week *real-option* backtest of past expiries is therefore
  **impossible to pull on demand**, even with the Historical-Data add-on subscribed.
- Verified: the subscription **IS active** — `check_option_historical_access()`
  resolves a live option and fetches real history (e.g. 2026-08-18 expiry → 23,220 rows;
  2026-08-11 expired → 0 rows).

### 6.2 The solution: forward premium logger
Instead of pulling dead history, the bot **captures live LTPs as they happen** on
every 5-minute run and accumulates them in `premiums.csv`. This:
- matches the "fully automated, no manual export" requirement,
- sidesteps Kite's expired-data gap entirely,
- over coming weeks becomes a genuine, growing **real-option** history that future
  backtests read directly via `--store premiums.csv`.

`export_csv` also now always includes the **live expiry** so recent windows pull
real premiums immediately.

---

## 7. RA analysis findings (real FUT data, wider window)

Runs over **2026-07-14 → 2026-08-14** (real futures prices; BS premiums where
`opt.csv` empty). HTF on/off comparison:

| Metric | CURRENT (HTF **on**) | CURRENT (HTF **off**) |
|---|---|---|
| Trades (n) | 32 | 36 |
| Win % | 40.6% | 41.7% |
| Profit Factor | 1.46 | 1.72 |
| Expectancy/trade | ₹328 | ₹481 |
| Max drawdown | −₹5,707 | −₹5,445 |
| Worst loss streak | 4 | 6 |

**Key findings**
- The 15m HTF trend gate did **not** lift win rate on this window (40.6% → 41.7% *without*
  it). Its only consistent benefit was cutting the worst consecutive-loss streak (6→4) —
  a *risk-smoothing* win, not a win-rate win.
- Highest-leverage levers for **win rate** (from §7–§12): **target R ≈ 1.25** (→50% win
  vs 45.5% at R=1.5), **swing SL** (PF 2.02 vs 1.69 for Supertrend SL), **regime filter on**
  (45.5%→47.4%).
- Expectancy is **net-positive** (PF > 1) on real underlying data — the strategy is
  viable; premiums are the main remaining uncertainty.
- **Caveat**: samples are small (n = 32–36); the 4-week `opt.csv` was empty (BS premiums),
  so these are *directional*, not decisive. A real verdict requires the accumulated
  forward store (matures over weeks).

---

## 8. GitHub Actions workflows

### 8.1 `trade_bot.yml` — live scanner
- Triggered every 5 min via `chain_next_run.py` (schedule cron is a fallback bootstrap).
- Restores/saves `bot_state.json` + `kite_credentials.json` + **`premiums.csv`** (cache).
- Dispatched inputs: `scan_today`, `fetch_trades`, `fetch_tradebook`, `test`.
- Injects all Kite + Telegram secrets (including `KITE_ACCESS_TOKEN`).

### 8.2 `strategy_optimize.yml` — adversarial optimizer
- Scheduled **Sunday 23:30 IST** + `workflow_dispatch` (inputs `start`, `end`, `htf_off`).
- Runs `python strategy_optimizer.py --auto --notify --store premiums.csv`.
- Restores/saves `kite_credentials.json` + `premiums.csv`.

### 8.3 `market_briefing.yml` — pre-market briefing
- Sends the morning "SENTIMENT GAUGE" briefing (GIFT NIFTY approximated; weights disclosed).

---

## 9. Secrets & credentials

Never committed (`.gitignore` excludes `kite_credentials.json`, `*.env`, `*_token*.txt`).
Supplied as GitHub Actions **secrets** / environment variables:

| Secret | Purpose |
|---|---|
| `KITE_API_KEY` | Kite app key |
| `KITE_API_SECRET` | Kite app secret |
| `KITE_ACCESS_TOKEN` | static fallback token (refreshed & cached at runtime) |
| `KITE_CLIENT_ID` | login user id |
| `KITE_PASSWORD` | login password |
| `KITE_TOTP_SECRET` | TOTP seed for headless auto-login |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Telegram chat/user id |

`kite_fetcher.refresh_token()` performs a **headless browser + TOTP** login when the
token is missing/expired, and caches `kite_credentials.json` (restored across runs so
we don't re-login every 5 minutes).

---

## 10. Compliance (SEBI Research Analyst lens)

- **Personal use** (alerts to self) is fine.
- If alerts are **broadcast to a Telegram group**, it becomes "research/advice" →
  requires **SEBI RA registration**, risk disclosure, a "no guaranteed returns"
  statement, and a past-performance disclaimer.
- Every alert appends `config.DISCLAIMER`.
- The pre-market "trend prediction" is relabelled **`SENTIMENT GAUGE`** (not a forecast).
- GIFT NIFTY is **approximated** (no live ticker) and disclosed as such.
- The bot is explicitly **not investment advice**; options are high-risk (full premium
  can be lost).

---

## 11. How to run

### Locally (needs Kite creds in env for live data)
```bash
python backtester.py --check-connectivity     # Kite auth + contract + option-API status
python backtester.py --mock                    # synthetic BS backtest (logic check)
python strategy_optimizer.py --mock            # synthetic harness (logic check)
python strategy_optimizer.py --auto --store premiums.csv   # real data (GH only, has creds)
python github_actions_runner.py                # one live scan (GH Actions environment)
```

### On GitHub
- **Live alerts**: the `trade_bot.yml` schedule runs automatically during IST market hours.
- **Optimizer**: `gh workflow run nifty-strategy-optimize -f start=YYYY-MM-DD -f end=YYYY-MM-DD`
  (add `-f htf_off=true` to isolate the HTF lift; the workflow adds `--store premiums.csv`).
- **Scan-only**: dispatch `trade_bot` with `scan_today=true`.

---

## 12. Known limitations & future work

1. **Real backtest of past weeks** needs the **forward premium store** to mature
   (accumulates over coming weeks). Until then, older-week premiums fall back to BS.
2. **RR is defined on the underlying, P&L on the premium** — delta < 1 + theta decay
   means an underlying 1:1.5 rarely yields a premium 1:1.5; the BS model approximates this.
3. **Alert-only** — no broker order placement (by design; human executes).
4. **GIFT NIFTY approximated** in the briefing (no real ticker).
5. **Regime filter** is gated off by default (`REGIME_FILTER_ENABLED = False`); enable
   after validating on accumulated real data.
6. **Small-sample statistics** — conclusions so far are directional; revisit once the
   forward store has several weeks of real premiums.

---

## 13. Change log (this session)

| Commit | Change |
|---|---|
| `7dbe970` | Separate NIFTY spot index series for strike selection (`fetch_spot_data`, `backtester._load_spot`, runner `fetch_latest_spot`) |
| `67f7030` | Fix HTF `asof` crash (sort direction series) in backtester + optimizer |
| `6b89ec1` | `--htf-off` flag to isolate HTF lift |
| `9943f31` | Wire `htf_off` dispatch input into optimizer workflow |
| `93b3ead` | `check_option_historical_access()` probe + empty-opt.csv diagnostic |
| `1164585` | Fix option resolution (expiry+strike+type, not symbol); real API confirmed active |
| `f351589` | `export_csv` includes live expiry (real-premium source) |
| `508f077` | `premium_store.py` forward real-premium logger + wiring + workflow cache/artifact |

---

*Generated as the single comprehensive reference for the NIFTY options buying bot.
All strategy parameters reflect the user's confirmed values (LOT_SIZE=65, Tuesday
expiry, 1:1–1:1.5 target, delta strike, 15m HTF bias, spot-based strike selection).*
