"""
Main Runner Script
Entry point for the NIFTY Options Backtesting System
"""

import argparse
import sys
from datetime import datetime

from backtester import Backtester
from telegram_notifier import TelegramNotifier
import config


def run_backtest(start_date=None, end_date=None, notify=False):
    """
    Run backtest and optionally send results to Telegram

    Args:
        start_date (str): Start date in 'YYYY-MM-DD' format
        end_date (str): End date in 'YYYY-MM-DD' format
        notify (bool): Send results to Telegram

    Returns:
        dict: Backtest results
    """
    print("\n" + "="*80)
    print("NIFTY OPTIONS BACKTESTING SYSTEM")
    print("="*80)

    # Initialize backtester
    backtester = Backtester(start_date, end_date)

    # Run backtest
    results = backtester.run_backtest()

    if not results:
        print("\n✗ Backtest failed")
        return None

    # Send to Telegram if enabled
    if notify:
        notifier = TelegramNotifier()
        if notifier.enabled:
            print("\nSending results to Telegram...")

            # Send summary
            summary_msg = f"""
📊 <b>BACKTEST COMPLETED</b>

📅 Period: {start_date} to {end_date}

📈 <b>Results:</b>
• Total Trades: {results['total_trades']}
• Win Rate: {results['win_rate']:.2f}%
• Total P&L: ₹{results['total_pnl']:,.2f}

✅ Wins: {results['winning_trades']}
❌ Losses: {results['losing_trades']}

📊 Avg Win: ₹{results['avg_win']:,.2f}
📉 Avg Loss: ₹{results['avg_loss']:,.2f}

🟢 CALL: {results['call_trades']} trades ({results['call_win_rate']:.1f}% win rate)
🔴 PUT: {results['put_trades']} trades ({results['put_win_rate']:.1f}% win rate)
"""
            notifier.send_message(summary_msg.strip())
            print("✓ Results sent to Telegram")

    return results


def run_dashboard():
    """
    Launch the Streamlit dashboard
    """
    import subprocess
    import os

    print("\n" + "="*80)
    print("LAUNCHING DASHBOARD")
    print("="*80)
    print("\nStarting Streamlit dashboard...")
    print("Dashboard will open in your browser automatically.")
    print("Press Ctrl+C to stop.\n")

    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", "dashboard.py"
        ])
    except KeyboardInterrupt:
        print("\n\nDashboard stopped.")
    except Exception as e:
        print(f"\nError launching dashboard: {e}")
        print("\nTry running manually:")
        print("  streamlit run dashboard.py")


def test_telegram():
    """
    Test Telegram connection
    """
    print("\n" + "="*80)
    print("TESTING TELEGRAM CONNECTION")
    print("="*80)

    notifier = TelegramNotifier()

    if not notifier.enabled:
        print("\n⚠ Telegram not configured.")
        print("\nTo enable Telegram notifications:")
        print("1. Run: python telegram_notifier.py")
        print("2. Follow the setup instructions")
        return

    print("\nSending test message...")
    success = notifier.test_connection()

    if success:
        print("✓ Test message sent! Check your Telegram.")
    else:
        print("✗ Failed to send message. Check your configuration.")


def main():
    """
    Main entry point
    """
    parser = argparse.ArgumentParser(
        description='NIFTY Options Backtesting System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run backtest with default dates
  python main.py backtest

  # Run backtest with custom dates
  python main.py backtest --start 2024-01-01 --end 2024-12-31

  # Run backtest and send results to Telegram
  python main.py backtest --notify

  # Launch dashboard
  python main.py dashboard

  # Test Telegram connection
  python main.py test-telegram
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Backtest command
    backtest_parser = subparsers.add_parser('backtest', help='Run backtest')
    backtest_parser.add_argument(
        '--start',
        type=str,
        default=config.BACKTEST_START_DATE,
        help=f'Start date (YYYY-MM-DD), default: {config.BACKTEST_START_DATE}'
    )
    backtest_parser.add_argument(
        '--end',
        type=str,
        default=config.BACKTEST_END_DATE,
        help=f'End date (YYYY-MM-DD), default: {config.BACKTEST_END_DATE}'
    )
    backtest_parser.add_argument(
        '--notify',
        action='store_true',
        help='Send results to Telegram'
    )

    # Dashboard command
    subparsers.add_parser('dashboard', help='Launch interactive dashboard')

    # Test Telegram command
    subparsers.add_parser('test-telegram', help='Test Telegram connection')

    args = parser.parse_args()

    if args.command == 'backtest':
        run_backtest(args.start, args.end, args.notify)

    elif args.command == 'dashboard':
        run_dashboard()

    elif args.command == 'test-telegram':
        test_telegram()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
