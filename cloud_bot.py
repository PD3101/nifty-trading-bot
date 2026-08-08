"""
Cloud-Optimized Trading Bot
Designed to run 24/7 on free cloud platforms
Auto-restarts, handles failures, minimal resource usage
"""

import time
import schedule
from datetime import datetime, time as dtime, timedelta
import pandas as pd
import yfinance as yf
import logging
import sys
import os

import config
from indicators import Indicators
from strategy import StrategyEngine
from telegram_notifier import TelegramNotifier


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('cloud_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class CloudTradingBot:
    """
    Cloud-optimized trading bot that runs 24/7
    """

    def __init__(self):
        """Initialize the cloud trading bot"""
        # Get Telegram credentials from environment variables (for cloud)
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or getattr(config, 'TELEGRAM_BOT_TOKEN', None)
        chat_id = os.getenv('TELEGRAM_CHAT_ID') or getattr(config, 'TELEGRAM_CHAT_ID', None)

        self.notifier = TelegramNotifier(bot_token, chat_id)
        self.strategy = StrategyEngine()

        self.running = True
        self.last_signal_time = None

        # Heartbeat for health checks
        self.last_heartbeat = datetime.now()

        logger.info("Cloud Trading Bot initialized")

    def fetch_live_data(self, interval='3m', lookback_days=2):
        """
        Fetch live market data.

        NOTE: Yahoo Finance does NOT support 3-minute intervals directly.
        We fetch 1-minute data and resample to the desired timeframe (3m/15m).

        Args:
            interval (str): Candle interval ('3m', '15m')
            lookback_days (int): Days of history to fetch

        Returns:
            pd.DataFrame: OHLCV data
        """
        try:
            # Fetch 1-minute base data (Yahoo supports 1m)
            ticker = yf.Ticker("^NSEI")
            df = ticker.history(period=f"{lookback_days}d", interval="1m")

            if df.empty:
                logger.warning(f"No 1-minute data available")
                return None

            df.columns = [col.lower() for col in df.columns]
            df = df[['open', 'high', 'low', 'close', 'volume']]

            # Resample to desired interval
            if interval == '3m':
                resampled = df.resample('3min').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna()
            elif interval == '15m':
                resampled = df.resample('15min').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last',
                    'volume': 'sum'
                }).dropna()
            else:
                resampled = df.copy()

            return resampled

        except Exception as e:
            logger.error(f"Error fetching data: {e}")
            return None

    def is_market_open(self):
        """
        Check if NSE is currently open (IST)
        Market hours: 09:15 - 15:30 IST, Monday-Friday

        IMPORTANT: NO trades before 09:45 IST (first 30 min = observation).
        Between 09:15 and 09:45 the bot observes but does not signal.

        Returns:
            bool: True if market is open AND trading is allowed (>= 09:45)
        """
        # Get current time in IST (UTC+5:30)
        from datetime import timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(ist)

        # Check weekday (0=Monday, 4=Friday)
        if now.weekday() > 4:
            return False

        # Market hours - NO trades before 09:45 AM IST (user requirement)
        trading_open = dtime(9, 45)
        market_close = dtime(15, 30)
        current_time = now.time()

        return trading_open <= current_time <= market_close

    def scan_market(self):
        """
        Main market scanning logic
        """
        try:
            logger.info("Scanning market...")

            # Fetch data
            data_3m = self.fetch_live_data('3m')
            data_15m = self.fetch_live_data('15m')

            if data_3m is None or data_15m is None:
                logger.error("Failed to fetch market data")
                return

            if len(data_3m) < 20 or len(data_15m) < 20:
                logger.warning("Insufficient data for indicators")
                return

            # Calculate indicators
            data_3m = Indicators.add_all_indicators(data_3m, "3m")
            data_15m = Indicators.add_all_indicators(data_15m, "15m")

            # Get latest candles
            latest_3m = data_3m.iloc[-1]
            latest_15m = data_15m.iloc[-1]

            # Check if already processed
            if self.last_signal_time == latest_3m.name:
                logger.debug("Already processed this candle")
                return

            # Determine bias and check signal
            htf_bias = self.strategy.determine_htf_bias(latest_15m)

            if htf_bias == 'MIXED':
                logger.debug("HTF bias is MIXED - no trade")
                return

            # SPOT price for strike selection (strategy runs on futures 3m).
            # Current data source uses ^NSEI as proxy for both futures & spot.
            spot_price_for_strike = float(latest_3m['close'])

            signal = self.strategy.generate_signal(
                latest_3m, htf_bias, spot_price=spot_price_for_strike
            )

            if signal:
                self.last_signal_time = latest_3m.name
                self.send_signal(signal)

        except Exception as e:
            logger.error(f"Error in market scan: {e}")

    def send_signal(self, signal):
        """Send signal notification"""
        try:
            logger.info(f"NEW SIGNAL: {signal['type']} at {signal['spot_price']:.2f}")

            if self.notifier.enabled:
                self.notifier.send_signal(signal)
                logger.info("Signal sent to Telegram")
            else:
                logger.warning("Telegram not configured")

        except Exception as e:
            logger.error(f"Error sending signal: {e}")

    def send_heartbeat(self):
        """
        Send periodic heartbeat to confirm bot is running
        """
        try:
            now = datetime.now()

            # Send heartbeat every 6 hours
            if (now - self.last_heartbeat).total_seconds() > 21600:
                if self.notifier.enabled:
                    msg = f"✅ <b>Bot Running</b>\n\n🕐 Time: {now.strftime('%Y-%m-%d %H:%M IST')}\n📊 Status: Active"
                    self.notifier.send_message(msg)

                self.last_heartbeat = now
                logger.info("Heartbeat sent")

        except Exception as e:
            logger.error(f"Error sending heartbeat: {e}")

    def run_scheduled_scan(self):
        """Scan only during market hours"""
        if self.is_market_open():
            logger.info("Market OPEN - scanning")
            self.scan_market()
        else:
            logger.debug("Market CLOSED - waiting")

    def start(self):
        """Start the cloud bot"""
        logger.info("="*60)
        logger.info("CLOUD TRADING BOT STARTED")
        logger.info("="*60)

        # Verify Telegram setup
        if not self.notifier.enabled:
            logger.error("TELEGRAM NOT CONFIGURED!")
            logger.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")
            logger.error("Or add them to config.py")

        else:
            # Send startup notification
            msg = """
🚀 <b>CLOUD BOT STARTED</b>

✅ Running 24/7 on cloud
📊 Monitoring NIFTY markets
📱 Telegram alerts enabled

<i>You will receive signals automatically during market hours</i>
            """
            self.notifier.send_message(msg.strip())
            logger.info("Startup notification sent")

        # Schedule scans
        schedule.every(1).minutes.do(self.run_scheduled_scan)
        schedule.every(6).hours.do(self.send_heartbeat)

        # Initial scan
        self.run_scheduled_scan()

        logger.info("Bot is now running. Monitoring market...")
        logger.info("="*60)

        # Main loop
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(10)  # Check every 10 seconds

        except KeyboardInterrupt:
            logger.info("Bot stopped by user")

        except Exception as e:
            logger.error(f"Bot crashed: {e}")
            # Try to notify via Telegram before dying
            if self.notifier.enabled:
                self.notifier.send_message(f"⚠️ <b>BOT CRASHED</b>\n\nError: {str(e)}")
            raise


def main():
    """Main entry point"""
    print("""
╔═════════════════════════════════════════════════════════════╗
║         NIFTY OPTIONS CLOUD TRADING BOT                     ║
║                                                             ║
║  🤖 Running 24/7 on cloud                                   ║
║  📊 Live market monitoring                                  ║
║  📱 Telegram notifications                                  ║
║                                                             ║
╚═════════════════════════════════════════════════════════════╝
    """)

    bot = CloudTradingBot()
    bot.start()


if __name__ == "__main__":
    main()
