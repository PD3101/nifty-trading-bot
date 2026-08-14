"""
Configuration file — NIFTY Options Buying Strategy

Aligned with the user's actual strategy (Aug 2026):
  - Chart: NIFTY FUT, 3-minute
  - Indicators: VWAP + VWMA-20 + Supertrend (all on FUT 3m chart)
  - No 15-minute HTF bias — all rules on the 3-minute chart
  - Entry: pullback to VWMA-20, bounce/rejection
  - Exit: Supertrend level stoploss, 1:2 RR target
  - Risk: max 2-3 trades/day, max 1-2 losses/day then stop
"""

import os

# ============================================================================
# TELEGRAM
# ============================================================================

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# ============================================================================
# MARKET
# ============================================================================

FUTURES_SYMBOL = "^NSEI"   # NIFTY 50 Index (proxy for futures)
SPOT_SYMBOL = "^NSEI"      # NIFTY Spot

EXECUTION_TIMEFRAME = "3m"  # All rules run on 3-minute chart
HIGHER_TIMEFRAME = None     # No 15m HTF bias in this strategy

MARKET_OPEN = "09:15"       # NSE opens
MARKET_CLOSE = "15:30"      # NSE closes
TRADING_START = "09:45"     # No trades before this
LUNCH_START = "12:30"       # Lunch hour — low momentum
LUNCH_END = "14:00"         # Resume trading after lunch

# ============================================================================
# INDICATORS
# ============================================================================

VWAP_SESSION = "daily"
VWMA_LENGTH = 20
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# ============================================================================
# STRIKE SELECTION
# ============================================================================

STRIKE_INTERVAL = 50          # NIFTY strike interval (50 pts)
ITM_STRIKES = 1               # Default: 1 strike ITM (50 pts for NIFTY)
ITM_POINTS = STRIKE_INTERVAL * ITM_STRIKES  # 50 pts ITM

# ATM only on high-conviction setups with strong OI support
# (OI data not yet available — defaults to ITM only)
ALLOW_ATM_HIGH_CONVICTION = False

# ============================================================================
# ENTRY RULES
# ============================================================================

# Pullback trigger: price must have pulled back to VWMA-20 recently
# before entering. Tolerance: how close the candle low/high must come
# to VWMA-20 to count as a "pullback" (0.15% ≈ 37 pts on NIFTY ~24500).
PULLBACK_TOLERANCE = 0.0015   # 0.15% of VWMA-20
PULLBACK_LOOKBACK = 3         # Check last 3 candles for pullback

# No-chase: don't enter after N consecutive candles in the same direction
NO_CHASE_CANDLES = 4          # Skip if last 4+ candles all same direction

# No new entries after this IST time. Late-day setups (especially after
# lunch) are often fake breakouts that don't leave enough time for the
# 1:2 target to work. Configurable — set to "" to disable.
NO_ENTRY_AFTER = "14:30"      # IST — no new entries in the last hour

# ============================================================================
# EXIT RULES
# ============================================================================

# Stoploss: Supertrend LEVEL (price value) of the entry candle
# (not a direction flip — the actual Supertrend line value)

# Target: 1:2 Risk-Reward ratio
RR_RATIO = 2.0                # Risk-Reward multiplier

# Hybrid exit (Notes section):
# Book 50% at 1:1, trail remaining 50% for 1:2+
HYBRID_EXIT_ENABLED = True
PARTIAL_BOOK_PERCENT = 50     # Book this % at 1:1

# ============================================================================
# RISK MANAGEMENT
# ============================================================================

MAX_POSITIONS = 1
CAPITAL_PER_TRADE = 50000     # INR per trade
POSITION_SIZE_LOTS = 1        # 1 lot
# ⚠️ VERIFY vs NSE circular: NIFTY 50 futures lot size was 50, revised to 75
# for contracts introduced from Nov 2024. As of 2026 it is 75. If trading an
# older/expired series, confirm on the NSE contract note.
LOT_SIZE = 75                 # NSE NIFTY 50 futures/options lot size (post-Nov-2024 = 75)

# Hardening: refuse entries whose notional (LTP × lot) exceeds capital budget.
CAPITAL_GUARD_ENABLED = True
# After 1:1 partial booked, trail remaining 50% with a break-even stop (protect profit).
BREAKEVEN_TRAIL_ENABLED = True

MAX_TRADES_PER_DAY = 3        # Rule 12: max 2-3 trades/day
MAX_LOSSES_PER_DAY = 2        # Rule 13: max 1-2 losses → STOP

