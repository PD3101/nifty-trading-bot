"""
Backtesting Engine — aligned with actual strategy

- 3-minute chart only (no 15m HTF bias)
- Pullback to VWMA-20 trigger + no-chase filter
- Stoploss: Supertrend level of entry candle
- Target: 1:2 Risk-Reward (hybrid: 50% at 1:1, trail for 1:2)
- Max 2-3 trades/day, max 1-2 losses/day then stop
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import config
from data_fetcher import DataFetcher
from indicators import Indicators
from strategy import StrategyEngine


class Trade:
    def __init__(self, signal, entry_time, entry_price, stoploss_premium,
                 target_1_1, target_1_2):
        self.signal = signal
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.stoploss_premium = stoploss_premium
        self.target_1_1 = target_1_1
        self.target_1_2 = target_1_2
        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl = 0
        self.pnl_percent = 0
        self.status = 'OPEN'
        self.partial_booked = False
        self.partial_pnl = 0

    def close(self, exit_time, exit_price, reason, partial=False):
        lot = config.LOT_SIZE  # 65 for NIFTY
        if partial:
            # Book 50% at current price
            self.partial_pnl = (exit_price - self.entry_price) * 0.5 * lot
            self.partial_booked = True
            return

        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason
        self.status = 'CLOSED'
        pnl_full = (exit_price - self.entry_price) * lot
        # If partial was booked, remaining 50% P&L
        pnl_remaining = pnl_full * 0.5
        self.pnl = self.partial_pnl + pnl_remaining
        self.pnl_percent = (self.pnl / (self.entry_price * lot)) * 100 if self.entry_price else 0


def simulate_option_price(spot_price, strike, option_type):
    if option_type == 'CALL':
        intrinsic = max(0, spot_price - strike)
    else:
        intrinsic = max(0, strike - spot_price)
    time_value = intrinsic * 0.3 if intrinsic > 0 else spot_price * 0.01
    return intrinsic + time_value


class Backtester:
    def __init__(self, start_date=None, end_date=None):
        self.start_date = start_date or config.BACKTEST_START_DATE
        self.end_date = end_date or config.BACKTEST_END_DATE
        self.data_fetcher = DataFetcher(self.start_date, self.end_date)
        self.strategy = StrategyEngine()
        self.trades = []
        self.open_trade = None
        self.signals_log = []
        self.trades_today = 0
        self.losses_today = 0
        self.daily_stopped = False
        self.current_date = None

    def run_backtest(self):
        print("\n" + "=" * 80)
        print("STARTING BACKTEST")
        print(f"Period: {self.start_date} to {self.end_date}")
        print("=" * 80)

        data = self.data_fetcher.prepare_data_for_backtesting()
        if data is None:
            print("Error: Could not fetch data")
            return None

        df_3m = Indicators.add_all_indicators(data['futures_3m'], "3m")
        spot_df = data.get('spot')
        if spot_df is not None and not spot_df.empty:
            spot_close = spot_df['close'].resample('3min').last().reindex(df_3m.index).ffill()
        else:
            spot_close = df_3m['close'].copy()

        print(f"3m candles: {len(df_3m)}")
        print("\nRunning backtest...\n")

        for i in range(len(df_3m)):
            current_candle = df_3m.iloc[i]
            current_time = current_candle.name

            # Daily reset
            day = current_time.date() if hasattr(current_time, 'date') else current_time
            if day != self.current_date:
                self.current_date = day
                self.trades_today = 0
                self.losses_today = 0
                self.daily_stopped = False

            # Market hours filter
            if not self._in_market_hours(current_time):
                continue

            close = float(current_candle['close'])

            # --- Manage open trade ---
            if self.open_trade:
                opt_type = 'CALL' if self.open_trade.signal['type'] == 'BUY_CALL' else 'PUT'
                current_option_price = simulate_option_price(
                    close, self.open_trade.signal['recommended_strike'], opt_type
                )

                # Check stoploss: spot hits Supertrend level
                st_level = self.open_trade.signal['supertrend_level']
                exit_reason = None
                if self.open_trade.signal['type'] == 'BUY_CALL' and close <= st_level:
                    exit_reason = "Supertrend Stoploss"
                elif self.open_trade.signal['type'] == 'BUY_PUT' and close >= st_level:
                    exit_reason = "Supertrend Stoploss"

                # Check target 1:2
                if not exit_reason and current_option_price >= self.open_trade.target_1_2:
                    exit_reason = "Target 1:2 RR"

                # Hybrid: partial at 1:1
                if (not exit_reason and config.HYBRID_EXIT_ENABLED
                        and not self.open_trade.partial_booked
                        and current_option_price >= self.open_trade.target_1_1):
                    self.open_trade.close(current_time, current_option_price,
                                          "1:1 RR", partial=True)
                    print(f"  PARTIAL 1:1 at {current_time}")

                if exit_reason:
                    self.open_trade.close(current_time, current_option_price, exit_reason)
                    is_loss = self.open_trade.pnl < 0
                    self.trades.append(self.open_trade)
                    self.trades_today += 1
                    if is_loss:
                        self.losses_today += 1
                    self.open_trade = None

                    if (self.trades_today >= config.MAX_TRADES_PER_DAY or
                            self.losses_today >= config.MAX_LOSSES_PER_DAY):
                        self.daily_stopped = True
                continue

            # --- Look for new entry ---
            if self.daily_stopped:
                continue

            spot_price = float(spot_close.iloc[i]) if current_time in spot_close.index else close
            signal = self.strategy.generate_signal(
                current_candle, df_3m, i, spot_price=spot_price
            )
            if signal:
                self.signals_log.append(signal)
                opt_type = 'CALL' if signal['type'] == 'BUY_CALL' else 'PUT'
                entry_price = simulate_option_price(
                    spot_price, signal['recommended_strike'], opt_type
                )
                st_level = signal['supertrend_level']
                sl_premium = simulate_option_price(st_level, signal['recommended_strike'], opt_type)
                risk = abs(entry_price - sl_premium)
                if risk <= 0:
                    continue
                target_1_1 = entry_price + risk
                target_1_2 = entry_price + 2 * risk

                trade = Trade(signal, current_time, entry_price,
                              sl_premium, target_1_1, target_1_2)
                self.open_trade = trade

        # Close any open trade at end
        if self.open_trade:
            last = df_3m.iloc[-1]
            close = float(last['close'])
            opt_type = 'CALL' if self.open_trade.signal['type'] == 'BUY_CALL' else 'PUT'
            ep = simulate_option_price(close, self.open_trade.signal['recommended_strike'], opt_type)
            self.open_trade.close(last.name, ep, "End of Backtest")
            self.trades.append(self.open_trade)
            self.open_trade = None

        return self.calculate_results()

    def _in_market_hours(self, dt):
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            from datetime import timezone, timedelta
            ist = timezone(timedelta(hours=5, minutes=30))
            dt = dt.astimezone(ist)
        t = dt.time() if hasattr(dt, 'time') else None
        if t is None:
            return False
        from datetime import time as dtime
        market_open = dtime(9, 45)
        market_close = dtime(15, 30)
        lunch_start = dtime(12, 30)
        lunch_end = dtime(14, 0)
        if market_open <= t <= market_close:
            if lunch_start <= t <= lunch_end:
                return False
            return True
        return False

    def calculate_results(self):
        if not self.trades:
            print("\nNo trades executed")
            return None

        print(f"\n{'=' * 80}")
        print("BACKTEST RESULTS")
        print("=" * 80)

        total = len(self.trades)
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        win_rate = len(wins) / total * 100
        total_pnl = sum(t.pnl for t in self.trades)
        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = np.mean([t.pnl for t in losses]) if losses else 0

        print(f"Total Trades: {total}")
        print(f"Winning: {len(wins)} | Losing: {len(losses)}")
        print(f"Win Rate: {win_rate:.1f}%")
        print(f"Total P&L: ₹{total_pnl:,.2f}")
        print(f"Avg Win: ₹{avg_win:,.2f} | Avg Loss: ₹{avg_loss:,.2f}")
        print("=" * 80)

        call_trades = [t for t in self.trades if t.signal['type'] == 'BUY_CALL']
        put_trades = [t for t in self.trades if t.signal['type'] == 'BUY_PUT']
        call_wins = len([t for t in call_trades if t.pnl > 0])
        put_wins = len([t for t in put_trades if t.pnl > 0])

        return {
            'total_trades': total,
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'call_trades': len(call_trades),
            'put_trades': len(put_trades),
            'call_win_rate': call_wins / len(call_trades) * 100 if call_trades else 0,
            'put_win_rate': put_wins / len(put_trades) * 100 if put_trades else 0,
            'trades': self.trades,
            'signals': self.signals_log,
        }


if __name__ == "__main__":
    bt = Backtester()
    results = bt.run_backtest()
    if results and results['trades']:
        print("\nSAMPLE TRADES:")
        for i, t in enumerate(results['trades'][:5], 1):
            print(f"  #{i} {t.signal['type']} {t.signal['strike_label']} "
                  f"| Entry ₹{t.entry_price:.2f} → Exit ₹{t.exit_price:.2f} "
                  f"| P&L ₹{t.pnl:+.2f} ({t.exit_reason})")
