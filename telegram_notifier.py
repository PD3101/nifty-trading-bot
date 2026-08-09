"""
Telegram Notification Module
Sends real-time trade signals and updates to Telegram
"""

import requests
import json
from datetime import datetime
import config


class TelegramNotifier:
    """
    Sends notifications to Telegram
    """

    def __init__(self, bot_token=None, chat_id=None):
        """
        Initialize Telegram notifier

        Args:
            bot_token (str): Telegram bot token (from BotFather)
            chat_id (str): Your Telegram chat ID

        Setup Instructions:
        1. Open Telegram and search for @BotFather
        2. Send /newbot and follow instructions
        3. Copy the bot token you receive
        4. Search for @userinfobot on Telegram
        5. Send /start to get your chat ID
        6. Add both to config.py or pass them here
        """
        self.bot_token = bot_token or getattr(config, 'TELEGRAM_BOT_TOKEN', None)
        self.chat_id = chat_id or getattr(config, 'TELEGRAM_CHAT_ID', None)
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            print("Warning: Telegram notifications disabled (missing bot_token or chat_id)")

    def send_message(self, message, parse_mode='HTML'):
        """
        Send a message to Telegram

        Args:
            message (str): Message text (supports HTML or Markdown)
            parse_mode (str): 'HTML' or 'Markdown'

        Returns:
            bool: True if sent successfully
        """
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        payload = {
            'chat_id': self.chat_id,
            'text': message,
            'parse_mode': parse_mode
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Error sending Telegram message: {e}")
            return False

    def format_signal(self, signal):
        """
        Format a trading signal for Telegram

        Args:
            signal (dict): Signal dictionary from strategy

        Returns:
            str: Formatted HTML message
        """
        # Emoji based on signal type
        if signal['type'] == 'BUY_CALL':
            emoji = "🟢"
            signal_type = "BUY CALL"
        else:
            emoji = "🔴"
            signal_type = "BUY PUT"

        # Format time
        signal_time = signal['timestamp'].strftime("%I:%M %p") if hasattr(signal['timestamp'], 'strftime') else str(signal['timestamp'])

        # Build message (reason split before f-string: backslashes are not
        # allowed in f-string expressions on Python <3.12)
        reason_lines = signal['reason'].replace(' | ', '\n✓ ')
        message = f"""
{emoji} <b>{signal_type} SIGNAL</b>

💰 <b>Spot:</b> {signal['spot_price']:,.2f}
🎯 <b>Strike:</b> {signal['strike_label']}
📊 <b>Confidence:</b> {signal['confidence']}%

<b>📋 Reason:</b>
{reason_lines}

🕐 <b>Time:</b> {signal_time}
"""

        return message.strip()

    def send_signal(self, signal):
        """
        Send a trading signal notification

        Args:
            signal (dict): Signal from strategy

        Returns:
            bool: Success status
        """
        message = self.format_signal(signal)
        return self.send_message(message)

    def send_trade_entry(self, trade):
        """
        Send trade entry notification

        Args:
            trade (Trade): Trade object

        Returns:
            bool: Success status
        """
        emoji = "🟢" if trade.signal['type'] == 'BUY_CALL' else "🔴"

        message = f"""
{emoji} <b>TRADE ENTERED</b>

📍 <b>{trade.signal['type']}</b>
🎯 <b>Strike:</b> {trade.signal['strike_label']}
💵 <b>Entry Price:</b> ₹{trade.entry_price:.2f}
🕐 <b>Time:</b> {trade.entry_time.strftime('%I:%M %p')}
"""
        return self.send_message(message.strip())

    def send_trade_exit(self, trade):
        """
        Send trade exit notification

        Args:
            trade (Trade): Closed trade object

        Returns:
            bool: Success status
        """
        # Emoji based on profit/loss
        if trade.pnl > 0:
            emoji = "✅"
            result = "PROFIT"
        else:
            emoji = "❌"
            result = "LOSS"

        message = f"""
{emoji} <b>TRADE CLOSED - {result}</b>

📍 <b>{trade.signal['type']}</b>
🎯 <b>Strike:</b> {trade.signal['strike_label']}
💵 <b>Entry:</b> ₹{trade.entry_price:.2f}
💰 <b>Exit:</b> ₹{trade.exit_price:.2f}

📊 <b>P&L:</b> ₹{trade.pnl:,.2f} ({trade.pnl_percent:+.2f}%)
📝 <b>Reason:</b> {trade.exit_reason}
🕐 <b>Duration:</b> {trade.exit_time - trade.entry_time}
"""
        return self.send_message(message.strip())

    def send_daily_summary(self, date, trades):
        """
        Send daily performance summary

        Args:
            date (str): Date in 'YYYY-MM-DD' format
            trades (list): List of Trade objects for the day

        Returns:
            bool: Success status
        """
        if not trades:
            return False

        total_trades = len(trades)
        wins = len([t for t in trades if t.pnl > 0])
        losses = len([t for t in trades if t.pnl <= 0])
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        total_pnl = sum(t.pnl for t in trades)
        emoji = "📈" if total_pnl > 0 else "📉"

        message = f"""
{emoji} <b>DAILY SUMMARY - {date}</b>

📊 <b>Trades:</b> {total_trades}
✅ <b>Wins:</b> {wins}
❌ <b>Losses:</b> {losses}
📈 <b>Win Rate:</b> {win_rate:.1f}%

💰 <b>Total P&L:</b> ₹{total_pnl:,.2f}
"""
        return self.send_message(message.strip())

    def send_stop_loss_alert(self, trade, reason):
        """
        Send stop loss hit alert

        Args:
            trade (Trade): Current trade
            reason (str): Stop loss reason

        Returns:
            bool: Success status
        """
        message = f"""
⚠️ <b>STOP LOSS ALERT</b>

📍 <b>{trade.signal['type']}</b>
🎯 <b>Strike:</b> {trade.signal['strike_label']}
❗ <b>Reason:</b> {reason}

Taking exit position...
"""
        return self.send_message(message.strip())

    def send_target_alert(self, trade, target_percent):
        """
        Send target reached alert

        Args:
            trade (Trade): Current trade
            target_percent (float): Target percentage achieved

        Returns:
            bool: Success status
        """
        message = f"""
🎯 <b>TARGET REACHED</b>

📍 <b>{trade.signal['type']}</b>
🎯 <b>Strike:</b> {trade.signal['strike_label']}
📈 <b>Profit:</b> {target_percent:.1f}%

Booking profits...
"""
        return self.send_message(message.strip())

    def test_connection(self):
        """
        Test Telegram connection

        Returns:
            bool: True if connected successfully
        """
        test_message = """
🤖 <b>Telegram Bot Connected!</b>

Your NIFTY Options Trading Bot is now active.

You will receive notifications for:
✓ New trade signals
✓ Trade entries
✓ Trade exits
✓ Stop loss alerts
✓ Target achievements
✓ Daily summaries
"""
        return self.send_message(test_message.strip())


# Setup instructions
SETUP_INSTRUCTIONS = """
=================================================================================
TELEGRAM NOTIFICATION SETUP GUIDE
=================================================================================

Follow these steps to enable Telegram notifications:

STEP 1: Create a Telegram Bot
------------------------------
1. Open Telegram app
2. Search for @BotFather
3. Send /newbot command
4. Choose a name for your bot (e.g., "NIFTY Options Alerts")
5. Choose a username (e.g., "my_nifty_bot")
6. Copy the bot token you receive (looks like: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz)

STEP 2: Get Your Chat ID
-------------------------
1. Search for @userinfobot on Telegram
2. Send /start to this bot
3. Copy your chat ID (a number like: 123456789)

STEP 3: Add to Configuration
-----------------------------
Open config.py and add these lines at the end:

    # Telegram Configuration
    TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
    TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"

STEP 4: Test Connection
------------------------
Run: python telegram_notifier.py

If successful, you'll receive a test message on Telegram!

=================================================================================
TROUBLESHOOTING
=================================================================================

Issue: Not receiving messages
- Make sure you've started a chat with your bot (send /start to your bot)
- Verify bot token and chat ID are correct
- Check your internet connection

Issue: Bot token invalid
- Make sure you copied the complete token from BotFather
- Token should not have spaces or line breaks

=================================================================================
"""


if __name__ == "__main__":
    print(SETUP_INSTRUCTIONS)

    # Test connection
    notifier = TelegramNotifier()

    if notifier.enabled:
        print("\nTesting Telegram connection...")
        success = notifier.test_connection()

        if success:
            print("✓ Connection successful! Check your Telegram.")
        else:
            print("✗ Connection failed. Check your configuration.")
    else:
        print("\n⚠ Telegram not configured yet.")
        print("Follow the setup instructions above.")
