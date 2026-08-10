"""
One-shot runner for GitHub Actions — fully aligned with the actual strategy.

Single market check per run:
  - 3-minute FUT chart only (no 15m HTF bias)
  - Pullback to VWMA-20 entry trigger
  - No-chase filter (4+ consecutive candles)
  - Stoploss at Supertrend LEVEL of entry candle
  - 1:2 RR target (hybrid: 50% at 1:1, trail 50% for 1:2)
  - Max 2-3 trades/day, max 1-2 losses/day then stop
  - Lunch hours 12:30-2:00 PM avoided

State (open position, daily counters) persists between runs via GH Actions cache.
"""

import json
import logging
import os
import sys
from datetime import time as dtime, timedelta

import pandas as pd
import numpy as np

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

LUNCH_START = dtime(12, 30)
LUNCH_END = dtime(14, 0)
MARKET_CLOSE_TIME = dtime(15, 30)


# ======================================================================
# Helpers
# ======================================================================

def simulate_option_price(spot_price, strike, option_type):
    """Simplified option premium model (mirrors backtester)."""
    if option_type == 'CALL':
        intrinsic = max(0, spot_price - strike)
    else:
        intrinsic = max(0, strike - spot_price)
    time_value = intrinsic * 0.3 if intrinsic > 0 else spot_price * 0.01
    return intrinsic + time_value


def fetch_3m_data(lookback_days=5):
    """Fetch NIFTY futures 3m candles from Kite Connect ONLY."""
    from kite_fetcher import fetch_3m_data as kite_fetch
    return kite_fetch(lookback_days)


def keep_closed(df, period_minutes, now):
    """Keep only candles that have fully closed (non-repainting)."""
    close_at = df.index + pd.Timedelta(minutes=period_minutes)
    return df[close_at <= now]


def load_state():
    default = {
        'date': '2000-01-01',
        'open_position': None,
        'consecutive_failures': 0,
        'trades_today': 0,
        'losses_today': 0,
        'daily_stopped': False,
    }
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
            if not isinstance(state, dict):
                return default
            # Ensure all keys present
            for k, v in default.items():
                state.setdefault(k, v)
            return state
    except Exception:
        return default


def save_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


# ======================================================================
# Exit evaluation
# ======================================================================

def evaluate_exit(position, row_3m, current_option_price, today, now):
    """
    Check exit conditions. Returns (reason, partial_exit) or (None, False).

    partial_exit=True means "book 50% now, keep trailing" (1:1 hit).
    partial_exit=False + reason means "full exit" (stoploss or 1:2 target).
    """
    close = float(row_3m['close'])

    # End of day / previous day
    if position.get('date') != today:
        return "End of Day (position from a previous day)", False
    if now.time() >= MARKET_CLOSE_TIME:
        return "End of Day (Market Close)", False

    entry_price = position['entry_price']
    stoploss_premium = position['stoploss_premium']
    target_1_1 = position['target_1_1']
    target_1_2 = position['target_1_2']
    entry_spot = position['entry_spot']
    st_level = position['entry_supertrend_level']
    signal_type = position['type']

    # --- Stoploss: spot hits Supertrend level of entry candle ---
    if signal_type == 'BUY_CALL' and close <= st_level:
        return "Supertrend Stoploss", False
    if signal_type == 'BUY_PUT' and close >= st_level:
        return "Supertrend Stoploss", False

    # --- Target 1:2 ---
    if current_option_price >= target_1_2:
        return "Target 1:2 RR", False

    # --- Partial exit at 1:1 (hybrid) ---
    if config.HYBRID_EXIT_ENABLED and not position.get('partial_booked'):
        if current_option_price >= target_1_1:
            return "1:1 RR — Book 50%", True

    return None, False


# ======================================================================
# Telegram alert formatting
# ======================================================================

