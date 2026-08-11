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
POSITION_SIZE_LOTS = 1        # 1 lot = 65 qty (NIFTY)
LOT_SIZE = 65

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
EXPIRY_DAY = 1                # Tuesday (NIFTY weekly expiry)

# ============================================================================
# SYSTEM RULES (NON-NEGOTIABLE)
# ============================================================================

# Only closed candles evaluated (non-repainting)
# No future data, no lookahead
# Only 1 position at a time
STRICT_MODE = True
