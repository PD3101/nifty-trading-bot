"""
Market Timing and Holiday Management
Strict market hours enforcement and NSE holiday checking
"""

import pytz
from datetime import datetime, time as dtime, timedelta
import requests
import logging

logger = logging.getLogger(__name__)


class MarketTimingManager:
    """
    Manages market hours, holidays, and trading time restrictions
    """

    def __init__(self):
        """Initialize market timing manager"""
        self.ist = pytz.timezone('Asia/Kolkata')

        # NSE Trading Hours
        self.market_open = dtime(9, 15)   # 9:15 AM IST
        self.market_close = dtime(15, 30) # 3:30 PM IST
        self.trading_start = dtime(9, 45) # 9:45 AM IST - First trade allowed

        # NSE Holidays 2026 (approximate - update with official calendar)
        self.holidays_2026 = [
            '2026-01-26',  # Republic Day
            '2026-03-14',  # Holi
            '2026-04-02',  # Ram Navami
            '2026-04-10',  # Mahavir Jayanti
            '2026-04-14',  # Dr. Ambedkar Jayanti
            '2026-05-01',  # Maharashtra Day
            '2026-08-15',  # Independence Day
            '2026-10-02',  # Gandhi Jayanti
            '2026-10-24',  # Dussehra
            '2026-11-13',  # Diwali
            '2026-11-14',  # Diwali
            '2026-12-25',  # Christmas
        ]

        logger.info("Market timing manager initialized")

    def get_ist_time(self):
        """
        Get current time in IST

        Returns:
            datetime: Current IST datetime
        """
        return datetime.now(self.ist)

    def is_weekday(self, dt=None):
        """
        Check if given date is a weekday (Monday-Friday)

        Args:
            dt (datetime): Date to check (default: now)

        Returns:
            bool: True if Monday-Friday
        """
        if dt is None:
            dt = self.get_ist_time()

        # 0 = Monday, 4 = Friday, 5 = Saturday, 6 = Sunday
        return dt.weekday() < 5

    def is_holiday(self, dt=None):
        """
        Check if given date is an NSE holiday

        Args:
            dt (datetime): Date to check (default: today)

        Returns:
            bool: True if holiday
        """
        if dt is None:
            dt = self.get_ist_time()

        date_str = dt.strftime('%Y-%m-%d')
        return date_str in self.holidays_2026

    def is_market_open(self, dt=None):
        """
        Check if market is currently open

        Args:
            dt (datetime): Time to check (default: now)

        Returns:
            bool: True if market is open
        """
        if dt is None:
            dt = self.get_ist_time()

        # Check if weekday
        if not self.is_weekday(dt):
            logger.debug(f"Market closed: Weekend ({dt.strftime('%A')})")
            return False

        # Check if holiday
        if self.is_holiday(dt):
            logger.debug(f"Market closed: Holiday ({dt.strftime('%Y-%m-%d')})")
            return False

        # Check time
        current_time = dt.time()
        if self.market_open <= current_time <= self.market_close:
            return True

        logger.debug(f"Market closed: Outside trading hours ({current_time})")
        return False

    def can_trade_now(self, dt=None):
        """
        Check if trading is allowed now
        Market must be open AND time must be after 9:45 AM

        Args:
            dt (datetime): Time to check (default: now)

        Returns:
            bool: True if can trade
        """
        if dt is None:
            dt = self.get_ist_time()

        # Market must be open
        if not self.is_market_open(dt):
            return False

        # Time must be after 9:45 AM (no trades in first 30 minutes)
        current_time = dt.time()
        if current_time < self.trading_start:
            logger.debug(f"Trading not allowed yet: Before 9:45 AM (current: {current_time})")
            return False

        return True

    def time_until_market_open(self):
        """
        Calculate time until next market open

        Returns:
            str: Human-readable time until market open
        """
        now = self.get_ist_time()

        # If market is open now
        if self.is_market_open(now):
            return "Market is currently open"

        # Find next market open
        current_date = now.date()
        current_time = now.time()

        # If today is a trading day and before market open
        if self.is_weekday(now) and not self.is_holiday(now):
            if current_time < self.market_open:
                market_open_today = now.replace(
                    hour=self.market_open.hour,
                    minute=self.market_open.minute,
                    second=0,
                    microsecond=0
                )
                delta = market_open_today - now
                hours = delta.seconds // 3600
                minutes = (delta.seconds % 3600) // 60
                return f"Market opens in {hours}h {minutes}m"

        # Otherwise, find next weekday
        days_ahead = 1
        while days_ahead < 7:
            next_date = now + timedelta(days=days_ahead)

            if self.is_weekday(next_date) and not self.is_holiday(next_date):
                next_open = next_date.replace(
                    hour=self.market_open.hour,
                    minute=self.market_open.minute,
                    second=0,
                    microsecond=0
                )
                delta = next_open - now
                days = delta.days
                hours = delta.seconds // 3600

                if days == 0:
                    return f"Market opens in {hours} hours"
                elif days == 1:
                    return f"Market opens tomorrow at 9:15 AM IST"
                else:
                    return f"Market opens in {days} days ({next_open.strftime('%A, %b %d')})"

            days_ahead += 1

        return "Next market open not found"

    def time_until_trading_allowed(self):
        """
        Calculate time until trading is allowed (9:45 AM)

        Returns:
            str: Human-readable time until 9:45 AM
        """
        now = self.get_ist_time()

        if self.can_trade_now(now):
            return "Trading is allowed now"

        if not self.is_market_open(now):
            return self.time_until_market_open()

        # Market is open but before 9:45 AM
        if now.time() < self.trading_start:
            trading_start_today = now.replace(
                hour=self.trading_start.hour,
                minute=self.trading_start.minute,
                second=0,
                microsecond=0
            )
            delta = trading_start_today - now
            minutes = delta.seconds // 60
            return f"Trading starts in {minutes} minutes (at 9:45 AM)"

        return "Trading not allowed"

    def get_market_status(self):
        """
        Get detailed market status

        Returns:
            dict: Market status information
        """
        now = self.get_ist_time()

        status = {
            'current_time_ist': now.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'is_weekday': self.is_weekday(now),
            'is_holiday': self.is_holiday(now),
            'is_market_open': self.is_market_open(now),
            'can_trade': self.can_trade_now(now),
            'market_opens_at': '9:15 AM IST',
            'trading_starts_at': '9:45 AM IST',
            'market_closes_at': '3:30 PM IST',
            'time_until_open': self.time_until_market_open(),
            'time_until_trading': self.time_until_trading_allowed()
        }

        return status


def test_market_timing():
    """Test market timing manager"""
    print("Testing Market Timing Manager...")
    print("="*60)

    manager = MarketTimingManager()

    # Get current status
    status = manager.get_market_status()

    print(f"\nCurrent Time (IST): {status['current_time_ist']}")
    print(f"Weekday: {'Yes' if status['is_weekday'] else 'No (Weekend)'}")
    print(f"Holiday: {'Yes' if status['is_holiday'] else 'No'}")
    print(f"Market Open: {'Yes ✓' if status['is_market_open'] else 'No ✗'}")
    print(f"Trading Allowed: {'Yes ✓' if status['can_trade'] else 'No ✗'}")
    print(f"\n{status['time_until_open']}")
    print(f"{status['time_until_trading']}")

    print("\n" + "="*60)
    print(f"Market Hours: {status['market_opens_at']} - {status['market_closes_at']}")
    print(f"First Trade Allowed: {status['trading_starts_at']}")
    print("="*60)


if __name__ == "__main__":
    test_market_timing()