def send_entry_alert(notifier, signal, entry_price, stoploss_premium,
                     target_1_1, target_1_2, now):
    lot = config.LOT_SIZE
    emoji = "🟢" if signal['type'] == 'BUY_CALL' else "🔴"
    signal_type = "BUY CALL" if signal['type'] == 'BUY_CALL' else "BUY PUT"
    risk = entry_price - stoploss_premium if signal['type'] == 'BUY_CALL' \
        else stoploss_premium - entry_price
    cost = entry_price * lot

    msg = (
        f"{emoji} <b>{signal_type} — ENTRY</b>\n\n"
        f"🎯 <b>Strike:</b> {signal['strike_label']} (ITM)\n"
        f"💰 <b>LTP:</b> ₹{entry_price:.2f} × {lot} = ₹{cost:,.0f}\n"
        f"📍 <b>Spot:</b> {signal['spot_price']:,.2f}\n"
        f"🛑 <b>SL:</b> ₹{stoploss_premium:.2f} (Risk ₹{risk * lot:,.0f})\n\n"
        f"🎯 <b>Tgt 1:1 →</b> ₹{target_1_1:.2f} (book 50%)\n"
        f"🎯 <b>Tgt 1:2 →</b> ₹{target_1_2:.2f} (full exit)\n\n"
        f"📋 {signal['reason'].replace(' | ', chr(10) + '✓ ')}\n\n"
        f"🕐 <b>{now.strftime('%I:%M %p')}</b>"
    )
    notifier.send_message(msg)


def send_partial_exit_alert(notifier, position, current_price, now):
    lot = config.LOT_SIZE
    pnl = (current_price - position['entry_price']) * lot
    cost = position['entry_price'] * lot
    pnl_pct = (pnl / cost * 100) if cost else 0
    msg = (
        f"📊 <b>PARTIAL EXIT — 50% BOOKED</b>\n\n"
        f"🎯 <b>Strike:</b> {position['strike_label']}\n"
        f"💰 <b>Entry:</b> ₹{position['entry_price']:.2f} × {lot} = ₹{cost:,.0f}\n"
        f"💰 <b>Now:</b> ₹{current_price:.2f} (1:1 RR hit)\n"
        f"📈 <b>P&L (50%):</b> ₹{pnl:+,.0f} ({pnl_pct:+.1f}%)\n\n"
        f"📝 Trailing remaining 50% for 1:2 target\n"
        f"🕐 <b>{now.strftime('%I:%M %p')}</b>"
    )
    notifier.send_message(msg)


def send_full_exit_alert(notifier, position, current_price, reason, now):
    lot = config.LOT_SIZE
    pnl = (current_price - position['entry_price']) * lot
    cost = position['entry_price'] * lot
    pnl_pct = (pnl / cost * 100) if cost else 0
    emoji = "✅" if pnl >= 0 else "❌"
    msg = (
        f"{emoji} <b>TRADE CLOSED — {reason}</b>\n\n"
        f"🎯 <b>Strike:</b> {position['strike_label']}\n"
        f"💵 <b>Entry:</b> ₹{position['entry_price']:.2f} × {lot} = ₹{cost:,.0f}\n"
        f"💰 <b>Exit:</b> ₹{current_price:.2f} × {lot} = ₹{current_price * lot:,.0f}\n"
        f"📊 <b>P&L:</b> ₹{pnl:+,.0f} ({pnl_pct:+.1f}%)\n"
        f"📝 <b>Reason:</b> {reason}\n"
        f"🕐 <b>{now.strftime('%I:%M %p')}</b>"
    )
    notifier.send_message(msg)


def send_daily_stop_alert(notifier, trades, losses, now):
    reason = f"Max losses ({losses}/{config.MAX_LOSSES_PER_DAY})" if losses >= config.MAX_LOSSES_PER_DAY \
        else f"Max trades ({trades}/{config.MAX_TRADES_PER_DAY})"
    msg = (
        f"🛑 <b>TRADING STOPPED FOR TODAY</b>\n\n"
        f"📝 <b>Reason:</b> {reason}\n"
        f"📊 Trades today: {trades}\n"
        f"❌ Losses today: {losses}\n\n"
        f"🕐 <b>{now.strftime('%I:%M %p')}</b>"
    )
    notifier.send_message(msg)


# ======================================================================
# Main runner
# ======================================================================

