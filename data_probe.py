"""Probe how far back Kite serves NIFTY 50 SPOT 3-minute history.

Run on GitHub Actions (has Kite creds). Prints row counts per year so we know
the maximal feasible backtest window. No trading logic.
"""
from kite_fetcher import get_kite_client, _resolve_nifty_spot_token


def main():
    kite = get_kite_client()
    tok = _resolve_nifty_spot_token(kite)
    print(f"SPOT token = {tok}")
    for y in [2021, 2022, 2023, 2024, 2025, 2026]:
        try:
            candles = kite.historical_data(
                instrument_token=tok,
                from_date=f"{y}-01-01",
                to_date=f"{y}-12-31",
                interval="3minute",
            )
            n = len(candles) if candles else 0
            first = candles[0]['date'] if n else "n/a"
            last = candles[-1]['date'] if n else "n/a"
            print(f"{y}: rows={n} first={first} last={last}")
        except Exception as e:
            print(f"{y}: ERR {str(e)[:160]}")


if __name__ == "__main__":
    main()
