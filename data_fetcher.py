"""
Data Fetcher Module
Fetches historical NIFTY Futures and Spot data
Handles timeframe resampling and data preparation
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

import config


class DataFetcher:
    """
    Fetches and prepares historical market data for backtesting
    """

    def __init__(self, start_date=None, end_date=None):
        """
        Initialize DataFetcher

        Args:
            start_date (str): Start date in 'YYYY-MM-DD' format
            end_date (str): End date in 'YYYY-MM-DD' format
        """
        self.start_date = start_date or config.BACKTEST_START_DATE
        self.end_date = end_date or config.BACKTEST_END_DATE
        self.futures_symbol = config.FUTURES_SYMBOL
        self.spot_symbol = config.SPOT_SYMBOL

    def fetch_nifty_data(self, interval='1m'):
        """
        Fetch NIFTY data from Yahoo Finance

        Args:
            interval (str): Data interval ('1m', '5m', '15m', '1h', '1d')

        Returns:
            pd.DataFrame: OHLCV data
        """
        print(f"Fetching NIFTY data from {self.start_date} to {self.end_date}...")

        try:
            # Download data
            ticker = yf.Ticker(self.futures_symbol)
            df = ticker.history(start=self.start_date, end=self.end_date, interval=interval)

            if df.empty:
                print(f"Warning: No data fetched for {self.futures_symbol}")
                return None

            # Clean column names
            df.columns = [col.lower() for col in df.columns]

            # Ensure we have required columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                print(f"Error: Missing required columns in data")
                return None

            df = df[required_cols]

            print(f"Fetched {len(df)} rows of data")
            return df

        except Exception as e:
            print(f"Error fetching data: {e}")
            return None

    def resample_to_timeframe(self, df, timeframe):
        """
        Resample data to specified timeframe

        Args:
            df (pd.DataFrame): OHLCV dataframe
            timeframe (str): Target timeframe ('3m', '15m', etc.)

        Returns:
            pd.DataFrame: Resampled data
        """
        if df is None or df.empty:
            return None

        # Parse timeframe
        timeframe_map = {
            '1m': '1min',
            '3m': '3min',
            '5m': '5min',
            '15m': '15min',
            '30m': '30min',
            '1h': '1H',
            '1d': '1D'
        }

        resample_rule = timeframe_map.get(timeframe, timeframe)

        # Resample OHLCV
        resampled = df.resample(resample_rule).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        })

        # Drop NaN rows
        resampled = resampled.dropna()

        return resampled

    def filter_market_hours(self, df):
        """
        Filter data to keep only market hours (09:15 to 15:30 IST)

        Args:
            df (pd.DataFrame): Input dataframe with datetime index

        Returns:
            pd.DataFrame: Filtered dataframe
        """
        if df is None or df.empty:
            return None

        # Convert to IST (UTC+5:30)
        # Note: yfinance returns UTC time, need to adjust

        # Filter by time
        df_filtered = df.between_time(config.MARKET_OPEN, config.MARKET_CLOSE)

        return df_filtered

    def prepare_data_for_backtesting(self):
        """
        Main method to prepare all required data for backtesting

        Returns:
            dict: Dictionary containing:
                - futures_3m: 3-minute futures data
                - futures_15m: 15-minute futures data
                - spot: spot data for strike selection
        """
        print("\n" + "="*80)
        print("PREPARING DATA FOR BACKTESTING")
        print("="*80)

        # Fetch 1-minute data (base resolution)
        # Note: Yahoo Finance has limitations on intraday data
        # For longer backtests, we may need to fetch daily data or use alternative sources

        # Check date range
        start = datetime.strptime(self.start_date, "%Y-%m-%d")
        end = datetime.strptime(self.end_date, "%Y-%m-%d")
        days_diff = (end - start).days

        if days_diff > 60:
            print("\nWarning: Date range is more than 60 days.")
            print("Yahoo Finance limits intraday data to ~60 days.")
            print("Fetching available intraday data or using daily data as fallback...")

            # Try fetching 5-minute data (more available than 1-minute)
            base_data = self.fetch_nifty_data(interval='5m')
            base_interval = '5m'
        else:
            # Fetch 1-minute data
            base_data = self.fetch_nifty_data(interval='1m')
            base_interval = '1m'

        if base_data is None or base_data.empty:
            print("\nFalling back to daily data for testing...")
            base_data = self.fetch_nifty_data(interval='1d')
            base_interval = '1d'

        if base_data is None or base_data.empty:
            print("Error: Could not fetch any data")
            return None

        print(f"\nBase data interval: {base_interval}")
        print(f"Data range: {base_data.index[0]} to {base_data.index[-1]}")

        # Filter market hours (if intraday data)
        if base_interval in ['1m', '5m']:
            base_data = self.filter_market_hours(base_data)
            print(f"After market hours filter: {len(base_data)} rows")

        # Resample to required timeframes
        print("\nResampling to required timeframes...")

        if base_interval == '1d':
            # For daily data, we'll use it as-is
            # This is for testing when intraday data is not available
            futures_3m = base_data.copy()
            futures_15m = base_data.copy()
            print("Note: Using daily data for both 3m and 15m timeframes (limited by data availability)")
        else:
            # Resample to 3 minutes
            futures_3m = self.resample_to_timeframe(base_data, '3m')
            print(f"3-minute data: {len(futures_3m)} rows")

            # Resample to 15 minutes
            futures_15m = self.resample_to_timeframe(base_data, '15m')
            print(f"15-minute data: {len(futures_15m)} rows")

        # For NIFTY, Futures and Spot are the same index (in our data source)
        # In production, you would fetch actual futures data
        spot = base_data.copy()

        data_dict = {
            'futures_3m': futures_3m,
            'futures_15m': futures_15m,
            'spot': spot,
            'base_interval': base_interval
        }

        print("\n" + "="*80)
        print("DATA PREPARATION COMPLETE")
        print("="*80)

        return data_dict


if __name__ == "__main__":
    # Test the data fetcher
    fetcher = DataFetcher()
    data = fetcher.prepare_data_for_backtesting()

    if data:
        print("\n" + "="*80)
        print("DATA SUMMARY")
        print("="*80)
        print("\n3-Minute Futures Data:")
        print(data['futures_3m'].head())
        print(f"\nTotal 3m candles: {len(data['futures_3m'])}")

        print("\n15-Minute Futures Data:")
        print(data['futures_15m'].head())
        print(f"\nTotal 15m candles: {len(data['futures_15m'])}")
