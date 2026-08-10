"""
Chain the next GitHub Actions workflow run during market hours.

Called at the end of each trade-bot run. Triggers a workflow_dispatch
for the next scan in ~5 minutes, bypassing GitHub's unreliable schedule cron.

How it works:
  - Each trade-bot run calls this script at the very end.
  - If IST is within 08:25–15:30 on a weekday, it POSTs to the GitHub
    Actions API to trigger the next run.
  - The schedule cron (*/5 4-9) stays as a fallback bootstrap only.
  - Early runs (before 09:15) exit via can_trade_now() but keep the
    chain alive so the first real scan fires on time.
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
# Chain starts at 08:25 IST (pre-market bootstrap) and runs until market close.
# Early runs exit via can_trade_now() but keep the chain alive so the first
# real scan fires on time at 09:15.
CHAIN_START = dtime(8, 25)
MARKET_CLOSE = dtime(15, 30)


def should_chain():
    """Return True if we're within market hours on a weekday."""
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    return CHAIN_START <= now.time() <= MARKET_CLOSE


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
