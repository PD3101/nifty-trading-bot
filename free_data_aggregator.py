"""
Multi-Source Free Data Aggregator
Fetches NIFTY data from multiple free sources with fallbacks
NO PAID APIS - 100% FREE
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import time
from threading import Lock

# Import all free data sources
from nse_data_fetcher import NSEDataFetcher
import yfinance as yf

# TradingView
try:
    from tradingview_ta import TA_Handler, Interval
    TRADINGVIEW_AVAILABLE = True
except ImportError:
    TRADINGVIEW_AVAILABLE = False
    print("TradingView not available - install: pip install tradingview-ta")

logger = logging.getLogger(__name__)


class FreeDataAggregator:
    """
    Aggregates NIFTY data from multiple FREE sources
    Priority: NSE > TradingView > Yahoo Finance
    """

    def __init__(self):
        """Initialize data aggregator with all free sources"""
        self.nse_fetcher = NSEDataFetcher()
        self.lock = Lock()

        # Data cache
        self.last_spot_price = None
        self.last_update_time = None

        # Tick data for building candles
        self.tick_data = []  # Store minute-level ticks

        logger.info("Free data aggregator initialized")
        logger.info(f"TradingView available: {TRADINGVIEW_AVAILABLE}")

    def get_nifty_spot_price(self):
        """
        Get current NIFTY spot price from best available source

        Priority:
        1. NSE (most accurate)
        2. TradingView
        3. Yahoo Finance

        Returns:
            float: Current NIFTY spot price
        """
        # Try NSE first
        try:
            spot = self.nse_fetcher.get_nifty_spot()
            if spot and spot > 0:
                logger.info(f"Got spot from NSE: {spot:.2f}")
                self.last_spot_price = spot
                self.last_update_time = datetime.now()
                return spot
        except Exception as e:
            logger.warning(f"NSE fetch failed: {e}")

        # Try TradingView
        if TRADINGVIEW_AVAILABLE:
            try:
                nifty = TA_Handler(
                    symbol="NIFTY",
                    screener="india",
                    exchange="NSE",
                    interval=Interval.INTERVAL_1_MINUTE
                )
                analysis = nifty.get_analysis()
                spot = analysis.indicators.get('close')

                if spot and spot > 0:
                    logger.info(f"Got spot from TradingView: {spot:.2f}")
                    self.last_spot_price = spot
                    self.last_update_time = datetime.now()
                    return spot
            except Exception as e:
                logger.warning(f"TradingView fetch failed: {e}")

        # Try Yahoo Finance as last resort
        try:
            ticker = yf.Ticker("^NSEI")
            data = ticker.history(period="1d", interval="1m")
            if not data.empty:
                spot = float(data['Close'].iloc[-1])
                logger.info(f"Got spot from Yahoo Finance: {spot:.2f}")
                self.last_spot_price = spot
                self.last_update_time = datetime.now()
                return spot
        except Exception as e:
            logger.warning(f"Yahoo Finance fetch failed: {e}")

        # If all sources fail, return cached value
        if self.last_spot_price:
            logger.warning(f"All sources failed, using cached value: {self.last_spot_price:.2f}")
            return self.last_spot_price

        logger.error("All data sources failed and no cache available")
        return None

    def fetch_tick(self):
        """
        Fetch a single tick (1-minute data point)
        Store it for building candles

        Returns:
            dict: Tick data with timestamp and price
        """
        spot = self.get_nifty_spot_price()

        if spot:
            tick = {
                'timestamp': datetime.now(),
                'price': spot,
                'volume': 0  # We don't have volume from spot price
            }

            with self.lock:
                self.tick_data.append(tick)

                # Keep only last 24 hours of ticks
                cutoff = datetime.now() - timedelta(hours=24)
                self.tick_data = [t for t in self.tick_data if t['timestamp'] > cutoff]

            return tick

        return None

    def build_candles(self, interval_minutes=3):
        """
        Build OHLC candles from tick data

        Args:
            interval_minutes (int): Candle interval (3 or 15)

        Returns:
            pd.DataFrame: OHLC candles
        """
        with self.lock:
            if len(self.tick_data) < 2:
                logger.warning("Not enough tick data to build candles")
                return None

            # Convert ticks to DataFrame
            df = pd.DataFrame(self.tick_data)
            df.set_index('timestamp', inplace=True)

            # Resample to desired interval
            ohlc = df['price'].resample(f'{interval_minutes}min').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last'
            })

            # Add volume (placeholder - we don't have real volume from spot)
            ohlc['volume'] = 1000000  # Dummy volume

            # Drop incomplete candles
            ohlc = ohlc.dropna()

            return ohlc

    def get_live_candles_3m(self, periods=50):
        """
        Get live 3-minute candles

        Args:
            periods (int): Number of candles to return

        Returns:
            pd.DataFrame: 3-minute OHLC candles
        """
        candles = self.build_candles(interval_minutes=3)

        if candles is not None and len(candles) > 0:
            return candles.tail(periods)

        # Fallback: try Yahoo Finance for recent data
        logger.warning("Building candles failed, using Yahoo Finance")
        try:
            ticker = yf.Ticker("^NSEI")
            df = ticker.history(period="1d", interval="3m")

            if not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df[['open', 'high', 'low', 'close', 'volume']].tail(periods)
        except Exception as e:
            logger.error(f"Fallback to Yahoo Finance failed: {e}")

        return None

    def get_live_candles_15m(self, periods=50):
        """
        Get live 15-minute candles

        Args:
            periods (int): Number of candles to return

        Returns:
            pd.DataFrame: 15-minute OHLC candles
        """
        candles = self.build_candles(interval_minutes=15)

        if candles is not None and len(candles) > 0:
            return candles.tail(periods)

        # Fallback: try Yahoo Finance
        logger.warning("Building 15m candles failed, using Yahoo Finance")
        try:
            ticker = yf.Ticker("^NSEI")
            df = ticker.history(period="5d", interval="15m")

            if not df.empty:
                df.columns = [c.lower() for c in df.columns]
                return df[['open', 'high', 'low', 'close', 'volume']].tail(periods)
        except Exception as e:
            logger.error(f"Fallback to Yahoo Finance failed: {e}")

        return None

    def get_option_chain(self):
        """
        Get NIFTY option chain from NSE

        Returns:
            dict: Option chain data
        """
        try:
            return self.nse_fetcher.get_option_chain()
        except Exception as e:
            logger.error(f"Failed to fetch option chain: {e}")
            return None

    def get_best_strike(self, spot_price, option_type='CE', itm_range=35):
        """
        Get best ITM strike from option chain

        Args:
            spot_price (float): Current spot price
            option_type (str): 'CE' or 'PE'
            itm_range (int): Points ITM

        Returns:
            dict: Strike details
        """
        try:
            return self.nse_fetcher.get_best_strike(spot_price, option_type, itm_range)
        except Exception as e:
            logger.error(f"Failed to get best strike: {e}")

            # Fallback: calculate strike manually
            if option_type == 'CE':
                target_strike = spot_price - itm_range
            else:
                target_strike = spot_price + itm_range

            # Round to nearest 50
            strike = round(target_strike / 50) * 50

            return {
                'strike': strike,
                'ltp': 0,  # Unknown
                'volume': 0,
                'oi': 0,
                'symbol': f"NIFTY{strike}{option_type}"
            }

    def start_tick_collector(self, interval_seconds=60):
        """
        Start background thread to collect ticks every minute

        Args:
            interval_seconds (int): Fetch interval (default 60 = 1 minute)
        """
        import threading

        def collect_ticks():
            while True:
                try:
                    self.fetch_tick()
                    logger.debug("Tick collected")
                except Exception as e:
                    logger.error(f"Error collecting tick: {e}")

                time.sleep(interval_seconds)

        thread = threading.Thread(target=collect_ticks, daemon=True)
        thread.start()
        logger.info("Tick collector started (1-minute interval)")


def test_free_data_aggregator():
    """Test the free data aggregator"""
    print("Testing Free Data Aggregator...")
    print("="*60)

    aggregator = FreeDataAggregator()

    # Test 1: Get spot price
    print("\n1. Fetching NIFTY Spot Price...")
    spot = aggregator.get_nifty_spot_price()
    if spot:
        print(f"   ✓ Spot Price: {spot:.2f}")
    else:
        print("   ✗ Failed to fetch spot price")

    # Test 2: Fetch a few ticks
    print("\n2. Collecting ticks (this takes time)...")
    for i in range(3):
        tick = aggregator.fetch_tick()
        if tick:
            print(f"   Tick {i+1}: {tick['price']:.2f} at {tick['timestamp'].strftime('%H:%M:%S')}")
        time.sleep(2)

    # Test 3: Try building candles (may not work with only 3 ticks)
    print("\n3. Building candles...")
    candles_3m = aggregator.get_live_candles_3m(periods=10)
    if candles_3m is not None and len(candles_3m) > 0:
        print(f"   ✓ Got {len(candles_3m)} candles (3m)")
        print(candles_3m.tail(3))
    else:
        print("   - Not enough data yet (need more ticks)")

    # Test 4: Get option chain
    if spot:
        print("\n4. Getting best strike...")
        best_ce = aggregator.get_best_strike(spot, 'CE', 35)
        if best_ce:
            print(f"   ✓ Best CALL: {best_ce['strike']} @ ₹{best_ce.get('ltp', 'N/A')}")

    print("\n" + "="*60)
    print("Test Complete")
    print("\nNOTE: Full candle building requires collecting ticks over time")
    print("Bot will collect ticks every minute when running live")


if __name__ == "__main__":
    test_free_data_aggregator()