# ============================================================================
# GAP DETECTION
# ============================================================================

# Gap-up/gap-down: if today's open differs from yesterday's close by
# more than this %, the pullback trigger naturally adds patience.
# (No separate logic needed — the pullback filter handles it.)
GAP_THRESHOLD = 0.005         # 0.5% — informational only

# ============================================================================
# BACKTESTING
# ============================================================================

BACKTEST_START_DATE = "2026-08-01"
BACKTEST_END_DATE = "2026-08-08"
# ⚠️ VERIFY vs NSE 2026 expiry calendar. NIFTY 50 WEEKLY options expire on
# THURSDAY (weekday 3), NOT Tuesday. A Tuesday value resolves the wrong weekly
# contract in the alert symbol. 0=Mon … 6=Sun.
EXPIRY_DAY = 3                # Thursday — NSE NIFTY 50 weekly options expiry

# Real option-data backtest (requires Kite historical API + credentials).
# When True and not --mock, the backtester prices trades from actual option
# historical premiums instead of the Black-Scholes proxy. Falls back to BS if
# a premium is missing for a timestamp.
REAL_OPTION_DATA = False

# ============================================================================
# OPTION PRICING (Black-Scholes — replaces toy intrinsic+0.3*intrinsic model)
# ============================================================================

BS_RISK_FREE_RATE = 0.06       # risk-free (INR, approx)
DAYS_TO_EXPIRY = 7             # weeks-to-expiry for T (weekly option)
IV_METHOD = "realized"         # "realized" = rolling stdev of FUT returns; "fixed" = IV_FIXED
IV_FIXED = 0.18                # used if IV_METHOD == "fixed"
IV_FLOOR = 0.08                # clamp estimated IV (avoid nonsense)
IV_CAP = 0.60                  # clamp estimated IV
IV_WINDOW = 30                 # bars for rolling realized-vol estimate
MIN_PREMIUM = 5.0              # liquidity proxy: skip if entry premium < ₹5 (deep OTM / illiquid)

# ============================================================================
# TRANSACTION COSTS (India F&O, per lot, per order) — approximations
#   STT on options is charged on the SELL side only.
# ============================================================================

BROKERAGE_PER_ORDER = 20.0     # flat ₹/order (discount broker); entry + exit
STT_PCT = 0.000625             # STT on OPTIONS SELL = 0.0625% of premium notional
EXCHANGE_CHARGE_PCT = 0.0005   # NSE + SEBI + regulatory, ~% of premium notional/side
STAMP_PCT = 0.00003            # stamp duty ~% of premium notional/side
GST_PCT = 0.18                 # GST on (brokerage + exchange)
SLIPPAGE_PCT = 0.001           # slippage % of premium notional per side

# ============================================================================
# ROBUSTNESS / OVERFITTING
# ============================================================================

WALK_FORWARD_FOLDS = 5         # rolling out-of-sample folds for the date range
PARAM_SWEEP = True             # run a small parameter-sensitivity grid
PARAM_SWEEP_MULT = [2.0, 3.0, 4.0]   # Supertrend multiplier grid
PARAM_SWEEP_VWMA = [10, 20, 30]       # VWMA length grid
MONTE_CARLO_RUNS = 2000        # bootstrap resamples for P&L distribution

# ============================================================================
# REGIME / LIQUIDITY FILTERS (gated — off by default)
# ============================================================================

REGIME_FILTER_ENABLED = False  # skip entries when realized vol > REGIME_VOL_ZSCORE σ
REGIME_VOL_ZSCORE = 2.0
LIQUIDITY_FILTER_ENABLED = True  # skip entries with premium < MIN_PREMIUM

# ============================================================================
# COMPLIANCE (SEBI Research Analyst view)
# ============================================================================

DISCLAIMER = ("⚠️ Algorithmic/educational signals only — NOT investment advice. "
              "Options are high-risk; you can lose your full premium. Past performance ≠ future results.")
BRIEF_PREDICTION_LABEL = "SENTIMENT GAUGE"   # was "trend prediction"
GIFT_NIFTY_APPROX_NOTE = "GIFT NIFTY is approximated (no live ticker) — sentiment only."

# ============================================================================
# SYSTEM RULES (NON-NEGOTIABLE)
# ============================================================================

# Only closed candles evaluated (non-repainting)
# No future data, no lookahead
# Only 1 position at a time
STRICT_MODE = True
