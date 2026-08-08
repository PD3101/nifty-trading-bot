"""
Live Trading Agent
Autonomous bot that monitors NIFTY markets in real-time
Generates signals and sends Telegram notifications 24/7
"""

import time
import schedule
from datetime import datetime, time as dtime
import pandas as pd
import yfinance as yf
from threading import Thread
import logging

import config
from indicators import Indicators
from strategy import StrategyEngine
from telegram_notifier import TelegramNotifier


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LiveTradingAgent:
    """
    Autonomous trading agent that runs 24/7
    """

    def __init__(self):
        """Initialize the live trading agent"""
        self.strategy = StrategyEngine()
        self.notifier = TelegramNotifier()
        self.running = False

        # Data buffers for indicators
        self.data_3m = pd.DataFrame()
        self.data_15m = pd.DataFrame()

        # Track last signal to avoid duplicates
        self.last_signal_time = None

        # Current open trade
        self.current_trade = None

        logger.info("Live Trading Agent initialized")

    def fetch_live_data(self, interval='1m'):
        """
        Fetch latest live data from Yahoo Finance

        Args:
            interval (str): Data interval ('1m', '3m', '5m', '15m')

        Returns:
            pd.DataFrame: Latest OHLCV data
        """
        try:
            ticker = yf.Ticker("^NSEI")

            # Fetch last 2 days of data to ensure we have enough
            df = ticker.history(period="2d", interval=interval)

            if df.empty:
                logger.warning(f"No data fetched for interval {interval}")
                return None

            # Clean column names
            df.columns = [col.lower() for col in df.columns]

            # Keep required columns
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            df = df[required_cols]

            return df

        except Exception as e:
            logger.error(f"Error fetching live data: {e}")
            return None

    def update_data_buffers(self):
        """
        Update 3m and 15m data buffers with latest data
        """
        try:
            # Fetch 3-minute data
            data_3m_new = self.fetch_live_data('3m')
            if data_3m_new is not None and not data_3m_new.empty:
                self.data_3m = data_3m_new
                logger.info(f"Updated 3m data: {len(self.data_3m)} candles")

            # Fetch 15-minute data
            data_15m_new = self.fetch_live_data('15m')
            if data_15m_new is not None and not data_15m_new.empty:
                self.data_15m = data_15m_new
                logger.info(f"Updated 15m data: {len(self.data_15m)} candles")

            return True

        except Exception as e:
            logger.error(f"Error updating data buffers: {e}")
            return False

    def calculate_indicators(self):
        """
        Calculate indicators on current data buffers
        """
        try:
            if len(self.data_3m) > 0:
                self.data_3m = Indicators.add_all_indicators(self.data_3m, "3m")

            if len(self.data_15m) > 0:
                self.data_15m = Indicators.add_all_indicators(self.data_15m, "15m")

            logger.debug("Indicators calculated")
            return True

        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
            return False

    def check_for_signal(self):
        """
        Check for new trading signals

        Returns:
            dict: Signal information or None
        """
        try:
            if len(self.data_3m) == 0 or len(self.data_15m) == 0:
                logger.debug("Insufficient data for signal check")
                return None

            # Get latest candles
            latest_3m = self.data_3m.iloc[-1]
            latest_15m = self.data_15m.iloc[-1]

            # Check if this candle was already processed
            current_time = latest_3m.name
            if self.last_signal_time == current_time:
                logger.debug("Already processed this candle")
                return None

            # Determine HTF bias
            htf_bias = self.strategy.determine_htf_bias(latest_15m)

            if htf_bias == 'MIXED':
                logger.debug("HTF bias is MIXED - no trade")
                return None

            # Check for signal
            signal = self.strategy.generate_signal(latest_3m, htf_bias)

            if signal:
                self.last_signal_time = current_time
                logger.info(f"NEW SIGNAL: {signal['type']} at {signal['spot_price']:.2f}")
                return signal

            return None

        except Exception as e:
            logger.error(f"Error checking for signal: {e}")
            return None

    def process_signal(self, signal):
        """
        Process a new signal and send notification

        Args:
            signal (dict): Signal information
        """
        try:
            # Send Telegram notification
            if self.notifier.enabled:
                self.notifier.send_signal(signal)
                logger.info("Signal sent to Telegram")
            else:
                logger.warning("Telegram not configured - signal not sent")

            # Log signal locally
            logger.info(f"""
===========================================
NEW SIGNAL GENERATED
===========================================
Type: {signal['type']}
Spot: {signal['spot_price']:.2f}
Strike: {signal['strike_label']}
Confidence: {signal['confidence']}%
Reason: {signal['reason']}
Time: {signal['timestamp']}
===========================================
            """)

        except Exception as e:
            logger.error(f"Error processing signal: {e}")

    def scan_market(self):
        """
        Main market scanning function
        Called every minute during market hours
        """
        try:
            logger.info("Scanning market...")

            # Update data
            if not self.update_data_buffers():
                logger.error("Failed to update data buffers")
                return

            # Calculate indicators
            if not self.calculate_indicators():
                logger.error("Failed to calculate indicators")
                return

            # Check for signals
            signal = self.check_for_signal()

            if signal:
                self.process_signal(signal)
            else:
                logger.debug("No signal found")

        except Exception as e:
            logger.error(f"Error in market scan: {e}")

    def is_market_hours(self):
        """
        Check if current time is within market hours (IST)

        Returns:
            bool: True if market is open
        """
        now = datetime.now()

        # Check if weekday (0=Monday, 4=Friday)
        if now.weekday() > 4:  # Saturday or Sunday
            return False

        # Market hours: 09:15 - 15:30 IST
        market_open = dtime(9, 15)
        market_close = dtime(15, 30)
        current_time = now.time()

        return market_open <= current_time <= market_close

    def run_scheduled_scan(self):
        """
        Scheduled scan that only runs during market hours
        """
        if self.is_market_hours():
            logger.info("Market is open - running scan")
            self.scan_market()
        else:
            logger.debug("Market is closed - skipping scan")

    def send_startup_notification(self):
        """
        Send notification when bot starts
        """
        if self.notifier.enabled:
            message = """
🤖 <b>TRADING BOT STARTED</b>

✅ Live monitoring active
📊 Scanning NIFTY every minute
⏰ Operating during market hours only

You will receive alerts for:
• New trade signals
• Entry/exit recommendations
• Market status updates

<i>Bot is now running 24/7</i>
            """
            self.notifier.send_message(message.strip())
            logger.info("Startup notification sent")

    def start(self):
        """
        Start the live trading agent
        """
        logger.info("="*50)
        logger.info("STARTING LIVE TRADING AGENT")
        logger.info("="*50)

        self.running = True

        # Send startup notification
        self.send_startup_notification()

        # Schedule market scans every minute
        schedule.every(1).minutes.do(self.run_scheduled_scan)

        # Initial scan
        logger.info("Running initial market scan...")
        self.run_scheduled_scan()

        logger.info("Agent is now running. Press Ctrl+C to stop.")
        logger.info("="*50)

        # Main loop
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nStopping agent...")
            self.stop()

    def stop(self):
        """
        Stop the live trading agent
        """
        self.running = False
        logger.info("Live Trading Agent stopped")

        if self.notifier.enabled:
            message = "⚠️ <b>TRADING BOT STOPPED</b>\n\nLive monitoring is now inactive."
            self.notifier.send_message(message)


def main():
    """
    Main entry point for live trading agent
    """
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                 NIFTY OPTIONS LIVE TRADING AGENT              ║
    ║                                                               ║
    ║  🤖 Autonomous 24/7 market monitoring                        ║
    ║  📊 Real-time signal generation                              ║
    ║  📱 Instant Telegram notifications                           ║
    ║                                                               ║
    ║  This bot will:                                              ║
    ║  • Monitor NIFTY markets every minute                        ║
    ║  • Generate signals based on your strategy                   ║
    ║  • Send alerts to your Telegram                             ║
    ║  • Run automatically during market hours                     ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)

    # Initialize agent
    agent = LiveTradingAgent()

    # Check Telegram configuration
    if not agent.notifier.enabled:
        print("\n⚠️  WARNING: Telegram is not configured!")
        print("You will not receive notifications.")
        print("\nTo enable Telegram:")
        print("1. Run: python3 telegram_notifier.py")
        print("2. Follow the setup instructions")
        print("3. Restart this agent\n")

        response = input("Continue without Telegram? (y/n): ")
        if response.lower() != 'y':
            print("Exiting...")
            return

    # Start the agent
    agent.start()


if __name__ == "__main__":
    main()
