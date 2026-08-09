"""
One-shot trading bot runner for GitHub Actions.

Runs a SINGLE market check (fetch data -> indicators -> strategy -> alerts) then
exits. Designed to be lightweight so each scheduled run finishes well under the
GitHub Actions free-tier minute budget.

State (open position, error throttle) is persisted to a JSON file between runs
via the Actions cache, so signals aren't duplicated and positions survive
between 5-minute runs.

Replaces cloud_bot.py for the GitHub Actions deployment path:
- Non-repainting: only CLOSED 3m/15m candles are evaluated.
- Trades only 09:45-15:30 IST, Mon-Fri, no NSE holidays (market_timing.py).
- One position at a time (config.MAX_POSITIONS = 1).
- Exits: Supertrend flip, VWAP cross, 30% target, or end of day.
"""

import json
import logging
import os
import sys
from datetime import time as dtime, timedelta

import pandas as pd
import yfinance as yf

import config
from indicators import Indicators
from strategy import StrategyEngine
from market_timing import MarketTimingManager
from telegram_notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('gh_runner')

STATE_FILE = os.getenv('STATE_FILE', 'bot_state.json')
IST = 'Asia/Kolkata'
MARKET_CLOSE_TIME = dtime(15, 30)

# Simplified option premium model (mirrors backtester.simulate_option_price)
def simulate_option_price(spot_price, strike, option_type):
    if option_type == 'CALL':
        intrinsic = max(0, spot_price - strike)
    else:
        intrinsic = max(0, strike - spot_price)
    time_value = intrinsic * 0.3 if intrinsic > 0 else spot_price * 0.01
    return intrinsic + time_value


def fetch_resampled(interval, lookback_days=2):
    """Fetch 1m data and resample to '3m' or '15m'. Returns DataFrame or None."""
    try:
        ticker = yf.Ticker("^NSEI")
        df = ticker.history(period=f"{lookback_days}d", interval="1m")
        if df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df[['open', 'high', 'low', 'close', 'volume']]
        # Normalize index timezone to IST
        if df.index.tz is None:
            df.index = df.index.tz_localize(IST)
        else:
            df.index = df.index.tz_convert(IST)
        rule = '3min' if interval == '3m' else '15min'
        resampled = df.resample(rule).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        return resampled
    except Exception as e:
        logger.error(f"Fetch failed ({interval}): {e}")
        return None


def keep_closed(df, period_minutes, now):
    """Keep only candles whose period has fully closed by `now` (non-repainting)."""
    close_at = df.index + pd.Timedelta(minutes=period_minutes)
    return df[close_at <= now]


def load_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
            if not isinstance(state, dict):
                raise ValueError("bad state shape")
            return state
    except Exception:
        return {'date': '2000-01-01', 'open_position': None, 'consecutive_failures': 0}


def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def evaluate_exit(position, row_3m, current_option_price, today, now):
    """Return exit reason string, or None to keep holding."""
    if position.get('date') != today:
        return "End of Day (position from a previous day)"

    if now.time() >= MARKET_CLOSE_TIME:
        return "End of Day (Market Close)"

    st_dir = int(row_3m['3m_supertrend_direction'])
    if st_dir != int(position['entry_supertrend_direction']):
        return "Supertrend Flip"

    close = row_3m['close']
    vwap = row_3m['3m_vwap']
    if position['type'] == 'BUY_CALL' and close < vwap:
        return "Price Crossed Below VWAP"
    if position['type'] == 'BUY_PUT' and close > vwap:
        return "Price Crossed Above VWAP"

    entry_price = position.get('entry_price') or 0
    if entry_price > 0:
        pnl_pct = (current_option_price - entry_price) / entry_price * 100
        if pnl_pct >= 30:
            return "Target Reached (30%)"

    return None


