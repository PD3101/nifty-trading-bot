"""
Configuration file for NIFTY Options Backtesting System
All strategy parameters are defined here
"""

import os

# ============================================================================
# TELEGRAM CONFIGURATION
# ============================================================================

# Telegram credentials are read from ENVIRONMENT VARIABLES (never commit to git).
# Set locally for testing, and on Railway as env vars for deployment.
#   export TELEGRAM_BOT_TOKEN="..."
#   export TELEGRAM_CHAT_ID="..."
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')

# ============================================================================
# MARKET CONFIGURATION
# ============================================================================

# Instruments
FUTURES_SYMBOL = "^NSEI"  # NIFTY 50 Index (will be used as proxy for futures)
SPOT_SYMBOL = "^NSEI"     # NIFTY Spot

# Timeframes
HIGHER_TIMEFRAME = "15m"   # 15 Minutes
EXECUTION_TIMEFRAME = "3m" # 3 Minutes

# ============================================================================
# INDICATOR PARAMETERS
# ============================================================================

# VWAP
VWAP_SESSION = "daily"  # Standard session VWAP

# VWMA (also referred to as VAMA in the strategy)
VWMA_LENGTH = 20

# Supertrend
SUPERTREND_PERIOD = 10      # Default TradingView setting
SUPERTREND_MULTIPLIER = 3.0 # Default TradingView setting

# ============================================================================
# OPTION STRIKE SELECTION
# ============================================================================

# Strike Selection Rules
ITM_RANGE_MIN = 20  # Minimum points ITM
ITM_RANGE_MAX = 50  # Maximum points ITM

# Preferred Delta Range
DELTA_MIN = 0.55
DELTA_MAX = 0.70

# NIFTY Options Strike Interval
STRIKE_INTERVAL = 50  # NIFTY options are available in 50 point intervals

# ============================================================================
# ENTRY RULES
# ============================================================================

# BUY CALL Entry Conditions (all must be true):
# 1. Higher Timeframe (15m) is Bullish
# 2. Price is above VWAP
# 3. Price is above VWMA(20)
# 4. Supertrend is Green
# 5. 3-minute candle CLOSES above all three indicators

# BUY PUT Entry Conditions (all must be true):
# 1. Higher Timeframe (15m) is Bearish
# 2. Price is below VWAP
# 3. Price is below VWMA(20)
# 4. Supertrend is Red
# 5. 3-minute candle CLOSES below all three indicators

# ============================================================================
# EXIT RULES
# ============================================================================

# Stop Loss Triggers (exit if any occurs):
STOP_LOSS_TRIGGERS = [
    "supertrend_flip",           # Supertrend flips color
    "price_cross_vwap",          # Price closes back across VWAP
    "swing_violation"            # Recent swing high/low violated
]

# Target Rules
PARTIAL_TARGET_PERCENT = 50  # Book 50% at first target (support/resistance)
TRAIL_REMAINING = True       # Trail remaining position

# Trailing Method (choose one)
TRAIL_METHOD = "supertrend"  # Options: "supertrend", "swing_high", "swing_low"

# ============================================================================
# RISK MANAGEMENT
# ============================================================================

# Capital Allocation
CAPITAL_PER_TRADE = 50000    # Amount to risk per trade (INR)

# Position Sizing
MAX_POSITIONS = 1            # Maximum concurrent positions
POSITION_SIZE_LOTS = 1       # Number of lots per trade (1 lot = 50 shares for NIFTY)

# ============================================================================
# BACKTESTING PARAMETERS
# ============================================================================

# Historical Data Period
# Note: Yahoo Finance limits 1-minute data to last 8 days
BACKTEST_START_DATE = "2026-08-01"  # Start date for backtesting (last 7 days)
BACKTEST_END_DATE = "2026-08-08"    # End date for backtesting

# Trading Hours (IST)
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"

# Option Expiry
EXPIRY_DAY = 4  # Thursday (0=Monday, 4=Thursday)

# ============================================================================
# SIGNAL QUALITY
# ============================================================================

# Confidence Scoring Weights (for future use)
CONFIDENCE_WEIGHTS = {
    "htf_alignment": 0.3,
    "ltf_alignment": 0.3,
    "candle_strength": 0.2,
    "volume_confirmation": 0.2
}

# ============================================================================
# OUTPUT CONFIGURATION
# ============================================================================

# Signal Display Format
SHOW_CONFIDENCE = True
SHOW_SPOT_PRICE = True
SHOW_RECOMMENDED_STRIKE = True
SHOW_HTF_BIAS = True
SHOW_REASON = True

# Alert Configuration
ENABLE_ALERTS = True
ALERT_FORMAT = "json"  # Options: "json", "text"

# ============================================================================
# EXTENSIBILITY PLACEHOLDERS
# ============================================================================

# Future Feature Flags (not yet implemented)
ENABLE_VOLUME_FILTER = False
ENABLE_ATR_FILTER = False
ENABLE_MOMENTUM_FILTER = False
ENABLE_MARKET_STRUCTURE = False
ENABLE_LIQUIDITY_FILTER = False
ENABLE_OPEN_INTEREST = False
ENABLE_OPTION_CHAIN = False
ENABLE_AI_SCORING = False
ENABLE_BROKER_API = False
ENABLE_AUTO_TRADING = False
ENABLE_TRADE_JOURNAL = False

# Volume Filter (when enabled)
VOLUME_FILTER_MULTIPLIER = 1.5  # Minimum volume vs average

# ATR Filter (when enabled)
ATR_PERIOD = 14
ATR_THRESHOLD = 1.0

# ============================================================================
# SYSTEM RULES (NON-NEGOTIABLE)
# ============================================================================

# Never repaint
# Never use future candles
# Never use lookahead
# Never generate signals before candle close
# Only closed candles should be evaluated
# Generate deterministic signals

STRICT_MODE = True  # Enforce all system rules
