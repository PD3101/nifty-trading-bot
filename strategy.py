"""
Strategy Engine — aligned with user's actual NIFTY Options Buying Strategy

All rules run on the 3-minute FUT chart. No 15m HTF bias.

Entry (CALL):
  1. Price ABOVE VWAP, VWMA-20, and Supertrend
  2. Supertrend direction = bullish (green)
  3. Pullback: in last N candles, price touched VWMA-20 (within tolerance)
  4. Bounce: current candle closes above VWMA-20 (and above all 3)
  5. No chase: not 4+ consecutive candles already in the same direction

Entry (PUT): mirror of above.

Strike: 1 strike ITM (50 pts) from SPOT price.
Stoploss: Supertrend LEVEL of the entry candle (price value, not direction).
Target: 1:2 Risk-Reward ratio.
"""

import numpy as np
import config
from indicators import Indicators


class StrategyEngine:

    def __init__(self):
        pass

    # ------------------------------------------------------------------
    # Pullback detection
    # ------------------------------------------------------------------

    def check_pullback(self, df_3m, current_idx, direction):
        """
        Check if price pulled back to VWMA-20 in the last PULLBACK_LOOKBACK
        candles. This is the "wait for pullback" entry trigger.

        CALL setup: low of a recent candle <= VWMA-20 * (1 + tolerance)
        PUT setup:  high of a recent candle >= VWMA-20 * (1 - tolerance)
        """
        lookback = config.PULLBACK_LOOKBACK
        tol = config.PULLBACK_TOLERANCE

        start = max(0, current_idx - lookback)
        window = df_3m.iloc[start:current_idx]  # exclude current candle

        if len(window) == 0:
            return False

        if direction == 'CALL':
            # Pullback = a recent candle's low came near or below VWMA-20
            touched = (window['low'] <= window['3m_vwma'] * (1 + tol)).any()
        else:
            # Pullback = a recent candle's high came near or above VWMA-20
            touched = (window['high'] >= window['3m_vwma'] * (1 - tol)).any()

        return bool(touched)

    # ------------------------------------------------------------------
    # No-chase detection
    # ------------------------------------------------------------------

    def check_no_chase(self, df_3m, current_idx):
        """
        Don't enter if the last N candles already moved strongly in one
        direction (chasing an extended move).

        Returns True if chasing (should NOT enter).
        """
        n = config.NO_CHASE_CANDLES
        start = max(0, current_idx - n)
        window = df_3m.iloc[start:current_idx + 1]

        if len(window) < n:
            return False

        closes = window['close'].values

        # Chasing bullish: all N candles closed above VWMA-20
        all_above = all(
            closes[i] > window['3m_vwma'].iloc[i]
            for i in range(len(closes))
        )
        # Chasing bearish: all N candles closed below VWMA-20
        all_below = all(
            closes[i] < window['3m_vwma'].iloc[i]
            for i in range(len(closes))
        )

        return all_above or all_below

    # ------------------------------------------------------------------
    # Entry conditions
    # ------------------------------------------------------------------

    def check_call_entry(self, row_3m, df_3m, current_idx):
        """
        CALL entry conditions (all must be true):
        1. Close > VWAP
        2. Close > VWMA-20
        3. Supertrend direction = bullish (1)
        4. Close > Supertrend level
        5. Pullback to VWMA-20 detected
        6. Not chasing (4+ candles already up)
        """
        close = row_3m['close']
        vwap = row_3m['3m_vwap']
        vwma = row_3m['3m_vwma']
        st_level = row_3m['3m_supertrend']
        st_dir = int(row_3m['3m_supertrend_direction'])

        # Basic indicator alignment
        if not (close > vwap and close > vwma and st_dir == 1 and close > st_level):
            return False

        # Pullback trigger
        if not self.check_pullback(df_3m, current_idx, 'CALL'):
            return False

        # No-chase filter
        if self.check_no_chase(df_3m, current_idx):
            return False

        return True

    def check_put_entry(self, row_3m, df_3m, current_idx):
        """
        PUT entry conditions (mirror of CALL):
        1. Close < VWAP
        2. Close < VWMA-20
        3. Supertrend direction = bearish (-1)
        4. Close < Supertrend level
        5. Pullback to VWMA-20 detected
        6. Not chasing
        """
        close = row_3m['close']
        vwap = row_3m['3m_vwap']
        vwma = row_3m['3m_vwma']
        st_level = row_3m['3m_supertrend']
        st_dir = int(row_3m['3m_supertrend_direction'])

        if not (close < vwap and close < vwma and st_dir == -1 and close < st_level):
            return False

        if not self.check_pullback(df_3m, current_idx, 'PUT'):
            return False

        if self.check_no_chase(df_3m, current_idx):
            return False

        return True

    # ------------------------------------------------------------------
    # Strike selection
    # ------------------------------------------------------------------

    def select_option_strike(self, spot_price, signal_type):
        """
        Default: 1 strike ITM (50 pts for NIFTY).
        ATM allowed ONLY on high-conviction setups (strong OI support) —
        OI data not yet available, so always ITM.
        """
        strike_interval = config.STRIKE_INTERVAL
        itm_points = config.ITM_POINTS  # 50 pts

        if signal_type == 'BUY_CALL':
            # ITM below spot
            target = spot_price - itm_points
            strike = int(target // strike_interval) * strike_interval
        elif signal_type == 'BUY_PUT':
            # ITM above spot
            target = spot_price + itm_points
            strike = int(np.ceil(target / strike_interval)) * strike_interval
        else:
            return None

        return strike

    # ------------------------------------------------------------------
    # Confidence (simplified — kept for compatibility)
    # ------------------------------------------------------------------

    def calculate_signal_confidence(self, signal):
        """Rule-based confidence score."""
        confidence = 60  # base for meeting all conditions
        spot = signal['spot_price']
        ind = signal['indicators']
        if signal['type'] == 'BUY_CALL':
            avg_dist = np.mean([spot - ind['vwap'], spot - ind['vwma'], spot - ind['supertrend']])
        else:
            avg_dist = np.mean([ind['vwap'] - spot, ind['vwma'] - spot, ind['supertrend'] - spot])
        if avg_dist > 10:
            confidence += 10
        elif avg_dist > 5:
            confidence += 5
        return min(confidence, 100)

    def generate_signal_reason(self, signal):
        reasons = []
        if signal['type'] == 'BUY_CALL':
            reasons = ["Price Above VWAP", "Price Above VWMA-20",
                       "Supertrend Green", "Pullback to VWMA-20 + Bounce",
                       "3m Candle Closed Above All Indicators"]
        else:
            reasons = ["Price Below VWAP", "Price Below VWMA-20",
                       "Supertrend Red", "Pullback to VWMA-20 + Rejection",
                       "3m Candle Closed Below All Indicators"]
        return " | ".join(reasons)

    # ------------------------------------------------------------------
    # Main signal generation
    # ------------------------------------------------------------------

    def generate_signal(self, row_3m, df_3m, current_idx, spot_price=None):
        """
        Generate a trading signal. No HTF bias — all on 3m.

        Args:
            row_3m: latest closed 3m candle (pd.Series)
            df_3m: full 3m DataFrame (for pullback/chase checks)
            current_idx: integer index position of row_3m in df_3m
            spot_price: SPOT price for strike selection (defaults to close)

        Returns:
            dict with signal info including 'supertrend_level' for stoploss
        """
        close = float(row_3m['close'])
        st_level = float(row_3m['3m_supertrend'])
        spot = spot_price if spot_price is not None else close

        # Check CALL
        if self.check_call_entry(row_3m, df_3m, current_idx):
            strike = self.select_option_strike(spot, 'BUY_CALL')
            signal = {
                'type': 'BUY_CALL',
                'timestamp': row_3m.name,
                'spot_price': spot,
                'futures_close': close,
                'recommended_strike': strike,
                'strike_label': f"{int(strike)}CE",
                'supertrend_level': st_level,   # STOPLOSS level
                'indicators': {
                    'vwap': float(row_3m['3m_vwap']),
                    'vwma': float(row_3m['3m_vwma']),
                    'supertrend': st_level,
                    'supertrend_direction': int(row_3m['3m_supertrend_direction']),
                },
            }
            signal['confidence'] = self.calculate_signal_confidence(signal)
            signal['reason'] = self.generate_signal_reason(signal)
            return signal

        # Check PUT
        if self.check_put_entry(row_3m, df_3m, current_idx):
            strike = self.select_option_strike(spot, 'BUY_PUT')
            signal = {
                'type': 'BUY_PUT',
                'timestamp': row_3m.name,
                'spot_price': spot,
                'futures_close': close,
                'recommended_strike': strike,
                'strike_label': f"{int(strike)}PE",
                'supertrend_level': st_level,   # STOPLOSS level
                'indicators': {
                    'vwap': float(row_3m['3m_vwap']),
                    'vwma': float(row_3m['3m_vwma']),
                    'supertrend': st_level,
                    'supertrend_direction': int(row_3m['3m_supertrend_direction']),
                },
            }
            signal['confidence'] = self.calculate_signal_confidence(signal)
            signal['reason'] = self.generate_signal_reason(signal)
            return signal

        return None