def main():
    timing = MarketTimingManager()
    now = timing.get_ist_time()
    today = now.strftime('%Y-%m-%d')

    # Optional manual test mode (workflow_dispatch)
    if os.getenv('GH_ACTION_TEST', '').lower() in ('1', 'true'):
        notifier = TelegramNotifier()
        if notifier.enabled:
            ok = notifier.send_message(
                "🧪 <b>GitHub Actions test</b>\n\n"
                "✅ Bot code runs on GitHub Actions\n"
                f"🕐 Time: {now.strftime('%Y-%m-%d %H:%M %Z')}\n"
                "🤖 Ready to trade Monday 09:45 AM IST"
            )
            print(f"Test message sent: {ok}")
        else:
            print("Telegram not configured in this run")
        sys.exit(0)

    notifier = TelegramNotifier()
    if not notifier.enabled:
        logger.error("Telegram not configured - TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing")
        sys.exit(1)

    state = load_state()

    # ---- Daily reset + liveness message on trading days ----
    if state.get('date') != today:
        state = {'date': today, 'open_position': None, 'consecutive_failures': 0}
        if timing.is_weekday(now) and not timing.is_holiday(now):
            notifier.send_message(
                f"🟢 <b>Bot Online — {today}</b>\n\n"
                f"🕐 {now.strftime('%I:%M %p %Z')}\n"
                f"📡 Monitoring NIFTY every 5 min (09:45–15:30 IST)\n"
                f"📲 Entry/exit alerts will appear here"
            )
            logger.info("Daily online message sent")

    # ---- Trade only within market hours and after 09:45 IST ----
    if not timing.can_trade_now():
        save_state(state)
        logger.info("Not in trading window - no-op")
        return

    # ---- Fetch data (1m -> resample) ----
    df3 = fetch_resampled('3m')
    df15 = fetch_resampled('15m')
    if df3 is None or df15 is None:
        state['consecutive_failures'] = state.get('consecutive_failures', 0) + 1
        if state['consecutive_failures'] == 3:
            notifier.send_message(
                "⚠️ <b>Data fetch failing</b>\n\n"
                "The bot could not retrieve NIFTY data on 3 consecutive runs.\n"
                "Check the GitHub Actions logs for `nifty-trade-bot`."
            )
        save_state(state)
        logger.error("Failed to fetch market data")
        return

    df3 = keep_closed(df3, 3, now)
    df15 = keep_closed(df15, 15, now)
    if len(df3) < 20 or len(df15) < 20:
        logger.warning(f"Insufficient data: 3m={len(df3)} 15m={len(df15)}")
        save_state(state)
        return

    # ---- Indicators + latest closed candles ----
    df3 = Indicators.add_all_indicators(df3, "3m")
    df15 = Indicators.add_all_indicators(df15, "15m")
    latest3 = df3.iloc[-1]
    latest15 = df15.iloc[-1]

    strategy = StrategyEngine()
    htf_bias = strategy.determine_htf_bias(latest15)
    spot = float(latest3['close'])

    # ---- Exit management for open position ----
    position = state.get('open_position')
    if position:
        option_type = 'CALL' if position['type'] == 'BUY_CALL' else 'PUT'
        current_price = simulate_option_price(spot, position['strike'], option_type)
        reason = evaluate_exit(position, latest3, current_price, today, now)
        if reason:
            pnl = current_price - position['entry_price']
            pnl_pct = (pnl / position['entry_price'] * 100) if position['entry_price'] else 0
            emoji = "✅" if pnl >= 0 else "❌"
            notifier.send_message(
                f"{emoji} <b>TRADE CLOSED — {position['type']}</b>\n\n"
                f"🎯 <b>Strike:</b> {position['strike_label']}\n"
                f"💵 <b>Entry:</b> ₹{position['entry_price']:.2f}\n"
                f"💰 <b>Exit:</b> ₹{current_price:.2f}\n"
                f"📊 <b>P&L:</b> ₹{pnl:,.2f} ({pnl_pct:+.2f}%)\n"
                f"📝 <b>Reason:</b> {reason}\n"
                f"🕐 <b>Time:</b> {now.strftime('%I:%M %p')}"
            )
            logger.info(f"EXIT ({reason}) | P&L {pnl:+.2f} ({pnl_pct:+.2f}%)")
            state['open_position'] = None
    else:
        # ---- New entry (only when flat; MAX_POSITIONS = 1) ----
        signal = strategy.generate_signal(latest3, htf_bias, spot_price=spot)
        if signal:
            option_type = 'CALL' if signal['type'] == 'BUY_CALL' else 'PUT'
            entry_price = simulate_option_price(spot, signal['recommended_strike'], option_type)
            state['open_position'] = {
                'date': today,
                'type': signal['type'],
                'strike': signal['recommended_strike'],
                'strike_label': signal['strike_label'],
                'entry_price': entry_price,
                'entry_time': str(latest3.name),
                'entry_supertrend_direction': int(signal['indicators']['supertrend_direction']),
                'confidence': signal.get('confidence'),
            }
            notifier.send_signal(signal)
            logger.info(f"ENTRY: {signal['type']} {signal['strike_label']} "
                        f"@ ₹{entry_price:.2f} (spot {spot:,.2f})")

    state['consecutive_failures'] = 0
    save_state(state)
    logger.info("Run complete")


if __name__ == '__main__':
    main()