def main():
    timing = MarketTimingManager()
    now = timing.get_ist_time()
    today = now.strftime('%Y-%m-%d')

    # --- Test mode (workflow_dispatch) ---
    if os.getenv('GH_ACTION_TEST', '').lower() in ('1', 'true'):
        notifier = TelegramNotifier()
        if notifier.enabled:
            notifier.send_message(
                f"🧪 <b>GitHub Actions test</b>\n\n"
                f"✅ Strategy-aligned runner works on GitHub\n"
                f"🕐 {now.strftime('%Y-%m-%d %H:%M %Z')}\n"
                f"🤖 Ready to trade Monday 09:45 AM IST"
            )
            print("Test message sent: True")
        return

    notifier = TelegramNotifier()
    if not notifier.enabled:
        logger.error("Telegram not configured")
        sys.exit(1)

    state = load_state()

    # --- Daily reset ---
    if state.get('date') != today:
        state = {
            'date': today,
            'open_position': None,
            'consecutive_failures': 0,
            'trades_today': 0,
            'losses_today': 0,
            'daily_stopped': False,
        }
        if timing.is_weekday(now) and not timing.is_holiday(now):
            notifier.send_message(
                f"🟢 <b>Bot Online — {today}</b>\n\n"
                f"🕐 {now.strftime('%I:%M %p %Z')}\n"
                f"📡 Scanning NIFTY FUT 3m every 5 min (09:45–15:30)\n"
                f"🎯 Entry: pullback to VWMA-20 + bounce\n"
                f"🛑 SL: Supertrend level | Target: 1:2 RR\n"
                f"📊 Max {config.MAX_TRADES_PER_DAY} trades, "
                f"max {config.MAX_LOSSES_PER_DAY} losses/day\n"
                f"🍛 Lunch break: 12:30–2:00 PM"
            )

    # --- Scan-only mode: fetch today's data and report signals ---
    if os.getenv('SCAN_TODAY', '').lower() in ('1', 'true'):
        logger.info("Scan-only mode: fetching today's Kite data...")
        df3 = fetch_3m_data(lookback_days=2)
        if df3 is None:
            notifier.send_message("⚠️ <b>Scan failed</b>\n\nCould not fetch Kite data.")
            return

        # Filter to the latest trading day in the data (handles post-midnight runs)
        data_date = df3.index[-1].date()
        day_start = df3.index[-1].replace(hour=9, minute=15, second=0, microsecond=0)
        day_end = df3.index[-1].replace(hour=15, minute=30, second=0, microsecond=0)
        df3 = df3[(df3.index >= day_start) & (df3.index <= day_end)]

        if len(df3) < 20:
            notifier.send_message(f"⚠️ <b>Insufficient data</b>\n\nOnly {len(df3)} candles for {data_date}.")
            return

        df3 = Indicators.add_all_indicators(df3, "3m")
        strategy = StrategyEngine()
        signals = []

        for i in range(20, len(df3)):
            row = df3.iloc[i]
            spot = float(row['close'])
            sig = strategy.generate_signal(row, df3, i, spot_price=spot)
            if sig:
                signals.append({
                    'time': str(df3.index[i]),
                    'type': sig['type'],
                    'strike': sig.get('recommended_strike'),
                    'strike_label': sig.get('strike_label'),
                    'spot': spot,
                    'reason': sig.get('reason', ''),
                    'confidence': sig.get('confidence'),
                })

        # Build report
        if signals:
            lines = [f"📊 <b>SCAN — {data_date} — {len(signals)} signal(s) found</b>\n"]
            for s in signals:
                emoji = "🟢" if s['type'] == 'BUY_CALL' else "🔴"
                stype = "CE" if s['type'] == 'BUY_CALL' else "PE"
                lines.append(
                    f"{emoji} <b>{s['time'][-14:-6]}</b> — "
                    f"{s['strike_label']} ({stype})\n"
                    f"   Spot: {s['spot']:,.2f} | Confidence: {s.get('confidence', 'N/A')}%"
                )
            msg = "\n".join(lines)
        else:
            msg = f"📊 <b>SCAN — {data_date} — No signals</b>\n\nThe strategy found no entry setups (pullback to VWMA-20 + Supertrend confirmation)."

        notifier.send_message(msg)
        print(f"Scan complete: {len(signals)} signals")
        return

    # --- Trading window checks ---
    if not timing.can_trade_now():
        save_state(state)
        return

    # Lunch hour filter
    if LUNCH_START <= now.time() <= LUNCH_END:
        logger.info("Lunch hour — skipping")
        save_state(state)
        return

    # Daily stop check
    if state.get('daily_stopped'):
        save_state(state)
        return

    # --- Fetch 3m data only (no 15m) ---
    df3 = fetch_3m_data()
    if df3 is None:
        state['consecutive_failures'] = state.get('consecutive_failures', 0) + 1
        if state['consecutive_failures'] == 3:
            notifier.send_message(
                "⚠️ <b>Data fetch failing</b>\n\n"
                "3 consecutive failures. Check GitHub Actions logs."
            )
        save_state(state)
        return

    df3 = keep_closed(df3, 3, now)
    if len(df3) < 20:
        logger.warning(f"Insufficient 3m data: {len(df3)} candles")
        save_state(state)
        return

    df3 = Indicators.add_all_indicators(df3, "3m")
    latest3 = df3.iloc[-1]
    current_idx = len(df3) - 1
    spot = float(latest3['close'])
    strategy = StrategyEngine()

    # --- Open position → check exits ---
    position = state.get('open_position')
    if position:
        opt_type = 'CALL' if position['type'] == 'BUY_CALL' else 'PUT'
        current_price = simulate_option_price(spot, position['strike'], opt_type)

        reason, partial = evaluate_exit(position, latest3, current_price, today, now)

        if partial:
            # Hybrid exit: book 50% at 1:1
            send_partial_exit_alert(notifier, position, current_price, now)
            state['open_position']['partial_booked'] = True
            logger.info(f"PARTIAL EXIT at 1:1 | price={current_price:.2f}")

        elif reason:
            send_full_exit_alert(notifier, position, current_price, reason, now)
            is_loss = current_price < position['entry_price']
            state['trades_today'] = state.get('trades_today', 0) + 1
            if is_loss:
                state['losses_today'] = state.get('losses_today', 0) + 1
            state['open_position'] = None
            logger.info(f"EXIT ({reason}) | P&L {current_price - position['entry_price']:+.2f}")

            # Check if we should stop for the day
            if (state['trades_today'] >= config.MAX_TRADES_PER_DAY or
                    state['losses_today'] >= config.MAX_LOSSES_PER_DAY):
                state['daily_stopped'] = True
                send_daily_stop_alert(notifier, state['trades_today'],
                                      state['losses_today'], now)
                logger.info("Daily limit reached — trading stopped")

    # --- Flat → look for entry ---
    else:
        signal = strategy.generate_signal(latest3, df3, current_idx, spot_price=spot)
        if signal:
            opt_type = 'CALL' if signal['type'] == 'BUY_CALL' else 'PUT'
            entry_price = simulate_option_price(spot, signal['recommended_strike'], opt_type)
            st_level = signal['supertrend_level']

            # Compute stoploss and targets
            sl_premium = simulate_option_price(st_level, signal['recommended_strike'], opt_type)
            risk = abs(entry_price - sl_premium)
            if risk <= 0:
                logger.warning("Risk is zero — skipping entry")
                save_state(state)
                return
            target_1_1 = entry_price + risk   # 1:1 RR
            target_1_2 = entry_price + 2 * risk  # 1:2 RR

            state['open_position'] = {
                'date': today,
                'type': signal['type'],
                'strike': signal['recommended_strike'],
                'strike_label': signal['strike_label'],
                'entry_price': entry_price,
                'entry_spot': spot,
                'entry_supertrend_level': st_level,
                'entry_time': str(latest3.name),
                'stoploss_premium': sl_premium,
                'target_1_1': target_1_1,
                'target_1_2': target_1_2,
                'partial_booked': False,
                'confidence': signal.get('confidence'),
            }

            send_entry_alert(notifier, signal, entry_price, sl_premium,
                             target_1_1, target_1_2, now)
            logger.info(f"ENTRY: {signal['type']} {signal['strike_label']} "
                        f"@ ₹{entry_price:.2f} | SL ₹{sl_premium:.2f} "
                        f"| T1 ₹{target_1_1:.2f} | T2 ₹{target_1_2:.2f}")

    state['consecutive_failures'] = 0
    save_state(state)
    logger.info("Run complete")


if __name__ == '__main__':
    main()
