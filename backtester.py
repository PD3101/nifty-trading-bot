"""
Backtesting Engine — v2 (SEBI-RA grade)

Improvements over v1:
  * Options priced with Black-Scholes (option_pricer) using an estimated IV,
    instead of the toy intrinsic+0.3*intrinsic model. Premiums now move with
    spot via delta and decay with time via theta.
  * Full India F&O transaction-cost model (brokerage, STT on sell, exchange,
    stamp, GST, slippage).
  * Real risk metrics: expectancy, profit factor, max drawdown, equity curve.
  * Monte Carlo (bootstrap) on the trade list.
  * Walk-forward out-of-sample folds + parameter-sensitivity grid (overfit check).
  * Regime + liquidity filters (gated).

Run:
    python backtester.py                 # live Kite data (needs creds)
    python backtester.py --mock          # synthetic futures, no creds
    python backtester.py --mock --walkforward
    python backtester.py --mock --sensitivity
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time as dtime

import config
from indicators import Indicators
from strategy import StrategyEngine
from option_pricer import price_option, estimate_iv, option_costs


# ============================================================================
# Synthetic futures data (so the backtester runs without Kite credentials)
# ============================================================================
def generate_synthetic_futures(days=40, seed=42):
    """GBM with slowly-rotating drift → produces trends + pullbacks (entries)."""
    rng = np.random.default_rng(seed)
    start = datetime(2026, 8, 1, 9, 15)
    ts = []
    for d in range(days):
        day = start + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        t = datetime.combine(day, dtime(9, 15))
        end = datetime.combine(day, dtime(15, 30))
        while t <= end:
            ts.append(t)
            t += timedelta(minutes=3)
    n = len(ts)
    close = np.empty(n)
    close[0] = 24500.0
    for i in range(1, n):
        drift = 0.00010 * np.sin(i / 220.0)          # rotating regime
        shock = rng.normal(0, 0.0013)                  # per-3m vol
        close[i] = close[i - 1] * np.exp(drift + shock)
    df = pd.DataFrame(index=pd.DatetimeIndex(ts))
    df["close"] = close
    df["open"] = np.concatenate([[close[0]], close[:-1]])
    hi = np.maximum(df["open"].values, df["close"].values)
    lo = np.minimum(df["open"].values, df["close"].values)
    df["high"] = hi * (1 + np.abs(rng.normal(0, 0.0004, n)))
    df["low"] = lo * (1 - np.abs(rng.normal(0, 0.0004, n)))
    df["volume"] = rng.integers(80_000, 300_000, n).astype(float)
    return df


# ============================================================================
# Trade record
# ============================================================================
class Trade:
    def __init__(self, signal, entry_time, entry_premium, sl_premium,
                 target_1_1, target_1_2, iv, T):
        self.signal = signal
        self.entry_time = entry_time
        self.entry_premium = entry_premium
        self.sl_premium = sl_premium
        self.target_1_1 = target_1_1
        self.target_1_2 = target_1_2
        self.iv = iv
        self.T = T
        self.exit_time = None
        self.exit_premium = None
        self.exit_reason = None
        self.pnl = 0.0
        self.costs = 0.0
        self.status = "OPEN"
        self.partial_booked = False
        self.partial_pnl = 0.0


# ============================================================================
# Backtester
# ============================================================================
class Backtester:
    def __init__(self, start_date=None, end_date=None, mock=False, real_options=None):
        self.start_date = start_date or config.BACKTEST_START_DATE
        self.end_date = end_date or config.BACKTEST_END_DATE
        self.mock = mock
        self.real_options = config.REAL_OPTION_DATA if real_options is None else real_options
        self.strategy = StrategyEngine()
        self.kite = None
        self.option_series_cache = {}   # key -> premium DataFrame | None
        self._bt_start = None
        self._bt_end = None

    # ----------------------------------------------------------------
    def _next_expiry(self, from_date):
        """Next NSE weekly expiry on/after from_date (config.EXPIRY_DAY)."""
        from datetime import date as _date
        d = from_date
        for _ in range(8):
            if d.weekday() == config.EXPIRY_DAY:
                return d
            d += timedelta(days=1)
        return from_date

    def _resolve_option_series(self, opt_type, strike, expiry_date):
        """Fetch + cache the historical premium series for one option contract."""
        suffix = 'CE' if opt_type == 'CALL' else 'PE'
        key = f"{int(strike)}{suffix}_{expiry_date.isoformat()}"
        if key in self.option_series_cache:
            return self.option_series_cache[key]
        # Lazy Kite client (live path only)
        if self.kite is None:
            try:
                from kite_fetcher import get_kite_client
                self.kite = get_kite_client()
            except Exception as e:
                print(f"  [real-options] Kite client unavailable ({e}); using BS proxy.")
                self.kite = False
        if not self.kite:
            self.option_series_cache[key] = None
            return None
        from kite_fetcher import resolve_weekly_option, fetch_option_history
        sym, token = resolve_weekly_option(self.kite, expiry_date, strike, opt_type)
        if not token:
            print(f"  [real-options] could not resolve {sym}; using BS proxy.")
            self.option_series_cache[key] = None
            return None
        series = fetch_option_history(self.kite, token, self._bt_start, self._bt_end)
        self.option_series_cache[key] = series
        if series is None:
            print(f"  [real-options] no history for {sym}; using BS proxy.")
        return series

    def _premium(self, opt_type, strike, spot, T_i, iv_i, ts, real_options):
        """Option premium: real historical if available, else Black-Scholes."""
        if real_options and not self.mock:
            expiry = self._next_expiry(ts.date())
            series = self._resolve_option_series(opt_type, strike, expiry)
            if series is not None and len(series):
                val = series['premium'].asof(ts)
                if val == val and val is not None:   # not NaN
                    return float(val)
        return price_option(spot, strike, T_i, iv_i, opt_type)

    # ----------------------------------------------------------------
    def _load_df(self):
        if self.mock:
            df = generate_synthetic_futures()
            return df[self.start_date:self.end_date] if (self.start_date and self.end_date) else df
        # Live path: real NIFTY futures 3m from Kite
        from kite_fetcher import fetch_3m_data as kite_fetch
        from datetime import datetime as _dt
        start = _dt.strptime(self.start_date, "%Y-%m-%d")
        end = _dt.strptime(self.end_date, "%Y-%m-%d")
        days = (end - start).days
        df = kite_fetch(lookback_days=max(days + 2, 5))
        if df is None or len(df) < 20:
            print("Error: Kite returned no data")
            return None
        return df[self.start_date:self.end_date]

    # ----------------------------------------------------------------
    def _run_on_df(self, df_3m, mult=None, vwma_len=None, real_options=None):
        if df_3m is None or len(df_3m) < 20:
            return None
        real_options = self.real_options if real_options is None else real_options
        self._bt_start = df_3m.index[0]
        self._bt_end = df_3m.index[-1]
        df = Indicators.add_all_indicators(df_3m.copy(), "3m")
        if mult is not None:
            st, direction = Indicators.calculate_supertrend(df, config.SUPERTREND_PERIOD, mult)
            df["3m_supertrend"] = st
            df["3m_supertrend_direction"] = direction
        if vwma_len is not None:
            df["3m_vwma"] = Indicators.calculate_vwma(df, vwma_len)

        lot = config.LOT_SIZE
        # IV series (realized vol of underlying), floored/capped
        ret = df["close"].pct_change().fillna(0.0)
        if config.IV_METHOD == "fixed":
            iv_series = pd.Series(config.IV_FIXED, index=df.index)
        else:
            iv_series = (ret.rolling(config.IV_WINDOW).std() * np.sqrt(252))
            iv_series = iv_series.clip(config.IV_FLOOR, config.IV_CAP).fillna(config.IV_FLOOR)
        # time-to-expiry per bar (theta)
        expiry_dt = df.index[0] + timedelta(days=config.DAYS_TO_EXPIRY)
        days_left = (expiry_dt - df.index).days
        T_series = np.maximum(1, days_left) / 252.0

        # regime baseline for z-score filter
        iv_mean = iv_series.mean()
        iv_std = iv_series.std() or 1e-6

        trades = []
        open_trade = None
        trades_today = 0
        losses_today = 0
        daily_stopped = False
        current_date = None

        for i in range(len(df)):
            row = df.iloc[i]
            t = df.index[i]
            day = t.date()
            if day != current_date:
                current_date = day
                trades_today = 0
                losses_today = 0
                daily_stopped = False

            if not self._in_market_hours(t):
                continue

            close = float(row["close"])
            iv_i = float(iv_series.iloc[i])
            T_i = float(T_series[i])
            opt_type = None

            # ---- manage open trade ----
            if open_trade:
                opt_type = "CALL" if open_trade.signal["type"] == "BUY_CALL" else "PUT"
                cur_prem = self._premium(opt_type, open_trade.signal["recommended_strike"],
                                         close, T_i, iv_i, t, real_options)
                st_level = open_trade.signal["supertrend_level"]
                exit_reason = None
                if open_trade.signal["type"] == "BUY_CALL" and close <= st_level:
                    exit_reason = "Supertrend Stoploss"
                elif open_trade.signal["type"] == "BUY_PUT" and close >= st_level:
                    exit_reason = "Supertrend Stoploss"
                if not exit_reason and cur_prem >= open_trade.target_1_2:
                    exit_reason = "Target 1:2 RR"
                if (not exit_reason and config.HYBRID_EXIT_ENABLED
                        and not open_trade.partial_booked
                        and cur_prem >= open_trade.target_1_1):
                    open_trade.partial_pnl = (cur_prem - open_trade.entry_premium) * 0.5 * lot
                    open_trade.partial_booked = True
                if exit_reason:
                    cost, _ = option_costs(open_trade.entry_premium, cur_prem, lot)
                    pnl_full = (cur_prem - open_trade.entry_premium) * lot
                    pnl = open_trade.partial_pnl + pnl_full * 0.5 - cost
                    open_trade.exit_time = t
                    open_trade.exit_premium = cur_prem
                    open_trade.exit_reason = exit_reason
                    open_trade.pnl = pnl
                    open_trade.costs = cost
                    open_trade.status = "CLOSED"
                    trades.append(open_trade)
                    trades_today += 1
                    if pnl < 0:
                        losses_today += 1
                    open_trade = None
                    if (trades_today >= config.MAX_TRADES_PER_DAY
                            or losses_today >= config.MAX_LOSSES_PER_DAY):
                        daily_stopped = True
                continue

            # ---- look for new entry ----
            if daily_stopped:
                continue

            # Regime filter (gated)
            if config.REGIME_FILTER_ENABLED:
                z = (iv_i - iv_mean) / iv_std
                if z > config.REGIME_VOL_ZSCORE:
                    continue

            spot = close
            signal = self.strategy.generate_signal(row, df, i, spot_price=spot)
            if not signal:
                continue

            opt_type = "CALL" if signal["type"] == "BUY_CALL" else "PUT"
            entry_prem = self._premium(opt_type, signal["recommended_strike"], spot, T_i, iv_i, t, real_options)
            sl_prem = self._premium(opt_type, signal["recommended_strike"], signal["supertrend_level"], T_i, iv_i, t, real_options)
            risk = entry_prem - sl_prem
            if risk <= 0:
                continue
            # Liquidity filter (gated)
            if config.LIQUIDITY_FILTER_ENABLED and entry_prem < config.MIN_PREMIUM:
                continue
            target_1_1 = entry_prem + risk
            target_1_2 = entry_prem + 2 * risk
            open_trade = Trade(signal, t, entry_prem, sl_prem, target_1_1, target_1_2, iv_i, T_i)

        # close any open trade at end
        if open_trade:
            last = df.iloc[-1]
            close = float(last["close"])
            iv_i = float(iv_series.iloc[-1]); T_i = float(T_series[-1])
            opt_type = "CALL" if open_trade.signal["type"] == "BUY_CALL" else "PUT"
            ep = self._premium(opt_type, open_trade.signal["recommended_strike"], close, T_i, iv_i, df.index[-1], real_options)
            cost, _ = option_costs(open_trade.entry_premium, ep, lot)
            pnl_full = (ep - open_trade.entry_premium) * lot
            pnl = open_trade.partial_pnl + pnl_full * 0.5 - cost
            open_trade.exit_time = df.index[-1]
            open_trade.exit_premium = ep
            open_trade.exit_reason = "End of Backtest"
            open_trade.pnl = pnl
            open_trade.costs = cost
            open_trade.status = "CLOSED"
            trades.append(open_trade)

        return self._metrics(trades)

    # ----------------------------------------------------------------
    def _metrics(self, trades):
        if not trades:
            return {"trades": [], "num_trades": 0, "equity": [], "expectancy": 0.0,
                    "win_rate": 0.0, "profit_factor": 0.0, "max_dd": 0.0,
                    "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
        pnls = np.array([t.pnl for t in trades])
        equity = np.cumsum(pnls)
        peak = np.maximum.accumulate(equity)
        dd = equity - peak
        max_dd = float(dd.min()) if len(dd) else 0.0
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        win_rate = len(wins) / len(pnls) * 100
        pf = float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else (float("inf") if wins.sum() > 0 else 0.0)
        return {
            "trades": trades,
            "num_trades": len(pnls),
            "equity": equity.tolist(),
            "expectancy": float(pnls.mean()),
            "win_rate": win_rate,
            "profit_factor": pf,
            "max_dd": max_dd,
            "total_pnl": float(pnls.sum()),
            "avg_win": float(wins.mean()) if len(wins) else 0.0,
            "avg_loss": float(losses.mean()) if len(losses) else 0.0,
            "monte_carlo": self._monte_carlo(pnls),
        }

    # ----------------------------------------------------------------
    def _monte_carlo(self, pnls, runs=None):
        runs = runs or config.MONTE_CARLO_RUNS
        n = len(pnls)
        if n == 0:
            return {}
        rng = np.random.default_rng(7)
        totals = np.empty(runs)
        dds = np.empty(runs)
        for r in range(runs):
            sample = rng.choice(pnls, size=n, replace=True)
            eq = np.cumsum(sample)
            peak = np.maximum.accumulate(eq)
            dds[r] = (eq - peak).min()
            totals[r] = eq[-1]
        exps = totals / n
        return {
            "prob_profitable": float((totals > 0).mean() * 100),
            "expectancy_p5": float(np.percentile(exps, 5)),
            "expectancy_p95": float(np.percentile(exps, 95)),
            "worst_dd_p5": float(np.percentile(dds, 5)),
        }

    # ----------------------------------------------------------------
    def _in_market_hours(self, dt):
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            from datetime import timezone, timedelta as td
            dt = dt.astimezone(timezone(td(hours=5, minutes=30)))
        t = dt.time() if hasattr(dt, "time") else None
        if t is None:
            return False
        mo, mc = dtime(9, 45), dtime(15, 30)
        lunch_s, lunch_e = dtime(12, 30), dtime(14, 0)
        if mo <= t <= mc:
            if lunch_s <= t <= lunch_e:
                return False
            return True
        return False

    # ----------------------------------------------------------------
    def run_backtest(self):
        print("\n" + "=" * 80)
        print("BACKTEST (v2 — BS pricing + costs)")
        print(f"Period: {self.start_date} to {self.end_date}  mock={self.mock}")
        print("=" * 80)
        df = self._load_df()
        res = self._run_on_df(df)
        if res is None or res["num_trades"] == 0:
            print("No trades executed.")
            return res
        self._print(res, "FULL SAMPLE")
        return res

    def walk_forward(self):
        df = self._load_df()
        if df is None:
            return
        folds = config.WALK_FORWARD_FOLDS
        print(f"\n{'=' * 80}\nWALK-FORWARD (rolling out-of-sample, {folds} folds)\n{'=' * 80}")
        # split by date into contiguous folds
        dates = df.index
        boundaries = [dates[int(k * len(dates) / folds)] for k in range(1, folds)]
        prev = dates[0]
        for f in range(folds):
            end = boundaries[f] if f < folds - 1 else dates[-1]
            fold_df = df.loc[(df.index >= prev) & (df.index <= end)]
            res = self._run_on_df(fold_df)
            prev = end
            tag = f"FOLD {f+1}"
            if res and res["num_trades"]:
                self._print(res, tag)
            else:
                print(f"  {tag}: no trades")

    def parameter_sensitivity(self):
        df = self._load_df()
        if df is None:
            return
        print(f"\n{'=' * 80}\nPARAMETER SENSITIVITY (overfit check)\n{'=' * 80}")
        print(f"  {'mult':>5} {'vwma':>5} {'trades':>6} {'PF':>7} {'exp':>10} {'maxDD':>10}")
        for mult in config.PARAM_SWEEP_MULT:
            for vwma in config.PARAM_SWEEP_VWMA:
                res = self._run_on_df(df, mult=mult, vwma_len=vwma)
                if res and res["num_trades"]:
                    pf = res["profit_factor"]
                    pf_s = f"{pf:.2f}" if np.isfinite(pf) else "inf"
                    print(f"  {mult:>5} {vwma:>5} {res['num_trades']:>6} {pf_s:>7} "
                          f"{res['expectancy']:>10.1f} {res['max_dd']:>10.1f}")
                else:
                    print(f"  {mult:>5} {vwma:>5} {'0':>6} {'-':>7} {'-':>10} {'-':>10}")

    # ----------------------------------------------------------------
    def _print(self, res, tag):
        pf = res["profit_factor"]
        pf_s = f"{pf:.2f}" if np.isfinite(pf) else "inf"
        mc = res.get("monte_carlo", {})
        print(f"\n--- {tag} ---")
        print(f"  Trades         : {res['num_trades']}")
        print(f"  Win rate       : {res['win_rate']:.1f}%")
        print(f"  Expectancy/trade: ₹{res['expectancy']:,.1f}")
        print(f"  Total P&L      : ₹{res['total_pnl']:,.1f}")
        print(f"  Avg win / loss : ₹{res['avg_win']:,.1f} / ₹{res['avg_loss']:,.1f}")
        print(f"  Profit factor  : {pf_s}")
        print(f"  Max drawdown   : ₹{res['max_dd']:,.1f}")
        if mc:
            print(f"  Monte Carlo    : P(profitable)={mc['prob_profitable']:.0f}%  "
                  f"exp 5–95% ₹{mc['expectancy_p5']:,.0f}–{mc['expectancy_p95']:,.0f}  "
                  f"worstDD 5% ₹{mc['worst_dd_p5']:,.0f}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--real-options", action="store_true",
                    help="Price trades from real Kite option historical data (needs creds + historical API)")
    ap.add_argument("--walkforward", action="store_true")
    ap.add_argument("--sensitivity", action="store_true")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    args = ap.parse_args()

    bt = Backtester(start_date=args.start, end_date=args.end, mock=args.mock,
                    real_options=args.real_options)
    bt.run_backtest()
    if args.walkforward:
        bt.walk_forward()
    if args.sensitivity:
        bt.parameter_sensitivity()
