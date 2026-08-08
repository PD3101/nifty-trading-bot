"""
Strategy Engine
Implements the core trading strategy logic:
- Higher Timeframe (15m) Bias Determination
- Lower Timeframe (3m) Entry Conditions
- Signal Generation
- Strike Selection
"""

import pandas as pd
import numpy as np
import config
from indicators import Indicators


class StrategyEngine:
    """
    Core strategy implementation following exact rules
    """

    def __init__(self):
        """
        Initialize strategy engine
        """
        self.signals = []
        self.current_htf_bias = None

    def determine_htf_bias(self, row_15m):
        """
        Determine Higher Timeframe (15m) Bias

        Bullish Bias:
        - Price above VWAP
        - Price above VWMA(20)
        - Supertrend Green (direction = 1)

        Bearish Bias:
        - Price below VWAP
        - Price below VWMA(20)
        - Supertrend Red (direction = -1)

        Mixed:
        - Any disagreement = NO TRADE

        Args:
            row_15m (pd.Series): 15-minute candle data with indicators

        Returns:
            str: 'BULLISH', 'BEARISH', or 'MIXED'
        """
        close = row_15m['close']
        vwap = row_15m['15m_vwap']
        vwma = row_15m['15m_vwma']
        supertrend_direction = row_15m['15m_supertrend_direction']

        # Check bullish conditions
        bullish_conditions = [
            close > vwap,
            close > vwma,
            supertrend_direction == 1
        ]

        # Check bearish conditions
        bearish_conditions = [
            close < vwap,
            close < vwma,
            supertrend_direction == -1
        ]

        # All bullish conditions met
        if all(bullish_conditions):
            return 'BULLISH'

        # All bearish conditions met
        elif all(bearish_conditions):
            return 'BEARISH'

        # Mixed conditions
        else:
            return 'MIXED'

    def check_ltf_call_entry(self, row_3m, htf_bias):
        """
        Check BUY CALL entry conditions on 3-minute timeframe

        All conditions must be true:
        1. Higher Timeframe is Bullish
        2. Price is above VWAP
        3. Price is above VWMA(20)
        4. Supertrend is Green (direction = 1)
        5. 3-minute candle CLOSES above ALL THREE indicators

        Args:
            row_3m (pd.Series): 3-minute candle data with indicators
            htf_bias (str): Higher timeframe bias

        Returns:
            dict: Signal information or None
        """
        # Condition 1: HTF must be bullish
        if htf_bias != 'BULLISH':
            return None

        close = row_3m['close']
        vwap = row_3m['3m_vwap']
        vwma = row_3m['3m_vwma']
        supertrend = row_3m['3m_supertrend']
        supertrend_direction = row_3m['3m_supertrend_direction']

        # Conditions 2, 3, 4, 5
        call_conditions = {
            'price_above_vwap': close > vwap,
            'price_above_vwma': close > vwma,
            'supertrend_green': supertrend_direction == 1,
            'candle_closed_above_all': close > max(vwap, vwma, supertrend)
        }

        # All conditions must be true
        if all(call_conditions.values()):
            return {
                'type': 'BUY_CALL',
                'timestamp': row_3m.name,
                'spot_price': close,
                'htf_bias': htf_bias,
                'conditions': call_conditions,
                'indicators': {
                    'vwap': vwap,
                    'vwma': vwma,
                    'supertrend': supertrend,
                    'supertrend_direction': supertrend_direction
                }
            }

        return None

    def check_ltf_put_entry(self, row_3m, htf_bias):
        """
        Check BUY PUT entry conditions on 3-minute timeframe

        All conditions must be true:
        1. Higher Timeframe is Bearish
        2. Price is below VWAP
        3. Price is below VWMA(20)
        4. Supertrend is Red (direction = -1)
        5. 3-minute candle CLOSES below ALL THREE indicators

        Args:
            row_3m (pd.Series): 3-minute candle data with indicators
            htf_bias (str): Higher timeframe bias

        Returns:
            dict: Signal information or None
        """
        # Condition 1: HTF must be bearish
        if htf_bias != 'BEARISH':
            return None

        close = row_3m['close']
        vwap = row_3m['3m_vwap']
        vwma = row_3m['3m_vwma']
        supertrend = row_3m['3m_supertrend']
        supertrend_direction = row_3m['3m_supertrend_direction']

        # Conditions 2, 3, 4, 5
        put_conditions = {
            'price_below_vwap': close < vwap,
            'price_below_vwma': close < vwma,
            'supertrend_red': supertrend_direction == -1,
            'candle_closed_below_all': close < min(vwap, vwma, supertrend)
        }

        # All conditions must be true
        if all(put_conditions.values()):
            return {
                'type': 'BUY_PUT',
                'timestamp': row_3m.name,
                'spot_price': close,
                'htf_bias': htf_bias,
                'conditions': put_conditions,
                'indicators': {
                    'vwap': vwap,
                    'vwma': vwma,
                    'supertrend': supertrend,
                    'supertrend_direction': supertrend_direction
                }
            }

        return None

    def select_option_strike(self, spot_price, signal_type):
        """
        Select option strike based on spot price

        Rules:
        - Recommend nearest slightly ITM option
        - Approximately 20-50 points ITM
        - Preferred Delta: 0.55 to 0.70

        Args:
            spot_price (float): Current NIFTY spot price
            signal_type (str): 'BUY_CALL' or 'BUY_PUT'

        Returns:
            float: Recommended strike price
        """
        # Round spot to nearest strike interval
        strike_interval = config.STRIKE_INTERVAL

        if signal_type == 'BUY_CALL':
            # For CALL, go slightly ITM (below spot)
            # Target: 20-50 points ITM
            itm_amount = (config.ITM_RANGE_MIN + config.ITM_RANGE_MAX) / 2  # 35 points avg

            target_strike = spot_price - itm_amount

            # Round to nearest strike interval (down for CALL)
            recommended_strike = int(target_strike // strike_interval) * strike_interval

        elif signal_type == 'BUY_PUT':
            # For PUT, go slightly ITM (above spot)
            # Target: 20-50 points ITM
            itm_amount = (config.ITM_RANGE_MIN + config.ITM_RANGE_MAX) / 2  # 35 points avg

            target_strike = spot_price + itm_amount

            # Round to nearest strike interval (up for PUT)
            recommended_strike = int(np.ceil(target_strike / strike_interval)) * strike_interval

        else:
            recommended_strike = None

        return recommended_strike

    def calculate_signal_confidence(self, signal):
        """
        Calculate confidence score for a signal

        Currently uses rule-based scoring
        Future: Can be enhanced with AI/ML

        Args:
            signal (dict): Signal information

        Returns:
            float: Confidence percentage (0-100)
        """
        confidence = 0

        # Base confidence for meeting all conditions
        confidence += 60

        # HTF alignment bonus
        if signal['htf_bias'] in ['BULLISH', 'BEARISH']:
            confidence += 20

        # Strong candle close bonus
        spot = signal['spot_price']
        indicators = signal['indicators']

        if signal['type'] == 'BUY_CALL':
            # How far above indicators
            distances = [
                spot - indicators['vwap'],
                spot - indicators['vwma'],
                spot - indicators['supertrend']
            ]
            avg_distance = np.mean(distances)
            if avg_distance > 10:  # Strong breakout
                confidence += 10
            elif avg_distance > 5:
                confidence += 5

        elif signal['type'] == 'BUY_PUT':
            # How far below indicators
            distances = [
                indicators['vwap'] - spot,
                indicators['vwma'] - spot,
                indicators['supertrend'] - spot
            ]
            avg_distance = np.mean(distances)
            if avg_distance > 10:  # Strong breakdown
                confidence += 10
            elif avg_distance > 5:
                confidence += 5

        # Cap at 100
        confidence = min(confidence, 100)

        return round(confidence, 1)

    def generate_signal_reason(self, signal):
        """
        Generate human-readable reason for signal

        Args:
            signal (dict): Signal information

        Returns:
            str: Formatted reason string
        """
        reasons = []

        # HTF bias
        reasons.append(f"15m {signal['htf_bias'].title()}")

        # Conditions
        if signal['type'] == 'BUY_CALL':
            reasons.append("Price Above VWAP")
            reasons.append("Price Above VWMA(20)")
            reasons.append("Supertrend Green")
            reasons.append("3m Candle Closed Above All Indicators")

        elif signal['type'] == 'BUY_PUT':
            reasons.append("Price Below VWAP")
            reasons.append("Price Below VWMA(20)")
            reasons.append("Supertrend Red")
            reasons.append("3m Candle Closed Below All Indicators")

        return " | ".join(reasons)

    def generate_signal(self, row_3m, htf_bias, spot_price=None):
        """
        Main signal generation method

        Strategy execution (HTF bias + entry confirmation) happens on the
        FUTURES 3m chart. Strike selection uses the SPOT price ONLY.

        Args:
            row_3m (pd.Series): 3-minute candle data (futures chart)
            htf_bias (str): Higher timeframe bias
            spot_price (float, optional): NIFTY SPOT price used ONLY for
                strike selection. If None, falls back to the 3m close.

        Returns:
            dict: Complete signal with all information or None
        """
        # Check for CALL entry
        call_signal = self.check_ltf_call_entry(row_3m, htf_bias)
        if call_signal:
            # Strike selection uses SPOT price (not futures)
            # Note: confidence scoring uses futures indicator distances
            strike_spot = spot_price if spot_price is not None else call_signal['spot_price']
            strike = self.select_option_strike(strike_spot, 'BUY_CALL')
            call_signal['recommended_strike'] = strike
            call_signal['strike_label'] = f"{int(strike)}CE"
            # Record which price was used for strike selection
            call_signal['strike_selection_price'] = strike_spot
            call_signal['futures_close'] = call_signal['spot_price']

            # Calculate confidence
            call_signal['confidence'] = self.calculate_signal_confidence(call_signal)

            # Generate reason
            call_signal['reason'] = self.generate_signal_reason(call_signal)

            return call_signal

        # Check for PUT entry
        put_signal = self.check_ltf_put_entry(row_3m, htf_bias)
        if put_signal:
            # Strike selection uses SPOT price (not futures)
            strike_spot = spot_price if spot_price is not None else put_signal['spot_price']
            strike = self.select_option_strike(strike_spot, 'BUY_PUT')
            put_signal['recommended_strike'] = strike
            put_signal['strike_label'] = f"{int(strike)}PE"
            # Record which price was used for strike selection
            put_signal['strike_selection_price'] = strike_spot
            put_signal['futures_close'] = put_signal['spot_price']

            # Calculate confidence
            put_signal['confidence'] = self.calculate_signal_confidence(put_signal)

            # Generate reason
            put_signal['reason'] = self.generate_signal_reason(put_signal)

            return put_signal

        return None


def test_strategy():
    """
    Test function to verify strategy logic
    """
    from data_fetcher import DataFetcher

    print("Testing Strategy Engine...")
    print("="*80)

    # Fetch data
    fetcher = DataFetcher(start_date="2024-07-01", end_date="2024-08-07")
    data = fetcher.prepare_data_for_backtesting()

    if data is None:
        print("Error: Could not fetch data for testing")
        return

    # Add indicators
    df_3m = Indicators.add_all_indicators(data['futures_3m'], "3m")
    df_15m = Indicators.add_all_indicators(data['futures_15m'], "15m")

    # Initialize strategy
    strategy = StrategyEngine()

    # Test on recent data
    print("\nScanning for signals...")
    signals = []

    for i in range(len(df_3m)):
        row_3m = df_3m.iloc[i]

        # Get corresponding 15m candle
        timestamp_3m = row_3m.name
        df_15m_before = df_15m[df_15m.index <= timestamp_3m]

        if len(df_15m_before) == 0:
            continue

        row_15m = df_15m_before.iloc[-1]

        # Determine HTF bias
        htf_bias = strategy.determine_htf_bias(row_15m)

        # Generate signal
        signal = strategy.generate_signal(row_3m, htf_bias)

        if signal:
            signals.append(signal)

    print(f"\nTotal signals found: {len(signals)}")

    # Display signals
    if signals:
        print("\n" + "="*80)
        print("SIGNALS GENERATED")
        print("="*80)

        for i, signal in enumerate(signals[:10], 1):  # Show first 10
            print(f"\nSignal #{i}")
            print(f"Type: {signal['type']}")
            print(f"Timestamp: {signal['timestamp']}")
            print(f"Spot Price: {signal['spot_price']:.2f}")
            print(f"Recommended Strike: {signal['strike_label']}")
            print(f"Confidence: {signal['confidence']}%")
            print(f"Reason: {signal['reason']}")
            print("-"*80)


if __name__ == "__main__":
    test_strategy()
