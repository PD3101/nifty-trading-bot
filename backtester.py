"""
Backtesting Engine
Simulates option trades based on strategy signals
Manages entries, exits, stop losses, and targets
Calculates performance metrics
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import config
from data_fetcher import DataFetcher
from indicators import Indicators
from strategy import StrategyEngine


class Trade:
    """
    Represents a single option trade
    """
    def __init__(self, signal, entry_time, entry_price):
        self.signal = signal
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl = 0
        self.pnl_percent = 0
        self.status = 'OPEN'
        self.peak_profit = 0
        self.max_drawdown = 0

    def close(self, exit_time, exit_price, reason):
        """Close the trade"""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason
        self.status = 'CLOSED'

        # Calculate P&L
        if self.signal['type'] == 'BUY_CALL':
            self.pnl = exit_price - self.entry_price
        elif self.signal['type'] == 'BUY_PUT':
            self.pnl = exit_price - self.entry_price

        self.pnl_percent = (self.pnl / self.entry_price) * 100 if self.entry_price > 0 else 0

    def update_metrics(self, current_price):
        """Update running metrics"""
        if self.signal['type'] == 'BUY_CALL':
            unrealized_pnl = current_price - self.entry_price
        elif self.signal['type'] == 'BUY_PUT':
            unrealized_pnl = current_price - self.entry_price
        else:
            unrealized_pnl = 0

        self.peak_profit = max(self.peak_profit, unrealized_pnl)

        drawdown_from_peak = self.peak_profit - unrealized_pnl
        self.max_drawdown = max(self.max_drawdown, drawdown_from_peak)


class Backtester:
    """
    Main backtesting engine
    """

    def __init__(self, start_date=None, end_date=None):
        """
        Initialize backtester

        Args:
            start_date (str): Start date for backtest
            end_date (str): End date for backtest
        """
        self.start_date = start_date or config.BACKTEST_START_DATE
        self.end_date = end_date or config.BACKTEST_END_DATE

        self.data_fetcher = DataFetcher(self.start_date, self.end_date)
        self.strategy = StrategyEngine()

        self.trades = []
        self.open_trade = None
        self.signals_log = []

    def simulate_option_price(self, spot_price, strike, option_type, direction='entry'):
        """
        Simulate option price based on spot movement

        This is a simplified simulation. In production, use:
        - Historical option chain data
        - Black-Scholes model
        - Actual market prices

        Args:
            spot_price (float): Current spot price
            strike (float): Strike price
            option_type (str): 'CALL' or 'PUT'
            direction (str): 'entry' or 'exit'

        Returns:
            float: Estimated option premium
        """
        # Simplified ITM value calculation
        if option_type == 'CALL':
            intrinsic = max(0, spot_price - strike)
        else:  # PUT
            intrinsic = max(0, strike - spot_price)

        # Add time value (simplified - around 20-40% of intrinsic for ITM)
        if intrinsic > 0:
            time_value = intrinsic * 0.3  # 30% time value
        else:
            time_value = spot_price * 0.01  # OTM options have some value

        option_price = intrinsic + time_value

        return option_price

    def check_stop_loss(self, trade, current_candle_3m, current_candle_15m):
        """
        Check if stop loss conditions are met

        Stop Loss Triggers:
        1. Supertrend flips
        2. Price closes back across VWAP
        3. Recent swing high/low violated

        Args:
            trade (Trade): Current open trade
            current_candle_3m (pd.Series): Current 3m candle
            current_candle_15m (pd.Series): Current 15m candle

        Returns:
            tuple: (should_exit, reason)
        """
        close = current_candle_3m['close']
        vwap = current_candle_3m['3m_vwap']
        st_direction = current_candle_3m['3m_supertrend_direction']

        entry_st_direction = trade.signal['indicators']['supertrend_direction']

        # Check 1: Supertrend flip
        if st_direction != entry_st_direction:
            return True, "Supertrend Flip"

        # Check 2: Price crosses VWAP (opposite to entry)
        if trade.signal['type'] == 'BUY_CALL':
            if close < vwap:
                return True, "Price Crossed Below VWAP"
        elif trade.signal['type'] == 'BUY_PUT':
            if close > vwap:
                return True, "Price Crossed Above VWAP"

        # Check 3: Swing violation (simplified - using supertrend as proxy)
        # In production, implement proper swing high/low detection

        return False, None

    def check_target(self, trade, current_price):
        """
        Check if target conditions are met

        Args:
            trade (Trade): Current open trade
            current_price (float): Current option price

        Returns:
            tuple: (should_exit, reason)
        """
        # Calculate current profit
        if trade.signal['type'] == 'BUY_CALL':
            profit = current_price - trade.entry_price
        elif trade.signal['type'] == 'BUY_PUT':
            profit = current_price - trade.entry_price
        else:
            profit = 0

        profit_percent = (profit / trade.entry_price) * 100 if trade.entry_price > 0 else 0

        # Simple target: 30% profit
        # In production, use support/resistance levels
        if profit_percent >= 30:
            return True, "Target Reached (30%)"

        return False, None

    def run_backtest(self):
        """
        Main backtesting loop

        Returns:
            dict: Backtest results
        """
        print("\n" + "="*80)
        print("STARTING BACKTEST")
        print("="*80)
        print(f"Period: {self.start_date} to {self.end_date}")
        print(f"Capital per trade: ₹{config.CAPITAL_PER_TRADE:,.0f}")
        print("="*80)

        # Fetch and prepare data
        data = self.data_fetcher.prepare_data_for_backtesting()

        if data is None:
            print("Error: Could not fetch data")
            return None

        # Add indicators
        print("\nCalculating indicators...")
        df_3m = Indicators.add_all_indicators(data['futures_3m'], "3m")
        df_15m = Indicators.add_all_indicators(data['futures_15m'], "15m")
        spot_df = data['spot']

        # Build a SPOT close series aligned to 3m timestamps.
        # SPOT is used ONLY for strike selection; strategy runs on futures (df_3m).
        if spot_df is not None and not spot_df.empty:
            spot_close = spot_df['close'].resample('3min').last().reindex(df_3m.index).ffill()
        else:
            spot_close = df_3m['close'].copy()

        print(f"3m candles: {len(df_3m)}")
        print(f"15m candles: {len(df_15m)}")

        # Backtesting loop
        print("\nRunning backtest...")

        for i in range(len(df_3m)):
            current_candle_3m = df_3m.iloc[i]
            current_time = current_candle_3m.name

            # Get corresponding 15m candle
            df_15m_before = df_15m[df_15m.index <= current_time]
            if len(df_15m_before) == 0:
                continue

            current_candle_15m = df_15m_before.iloc[-1]

            # Determine HTF bias
            htf_bias = self.strategy.determine_htf_bias(current_candle_15m)

            # Check if we have an open trade
            if self.open_trade:
                # Get current spot and option price
                current_spot = current_candle_3m['close']

                if self.open_trade.signal['type'] == 'BUY_CALL':
                    option_type = 'CALL'
                else:
                    option_type = 'PUT'

                current_option_price = self.simulate_option_price(
                    current_spot,
                    self.open_trade.signal['recommended_strike'],
                    option_type,
                    'exit'
                )

                # Update trade metrics
                self.open_trade.update_metrics(current_option_price)

                # Check stop loss
                should_exit_sl, sl_reason = self.check_stop_loss(
                    self.open_trade,
                    current_candle_3m,
                    current_candle_15m
                )

                if should_exit_sl:
                    self.open_trade.close(current_time, current_option_price, sl_reason)
                    self.trades.append(self.open_trade)
                    self.open_trade = None
                    continue

                # Check target
                should_exit_target, target_reason = self.check_target(
                    self.open_trade,
                    current_option_price
                )

                if should_exit_target:
                    self.open_trade.close(current_time, current_option_price, target_reason)
                    self.trades.append(self.open_trade)
                    self.open_trade = None
                    continue

            # No open trade - look for new signal
            else:
                # SPOT price for strike selection (strategy signals from futures 3m)
                spot_price_for_strike = float(spot_close.iloc[i]) if current_time in spot_close.index else float(current_candle_3m['close'])
                signal = self.strategy.generate_signal(current_candle_3m, htf_bias, spot_price=spot_price_for_strike)

                if signal:
                    self.signals_log.append(signal)

                    # Enter trade
                    current_spot = signal['spot_price']

                    if signal['type'] == 'BUY_CALL':
                        option_type = 'CALL'
                    else:
                        option_type = 'PUT'

                    entry_price = self.simulate_option_price(
                        current_spot,
                        signal['recommended_strike'],
                        option_type,
                        'entry'
                    )

                    trade = Trade(signal, current_time, entry_price)
                    self.open_trade = trade

        # Close any open trade at end of backtest
        if self.open_trade:
            last_candle = df_3m.iloc[-1]
            current_spot = last_candle['close']

            if self.open_trade.signal['type'] == 'BUY_CALL':
                option_type = 'CALL'
            else:
                option_type = 'PUT'

            exit_price = self.simulate_option_price(
                current_spot,
                self.open_trade.signal['recommended_strike'],
                option_type,
                'exit'
            )

            self.open_trade.close(last_candle.name, exit_price, "End of Backtest")
            self.trades.append(self.open_trade)
            self.open_trade = None

        # Calculate results
        results = self.calculate_results()

        return results

    def calculate_results(self):
        """
        Calculate backtest performance metrics

        Returns:
            dict: Performance metrics
        """
        if not self.trades:
            print("\nNo trades executed during backtest period")
            return None

        print(f"\n{'='*80}")
        print("BACKTEST RESULTS")
        print("="*80)

        # Basic metrics
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]

        num_wins = len(winning_trades)
        num_losses = len(losing_trades)

        win_rate = (num_wins / total_trades * 100) if total_trades > 0 else 0

        # P&L metrics
        total_pnl = sum(t.pnl for t in self.trades)
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0

        # Per trade type
        call_trades = [t for t in self.trades if t.signal['type'] == 'BUY_CALL']
        put_trades = [t for t in self.trades if t.signal['type'] == 'BUY_PUT']

        call_wins = len([t for t in call_trades if t.pnl > 0])
        put_wins = len([t for t in put_trades if t.pnl > 0])

        call_win_rate = (call_wins / len(call_trades) * 100) if call_trades else 0
        put_win_rate = (put_wins / len(put_trades) * 100) if put_trades else 0

        results = {
            'total_trades': total_trades,
            'winning_trades': num_wins,
            'losing_trades': num_losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'call_trades': len(call_trades),
            'put_trades': len(put_trades),
            'call_win_rate': call_win_rate,
            'put_win_rate': put_win_rate,
            'trades': self.trades,
            'signals': self.signals_log
        }

        # Print summary
        print(f"\nTotal Trades: {total_trades}")
        print(f"Winning Trades: {num_wins}")
        print(f"Losing Trades: {num_losses}")
        print(f"Win Rate: {win_rate:.2f}%")
        print(f"\nTotal P&L: ₹{total_pnl:,.2f}")
        print(f"Average Win: ₹{avg_win:,.2f}")
        print(f"Average Loss: ₹{avg_loss:,.2f}")
        print(f"\nCALL Trades: {len(call_trades)} (Win Rate: {call_win_rate:.2f}%)")
        print(f"PUT Trades: {len(put_trades)} (Win Rate: {put_win_rate:.2f}%)")

        print("\n" + "="*80)

        return results


if __name__ == "__main__":
    # Run backtest with dates from config
    # Config is set to last 7 days (Yahoo Finance 1m data limit)
    backtester = Backtester()  # Uses config.BACKTEST_START_DATE and config.BACKTEST_END_DATE

    results = backtester.run_backtest()

    if results and results['trades']:
        print("\n" + "="*80)
        print("SAMPLE TRADES")
        print("="*80)

        for i, trade in enumerate(results['trades'][:5], 1):
            print(f"\nTrade #{i}")
            print(f"Type: {trade.signal['type']}")
            print(f"Entry: {trade.entry_time} @ ₹{trade.entry_price:.2f}")
            print(f"Exit: {trade.exit_time} @ ₹{trade.exit_price:.2f}")
            print(f"P&L: ₹{trade.pnl:.2f} ({trade.pnl_percent:.2f}%)")
            print(f"Reason: {trade.exit_reason}")
            print(f"Strike: {trade.signal['strike_label']}")
            print(f"Confidence: {trade.signal['confidence']}%")
