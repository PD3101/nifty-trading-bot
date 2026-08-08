"""
Indicators Module
Calculates all technical indicators required for the strategy:
- VWAP (Volume Weighted Average Price)
- VWMA (Volume Weighted Moving Average)
- Supertrend
"""

import pandas as pd
import numpy as np
import config


class Indicators:
    """
    Technical indicator calculations for the trading strategy
    All calculations are non-repainting and based on closed candles only
    """

    @staticmethod
    def calculate_vwap(df):
        """
        Calculate Volume Weighted Average Price (VWAP)

        Args:
            df (pd.DataFrame): OHLCV dataframe with datetime index

        Returns:
            pd.Series: VWAP values
        """
        # Typical price
        typical_price = (df['high'] + df['low'] + df['close']) / 3

        # Group by date for session VWAP
        df_copy = df.copy()
        df_copy['typical_price'] = typical_price
        df_copy['volume_clean'] = df['volume'].fillna(0).clip(lower=0)
        df_copy['tp_volume'] = typical_price * df_copy['volume_clean']
        df_copy['date'] = df_copy.index.date

        # Calculate cumulative sums per session
        df_copy['cumulative_tp_volume'] = df_copy.groupby('date')['tp_volume'].cumsum()
        df_copy['cumulative_volume'] = df_copy.groupby('date')['volume_clean'].cumsum()

        # VWAP = cumulative(TP * Volume) / cumulative(Volume)
        # If no volume data, fall back to simple average of typical price (session SMA)
        with np.errstate(divide='ignore', invalid='ignore'):
            vwap = df_copy['cumulative_tp_volume'] / df_copy['cumulative_volume']
            vwap = vwap.where(df_copy['cumulative_volume'] > 0)

        # Fallback: session simple average of typical price when volume is zero
        session_sma = df_copy.groupby('date')['typical_price'].transform('mean')
        vwap = vwap.fillna(session_sma)

        return vwap

    @staticmethod
    def calculate_vwma(df, length=20):
        """
        Calculate Volume Weighted Moving Average (VWMA)
        Also referred to as VAMA in the strategy

        Args:
            df (pd.DataFrame): OHLCV dataframe
            length (int): Period length (default 20)

        Returns:
            pd.Series: VWMA values
        """
        # VWMA = SUM(close * volume, length) / SUM(volume, length)
        pv = df['close'] * df['volume']
        vol_roll = df['volume'].rolling(window=length).sum()

        with np.errstate(divide='ignore', invalid='ignore'):
            vwma = pv.rolling(window=length).sum() / vol_roll
            vwma = vwma.where(vol_roll > 0)

        # Fallback: simple moving average of close when no volume data
        sma = df['close'].rolling(window=length).mean()
        vwma = vwma.fillna(sma)

        return vwma

    @staticmethod
    def calculate_supertrend(df, period=10, multiplier=3.0):
        """
        Calculate Supertrend indicator

        Args:
            df (pd.DataFrame): OHLCV dataframe
            period (int): ATR period
            multiplier (float): ATR multiplier

        Returns:
            tuple: (supertrend, direction)
                - supertrend: pd.Series with supertrend line values
                - direction: pd.Series with direction (1 = bullish/green, -1 = bearish/red)
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # Calculate ATR
        atr = Indicators.calculate_atr(df, period)

        # Calculate basic bands
        hl_avg = (high + low) / 2

        upper_band = hl_avg + (multiplier * atr)
        lower_band = hl_avg - (multiplier * atr)

        # Initialize supertrend
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)

        # First row
        supertrend.iloc[0] = lower_band.iloc[0]
        direction.iloc[0] = 1

        # Calculate supertrend
        for i in range(1, len(df)):
            # Upper band logic
            if upper_band.iloc[i] < supertrend.iloc[i-1] or close.iloc[i-1] > supertrend.iloc[i-1]:
                curr_upper = upper_band.iloc[i]
            else:
                curr_upper = supertrend.iloc[i-1]

            # Lower band logic
            if lower_band.iloc[i] > supertrend.iloc[i-1] or close.iloc[i-1] < supertrend.iloc[i-1]:
                curr_lower = lower_band.iloc[i]
            else:
                curr_lower = supertrend.iloc[i-1]

            # Determine direction and supertrend value
            if supertrend.iloc[i-1] == curr_upper:
                if close.iloc[i] <= curr_upper:
                    supertrend.iloc[i] = curr_upper
                    direction.iloc[i] = -1  # Red/Bearish
                else:
                    supertrend.iloc[i] = curr_lower
                    direction.iloc[i] = 1   # Green/Bullish
            else:
                if close.iloc[i] >= curr_lower:
                    supertrend.iloc[i] = curr_lower
                    direction.iloc[i] = 1   # Green/Bullish
                else:
                    supertrend.iloc[i] = curr_upper
                    direction.iloc[i] = -1  # Red/Bearish

        return supertrend, direction

    @staticmethod
    def calculate_atr(df, period=14):
        """
        Calculate Average True Range (ATR)

        Args:
            df (pd.DataFrame): OHLCV dataframe
            period (int): ATR period

        Returns:
            pd.Series: ATR values
        """
        high = df['high']
        low = df['low']
        close = df['close']

        # True Range components
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        # True Range is the maximum of the three
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # ATR is the moving average of True Range
        # min_periods=1 avoids NaN warmup so Supertrend computes from row 0
        atr = tr.rolling(window=period, min_periods=1).mean()

        return atr

    @staticmethod
    def add_all_indicators(df, timeframe_label=""):
        """
        Add all indicators to a dataframe

        Args:
            df (pd.DataFrame): OHLCV dataframe
            timeframe_label (str): Label for column names (e.g., "3m", "15m")

        Returns:
            pd.DataFrame: DataFrame with all indicators added
        """
        df = df.copy()

        prefix = f"{timeframe_label}_" if timeframe_label else ""

        # Calculate VWAP
        df[f'{prefix}vwap'] = Indicators.calculate_vwap(df)

        # Calculate VWMA
        df[f'{prefix}vwma'] = Indicators.calculate_vwma(df, config.VWMA_LENGTH)

        # Calculate Supertrend
        supertrend, direction = Indicators.calculate_supertrend(
            df,
            config.SUPERTREND_PERIOD,
            config.SUPERTREND_MULTIPLIER
        )
        df[f'{prefix}supertrend'] = supertrend
        df[f'{prefix}supertrend_direction'] = direction

        return df


def test_indicators():
    """
    Test function to verify indicator calculations
    """
    from data_fetcher import DataFetcher

    print("Testing Indicator Calculations...")
    print("="*80)

    # Fetch data
    fetcher = DataFetcher(start_date="2024-07-01", end_date="2024-08-07")
    data = fetcher.prepare_data_for_backtesting()

    if data is None:
        print("Error: Could not fetch data for testing")
        return

    # Test on 15-minute data
    df_15m = data['futures_15m'].copy()

    print("\nCalculating indicators on 15-minute data...")
    df_15m = Indicators.add_all_indicators(df_15m, "15m")

    print("\nLast 10 rows with indicators:")
    print(df_15m[['close', '15m_vwap', '15m_vwma', '15m_supertrend', '15m_supertrend_direction']].tail(10))

    # Test on 3-minute data
    df_3m = data['futures_3m'].copy()

    print("\n" + "="*80)
    print("\nCalculating indicators on 3-minute data...")
    df_3m = Indicators.add_all_indicators(df_3m, "3m")

    print("\nLast 10 rows with indicators:")
    print(df_3m[['close', '3m_vwap', '3m_vwma', '3m_supertrend', '3m_supertrend_direction']].tail(10))

    print("\n" + "="*80)
    print("Indicator calculations complete!")


if __name__ == "__main__":
    test_indicators()
