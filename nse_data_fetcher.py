"""
NSE Data Fetcher
Fetches real-time and historical data from NSE India
Replaces Yahoo Finance with official NSE sources
"""

import requests
import pandas as pd
import json
from datetime import datetime, timedelta
import time
import logging

logger = logging.getLogger(__name__)


class NSEDataFetcher:
    """
    Fetches data from NSE India official sources
    """

    def __init__(self):
        """Initialize NSE data fetcher"""
        self.base_url = "https://www.nseindia.com"
        self.session = requests.Session()

        # NSE requires proper headers
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.nseindia.com/'
        }
        self.session.headers.update(self.headers)

        # Initialize session with NSE
        self._init_session()

    def _init_session(self):
        """
        Initialize session with NSE to get cookies
        NSE requires valid session cookies
        """
        try:
            url = f"{self.base_url}/api/option-chain-indices?symbol=NIFTY"
            response = self.session.get(url, timeout=10)
            logger.info(f"NSE session initialized: {response.status_code}")
        except Exception as e:
            logger.warning(f"NSE session init warning: {e}")

    def get_nifty_spot(self):
        """
        Get current NIFTY spot price from NSE

        Returns:
            float: Current NIFTY spot price
        """
        try:
            url = f"{self.base_url}/api/equity-stockIndices?index=NIFTY%2050"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # Find NIFTY 50 in the data
                for item in data.get('data', []):
                    if item.get('symbol') == 'NIFTY 50' or item.get('index') == 'NIFTY 50':
                        return float(item.get('last', 0))

                logger.warning("NIFTY 50 not found in NSE response")
                return None

            else:
                logger.error(f"NSE API error: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error fetching NIFTY spot: {e}")
            return None

    def get_nifty_futures_ltp(self):
        """
        Get current month NIFTY Futures Last Traded Price

        Returns:
            float: NIFTY Futures LTP
        """
        try:
            url = f"{self.base_url}/api/equity-stockIndices?index=NIFTY%2050"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # Get futures data
                # Note: This is a simplified version
                # For real implementation, use proper futures endpoint

                for item in data.get('data', []):
                    if 'NIFTY' in item.get('symbol', ''):
                        return float(item.get('last', 0))

            logger.warning("Futures data not found")
            return None

        except Exception as e:
            logger.error(f"Error fetching futures: {e}")
            return None

    def get_option_chain(self, symbol='NIFTY'):
        """
        Get complete NIFTY option chain from NSE

        Args:
            symbol (str): Index symbol (default: NIFTY)

        Returns:
            dict: Option chain data with all strikes
        """
        try:
            url = f"{self.base_url}/api/option-chain-indices?symbol={symbol}"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                return data
            else:
                logger.error(f"Option chain fetch error: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return None

    def get_best_strike(self, spot_price, option_type='CE', itm_range=35):
        """
        Get best option strike from option chain

        Args:
            spot_price (float): Current spot price
            option_type (str): 'CE' for Call, 'PE' for Put
            itm_range (int): Points ITM (default 35)

        Returns:
            dict: Strike details with price, volume, OI, Greeks
        """
        try:
            option_chain = self.get_option_chain()

            if not option_chain:
                logger.error("Failed to fetch option chain")
                return None

            # Calculate target strike
            if option_type == 'CE':
                target_strike = spot_price - itm_range
            else:  # PE
                target_strike = spot_price + itm_range

            # Round to nearest 50
            target_strike = round(target_strike / 50) * 50

            # Find the strike in option chain
            records = option_chain.get('records', {}).get('data', [])

            for record in records:
                strike = record.get('strikePrice')

                if strike == target_strike:
                    option_data = record.get(option_type, {})

                    return {
                        'strike': strike,
                        'ltp': option_data.get('lastPrice', 0),
                        'bid': option_data.get('bidPrice', 0),
                        'ask': option_data.get('askPrice', 0),
                        'volume': option_data.get('totalTradedVolume', 0),
                        'oi': option_data.get('openInterest', 0),
                        'iv': option_data.get('impliedVolatility', 0),
                        'delta': option_data.get('delta', 0),
                        'symbol': option_data.get('identifier', '')
                    }

            logger.warning(f"Strike {target_strike} not found in option chain")
            return None

        except Exception as e:
            logger.error(f"Error getting best strike: {e}")
            return None


class ZerodhaDataFetcher:
    """
    Fetches data using Zerodha Historical API
    Requires Zerodha account and API subscription
    """

    def __init__(self, api_key=None, access_token=None):
        """
        Initialize Zerodha data fetcher

        Args:
            api_key (str): Zerodha API key
            access_token (str): Zerodha access token
        """
        self.api_key = api_key
        self.access_token = access_token

        # Note: Zerodha Kite Connect requires:
        # 1. Developer account (2000 INR/month)
        # 2. API credentials
        # 3. Daily login flow for access token

        logger.info("Zerodha fetcher initialized")

    def get_historical_data(self, instrument_token, from_date, to_date, interval='3minute'):
        """
        Get historical data from Zerodha

        Args:
            instrument_token (str): NIFTY Futures instrument token
            from_date (datetime): Start date
            to_date (datetime): End date
            interval (str): '3minute', '15minute', etc.

        Returns:
            pd.DataFrame: OHLCV data
        """
        try:
            # This requires kiteconnect library
            # from kiteconnect import KiteConnect
            # kite = KiteConnect(api_key=self.api_key)
            # kite.set_access_token(self.access_token)
            # data = kite.historical_data(instrument_token, from_date, to_date, interval)

            logger.warning("Zerodha Historical API requires paid subscription")
            logger.warning("Install: pip install kiteconnect")

            return None

        except Exception as e:
            logger.error(f"Zerodha API error: {e}")
            return None


class TradingViewDataFetcher:
    """
    Fetches data from TradingView (if API available)
    Note: TradingView doesn't have official public API
    """

    def __init__(self):
        """Initialize TradingView fetcher"""
        logger.info("TradingView fetcher initialized")
        logger.warning("TradingView has no official public API")

    def get_data(self, symbol, interval, bars):
        """
        Get data from TradingView

        Note: This would require unofficial libraries like:
        - tradingview-ta (for technical analysis only)
        - tvDatafeed (unofficial, may break)
        """
        logger.warning("TradingView data fetch not implemented")
        logger.warning("No official API available")
        return None


def test_nse_connection():
    """Test NSE data fetching"""
    print("Testing NSE Data Connection...")
    print("="*60)

    fetcher = NSEDataFetcher()

    # Test 1: Get NIFTY Spot
    print("\n1. Fetching NIFTY Spot Price...")
    spot = fetcher.get_nifty_spot()
    if spot:
        print(f"   ✓ NIFTY Spot: {spot:.2f}")
    else:
        print("   ✗ Failed to fetch spot price")

    # Test 2: Get Option Chain
    print("\n2. Fetching Option Chain...")
    option_chain = fetcher.get_option_chain()
    if option_chain:
        records = option_chain.get('records', {}).get('data', [])
        print(f"   ✓ Option Chain fetched: {len(records)} strikes")

        # Show sample strike
        if records:
            sample = records[0]
            print(f"   Sample Strike: {sample.get('strikePrice')}")
            ce_ltp = sample.get('CE', {}).get('lastPrice', 0)
            pe_ltp = sample.get('PE', {}).get('lastPrice', 0)
            print(f"   CE LTP: {ce_ltp}, PE LTP: {pe_ltp}")
    else:
        print("   ✗ Failed to fetch option chain")

    # Test 3: Get Best Strike
    if spot:
        print("\n3. Finding Best ITM Strike...")
        best_ce = fetcher.get_best_strike(spot, 'CE', 35)
        if best_ce:
            print(f"   ✓ Best CALL Strike: {best_ce['strike']} @ ₹{best_ce['ltp']}")
            print(f"     Volume: {best_ce['volume']}, OI: {best_ce['oi']}")

        best_pe = fetcher.get_best_strike(spot, 'PE', 35)
        if best_pe:
            print(f"   ✓ Best PUT Strike: {best_pe['strike']} @ ₹{best_pe['ltp']}")
            print(f"     Volume: {best_pe['volume']}, OI: {best_pe['oi']}")

    print("\n" + "="*60)
    print("NSE Connection Test Complete")


if __name__ == "__main__":
    test_nse_connection()
