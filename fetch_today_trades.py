"""
Print today's executed Kite Connect trades as JSON.

Used by the trade book update workflow: GitHub Actions runs this with the
KITE_* secrets, get_kite_client() refreshes the access token if needed,
and kite.trades() returns every executed trade for today (IST).

Output: one JSON array on stdout. Consume with `python -m json.tool` or jq.
"""

import json
import logging

from kite_fetcher import get_kite_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def main():
    kite = get_kite_client()
    trades = kite.trades()
    print(json.dumps(trades, indent=2, default=str))
    print(f"TOTAL_TRADES:{len(trades)}")


if __name__ == '__main__':
    main()
