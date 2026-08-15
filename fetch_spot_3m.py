"""
Fetch NIFTY 50 SPOT 3-minute history from Kite in <=90-day chunks
(Kite rejects spans >100 days) and write a single CSV for backtesting.

Run on GitHub Actions (has Kite creds). Output: spot_3m.csv
(columns: date, open, high, low, close, volume), IST timestamps.
"""
import argparse
import datetime as dt
import sys

import pandas as pd
from kite_fetcher import get_kite_client, _resolve_nifty_spot_token


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2021-01-01')
    ap.add_argument('--end', default=None)          # None -> today
    ap.add_argument('--chunk', type=int, default=90)
    ap.add_argument('--out', default='spot_3m.csv')
    args = ap.parse_args()

    kite = get_kite_client()
    tok = _resolve_nifty_spot_token(kite)
    print(f"SPOT token = {tok}")

    start = dt.datetime.strptime(args.start, '%Y-%m-%d').date()
    end = (dt.datetime.now().date() if args.end is None
           else dt.datetime.strptime(args.end, '%Y-%m-%d').date())
    print(f"Fetching 3m SPOT from {start} to {end} in {args.chunk}-day chunks")

    frames = []
    cur = start
    calls = 0
    while cur <= end:
        nxt = min(cur + dt.timedelta(days=args.chunk), end)
        try:
            candles = kite.historical_data(
                instrument_token=tok,
                from_date=cur.strftime('%Y-%m-%d'),
                to_date=nxt.strftime('%Y-%m-%d'),
                interval='3minute')
            if candles:
                frames.append(pd.DataFrame(candles))
                print(f"  {cur}..{nxt}: {len(candles)} rows")
            else:
                print(f"  {cur}..{nxt}: 0 rows")
        except Exception as e:
            print(f"  {cur}..{nxt}: ERR {str(e)[:120]}")
        cur = nxt + dt.timedelta(days=1)
        calls += 1

    if not frames:
        print("NO DATA returned — abort")
        sys.exit(1)

    df = pd.concat(frames, ignore_index=True)
    df['date'] = pd.to_datetime(df['date'])
    df = df.drop_duplicates(subset=['date']).sort_values('date')
    df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
    df.to_csv(args.out, index=False)
    print(f"WROTE {len(df)} rows -> {args.out}")
    print(f"  earliest: {df['date'].iloc[0]}")
    print(f"  latest:   {df['date'].iloc[-1]}")


if __name__ == '__main__':
    main()
