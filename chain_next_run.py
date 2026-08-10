"""
Chain the next GitHub Actions workflow run during market hours.

Called at the end of each trade-bot run. Triggers a workflow_dispatch
for the next scan in ~5 minutes, bypassing GitHub's unreliable schedule cron.

How it works:
  - Each trade-bot run calls this script at the very end.
  - If IST is within market hours (09:15–15:30) on a weekday,
    it POSTs to the GitHub Actions API to trigger the next run.
  - The schedule cron (*/5 4-9) stays as a fallback bootstrap only.
"""

import json
import logging
from datetime import datetime, time as dtime
from urllib.request import Request, urlopen
from urllib.error import URLError

import pytz

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger('chain')

IST = pytz.timezone('Asia/Kolkata')
MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)


def should_chain():
    """Return True if we're within market hours on a weekday."""
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def chain_next_run():
    """Trigger a workflow_dispatch for the trade-bot workflow."""
    import os

    token = os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY')

    if not token or not repo:
        logger.info("Not in GitHub Actions — skipping chain")
        return

    url = (
        f'https://api.github.com/repos/{repo}'
        f'/actions/workflows/trade_bot.yml/dispatches'
    )
    data = json.dumps({'ref': 'main'}).encode('utf-8')
    req = Request(url, data=data, headers={
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'nifty-trade-bot',
    })

    try:
        resp = urlopen(req)
        if resp.status == 204:
            logger.info("Next run scheduled (~5 min)")
        else:
            logger.warning(f"Unexpected status: {resp.status}")
    except URLError as e:
        logger.warning(f"Chain failed: {e}")
    except Exception as e:
        logger.warning(f"Chain error: {e}")


if __name__ == '__main__':
    if should_chain():
        chain_next_run()
    else:
        logger.info("Outside market hours — no chain")
