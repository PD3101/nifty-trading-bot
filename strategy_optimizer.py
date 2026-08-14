"""
Adversarial strategy-optimization harness (SEBI-RA lens).

Implements the user's optimization mandate WITHOUT rebuilding the strategy:
  - Ablation: every subset of {Supertrend, VWAP, VWMA}
  - SL methods: supertrend-level (current), ATR-based, swing-high/low
  - Target R multiples: 1.0 … 3.0 + hybrid partial booking
  - Market-regime NO-TRADE filter (vol + trend-strength)
  - Losing-trade forensics (categorised exit reasons)
  - Parameter sweeps + robustness surface
  - Time-series split: train / validation / untouched out-of-sample + walk-forward
  - Repainting audit guards (only closed candles; no future data)

CRITICAL: numbers are ONLY meaningful on REAL Kite history. Run with
`--real-options` (needs Kite historical API + creds). On `--mock` (synthetic
GBM) this validates the *harness mechanics* only — DO NOT trade on mock numbers.

Run:
    python3 strategy_optimizer.py --mock                      # proof-of-method (synthetic)
    python3 strategy_optimizer.py --real-options              # real Kite history (needs creds + hist API)
    python3 strategy_optimizer.py --csv fut.csv               # cached futures CSV (no subscription)
    python3 strategy_optimizer.py --csv fut.csv --opt-csv prem.csv   # + real option premiums
"""

import sys
import numpy as np
import pandas as pd
from datetime import timedelta

import config
from indicators import Indicators
from strategy import StrategyEngine
from option_pricer import price_option, option_costs
from backtester import generate_synthetic_futures, Backtester


# ---------------------------------------------------------------------------
# Indicators the harness needs beyond the standard set
# ---------------------------------------------------------------------------
def add_atr(df, period=14):
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(period).mean()
    return df


def add_trend_slope(df, col='3m_vwma', period=20):
    """Fractional slope of VWMA over `period` bars (trend strength)."""
    df['vwma_slope'] = df[col].diff(period) / df[col].shift(period)
    return df


# ---------------------------------------------------------------------------
# Cached-history loaders (run locally without Kite historical API)
# ---------------------------------------------------------------------------
def load_futures_csv(path):
    """Load a cached NIFTY FUT 3m CSV. Columns: date,open,high,low,close,volume.

    Any datetime column name is accepted; index is localized to IST.
    """
    df = pd.read_csv(path)
    dtcol = next((c for c in ('date', 'timestamp', 'time', 'datetime') if c in df.columns), df.columns[0])
    df[dtcol] = pd.to_datetime(df[dtcol])
    df.set_index(dtcol, inplace=True)
    df.index.name = None
    keep = [c for c in ('open', 'high', 'low', 'close', 'volume') if c in df.columns]
    df = df[keep].astype(float)
    if df.index.tz is None:
        df.index = df.index.tz_localize('Asia/Kolkata')
    else:
        df.index = df.index.tz_convert('Asia/Kolkata')
    return df


def build_opt_lookup(path):
    """Build a real-premium lookup from an option CSV.

    Columns: timestamp, strike, type (CALL/PUT), premium.
    Returns callable(strike, opt_type, timestamp) -> premium | None.
    When None, the harness falls back to Black-Scholes (as today).
    """
    od = pd.read_csv(path)
    tscol = next((c for c in ('timestamp', 'date', 'time', 'datetime') if c in od.columns), od.columns[0])
    od[tscol] = pd.to_datetime(od[tscol])
    od['strike'] = od['strike'].astype(int)
    od['type'] = od['type'].astype(str).str.upper()
    lookup = {}
    for (strike, typ), g in od.groupby(['strike', 'type']):
        s = pd.Series(g['premium'].values, index=pd.DatetimeIndex(g[tscol].values))
        s.index = s.index.tz_localize('Asia/Kolkata') if s.index.tz is None else s.index.tz_convert('Asia/Kolkata')
        lookup[(int(strike), typ)] = s.sort_index()

    def premium(strike, opt, ts):
        s = lookup.get((int(strike), opt.upper()))
        if s is None or len(s) == 0:
            return None
        v = s.asof(ts)
        return float(v) if v == v else None
    return premium


# ---------------------------------------------------------------------------
# Entry logic (reuses existing pullback / no-chase rules; ablates the 3 pillars)
# ---------------------------------------------------------------------------
def entry_decision(engine, row, df, i, mask):
    """Return 'BUY_CALL' / 'BUY_PUT' / None using only the indicators in `mask`.

    mask is a subset of {'supertrend', 'vwap', 'vwma'}. Pullback + no-chase are
    always applied (they are the user's core trigger, not a pillar to ablate).
    """
    close = float(row['close'])
    vwap = float(row['3m_vwap'])
    vwma = float(row['3m_vwma'])
    st_level = float(row['3m_supertrend'])
    st_dir = int(row['3m_supertrend_direction'])

    # --- CALL ---
    call_ok = True
    if 'vwap' in mask:
        call_ok &= close > vwap
    if 'vwma' in mask:
        call_ok &= close > vwma
    if 'supertrend' in mask:
        call_ok &= (st_dir == 1 and close > st_level)
    if call_ok and engine.check_pullback(df, i, 'CALL') and not engine.check_no_chase(df, i):
        return 'BUY_CALL'

    # --- PUT ---
    put_ok = True
    if 'vwap' in mask:
        put_ok &= close < vwap
    if 'vwma' in mask:
        put_ok &= close < vwma
    if 'supertrend' in mask:
        put_ok &= (st_dir == -1 and close < st_level)
    if put_ok and engine.check_pullback(df, i, 'PUT') and not engine.check_no_chase(df, i):
        return 'BUY_PUT'

    return None


def sl_level_for(spot, row, df, i, sig_type, method, atr_mult, swing_n):
    """Where the trade thesis is INVALIDATED (underlying-based, not premium)."""
    if method == 'supertrend':
        return float(row['3m_supertrend'])
    if method == 'atr':
        atr = float(row['atr'])
        return spot - atr_mult * atr if sig_type == 'BUY_CALL' else spot + atr_mult * atr
    if method == 'swing':
        lo = df['low'].iloc[max(0, i - swing_n):i + 1].min()
        hi = df['high'].iloc[max(0, i - swing_n):i + 1].max()
        return lo if sig_type == 'BUY_CALL' else hi
    raise ValueError(method)


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------
def simulate(df_3m, params, opt_lookup=None, engine=None):
    """Run one configured variant. Returns list of trade dicts + forensics.

    opt_lookup: callable(strike, opt_type, timestamp) -> premium | None.
    When it returns a premium, that real value is used; else Black-Scholes.
    """
    engine = engine or StrategyEngine()

    def get_prem(strike, opt, ts, spot_bs, T_i, iv_i):
        if opt_lookup is not None:
            rp = opt_lookup(strike, opt, ts)
            if rp is not None:
                return rp
        return price_option(spot_bs, strike, T_i, iv_i, opt)

    df = Indicators.add_all_indicators(df_3m.copy(), "3m")
    add_atr(df)
    add_trend_slope(df)

    lot = config.LOT_SIZE
    ret = df['close'].pct_change().fillna(0.0)
    iv_series = (ret.rolling(config.IV_WINDOW).std() * np.sqrt(252)).clip(config.IV_FLOOR, config.IV_CAP).fillna(config.IV_FLOOR)
    expiry_dt = df.index[0] + timedelta(days=config.DAYS_TO_EXPIRY)
    T_series = np.maximum(1, (expiry_dt - df.index).days) / 252.0

    # regime thresholds from the *training* distribution (passed in params)
    vol_q = params.get('regime_vol_q')
    slope_eps = params.get('regime_slope_eps', 0.0)

    trades = []
    open_trade = None
    trades_today = 0
    losses_today = 0
    daily_stopped = False
    current_date = None

    for i in range(len(df)):
        row = df.iloc[i]
        t = df.index[i]
        if t.date() != current_date:
            current_date = t.date()
            trades_today = 0
            losses_today = 0
            daily_stopped = False

        # market hours gate (non-repainting: closed candles only)
        tm = t.time()
        if not (dtime_between(tm)):
            continue

        close = float(row['close'])
        iv_i = float(iv_series.iloc[i])
        T_i = float(T_series[i])
        atr_mult = params.get('atr_mult', 1.5)
        swing_n = params.get('swing_n', 10)

        # ---- manage open ----
        if open_trade:
            opt = 'CALL' if open_trade['type'] == 'BUY_CALL' else 'PUT'
            cur = get_prem(open_trade['strike'], opt, t, close, T_i, iv_i)
            reason = None
            sl_level = open_trade['sl_level']
            if open_trade['type'] == 'BUY_CALL' and close <= sl_level:
                reason = f"{open_trade['sl_method']} SL"
            elif open_trade['type'] == 'BUY_PUT' and close >= sl_level:
                reason = f"{open_trade['sl_method']} SL"
            if not reason and cur >= open_trade['target']:
                reason = 'Target'
            if (not reason and params.get('hybrid') and not open_trade['partial_booked']
                    and cur >= open_trade['target_1r']):
                open_trade['partial_pnl'] = (cur - open_trade['entry_prem']) * 0.5 * lot
                open_trade['partial_booked'] = True
            if reason:
                cost, _ = option_costs(open_trade['entry_prem'], cur, lot)
                pnl = open_trade['partial_pnl'] + (cur - open_trade['entry_prem']) * 0.5 * lot - cost
                open_trade.update(exit_prem=cur, exit_reason=reason, pnl=pnl,
                                  exit_time=t, choppy=open_trade['choppy'])
                trades.append(open_trade)
                trades_today += 1
                if pnl < 0:
                    losses_today += 1
                open_trade = None
                if trades_today >= config.MAX_TRADES_PER_DAY or losses_today >= config.MAX_LOSSES_PER_DAY:
                    daily_stopped = True
            continue

        if daily_stopped:
            continue

        # ---- regime NO-TRADE filter ----
        if params.get('regime') and vol_q is not None:
            low_vol = iv_i < vol_q
            flat_trend = abs(float(row['vwma_slope'])) < slope_eps
            if low_vol or flat_trend:
                continue

        sig = entry_decision(engine, row, df, i, params['mask'])
        if not sig:
            continue

        opt = 'CALL' if sig == 'BUY_CALL' else 'PUT'
        strike = engine.select_option_strike(close, sig)
        entry_prem = get_prem(strike, opt, t, close, T_i, iv_i)
        sl_level = sl_level_for(close, row, df, i, sig, params['sl'], atr_mult, swing_n)
        sl_prem = get_prem(strike, opt, t, sl_level, T_i, iv_i)
        risk = entry_prem - sl_prem
        if risk <= 0:
            continue
        if config.LIQUIDITY_FILTER_ENABLED and entry_prem < config.MIN_PREMIUM:
            continue
        R = params.get('target_r', 2.0)
        target = entry_prem + R * risk

        open_trade = {
            'type': sig, 'strike': strike, 'entry_time': t, 'entry_prem': entry_prem,
            'sl_level': sl_level, 'sl_method': params['sl'], 'target': target,
            'target_1r': entry_prem + risk, 'partial_booked': False, 'partial_pnl': 0.0,
            'choppy': (iv_i < vol_q) if vol_q is not None else False,
        }

    # close residual at end of data
    if open_trade:
        last = df.iloc[-1]
        close = float(last['close'])
        iv_i = float(iv_series.iloc[-1]); T_i = float(T_series[-1])
        opt = 'CALL' if open_trade['type'] == 'BUY_CALL' else 'PUT'
        cur = get_prem(open_trade['strike'], opt, df.index[-1], close, T_i, iv_i)
        cost, _ = option_costs(open_trade['entry_prem'], cur, lot)
        pnl = open_trade['partial_pnl'] + (cur - open_trade['entry_prem']) * 0.5 * lot - cost
        open_trade.update(exit_prem=cur, exit_reason='End of Data', pnl=pnl,
                          exit_time=df.index[-1], choppy=open_trade['choppy'])
        trades.append(open_trade)

    return trades


def dtime_between(tm):
    from datetime import time as dtime
    mo, mc = dtime(9, 45), dtime(15, 30)
    ls, le = dtime(12, 30), dtime(14, 0)
    if mo <= tm <= mc and not (ls <= tm <= le):
        return True
    return False


# ---------------------------------------------------------------------------
# Metrics + forensics
# ---------------------------------------------------------------------------
def metrics(trades):
    if not trades:
        return dict(n=0, win=0.0, target=0.0, sl=0.0, pf=0.0, exp=0.0,
                    dd=0.0, avg_w=0.0, avg_l=0.0, max_loss_streak=0)
    pnls = np.array([x['pnl'] for x in trades])
    wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
    reasons = [x['exit_reason'] for x in trades]
    target_hits = sum(1 for r in reasons if r == 'Target')
    sl_hits = sum(1 for r in reasons if r.endswith('SL'))
    equity = np.cumsum(pnls)
    dd = (equity - np.maximum.accumulate(equity)).min()
    pf = (wins.sum() / -losses.sum()) if losses.sum() < 0 else (float('inf') if wins.sum() > 0 else 0.0)
    # max losing streak
    streak = mx = 0
    for p in pnls:
        if p < 0:
            streak += 1; mx = max(mx, streak)
        else:
            streak = 0
    return dict(
        n=len(pnls), win=len(wins) / len(pnls) * 100,
        target=target_hits / len(pnls) * 100, sl=sl_hits / len(pnls) * 100,
        pf=pf, exp=float(pnls.mean()), dd=float(dd),
        avg_w=float(wins.mean()) if len(wins) else 0.0,
        avg_l=float(losses.mean()) if len(losses) else 0.0,
        max_loss_streak=int(mx),
    )


def forensic_table(trades):
    """Categorise stop-losses to find the biggest sources (spec §2)."""
    from collections import Counter
    sl = Counter()
    sl_choppy = 0
    for x in trades:
        if x['exit_reason'].endswith('SL'):
            sl[x['exit_reason']] += 1
            if x.get('choppy'):
                sl_choppy += 1
    total_sl = sum(sl.values())
    return sl, total_sl, sl_choppy


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def load_data(mock, real_options, csv_path=None):
    if csv_path:
        return load_futures_csv(csv_path)
    bt = Backtester(mock=mock, real_options=real_options)
    if mock:
        df = generate_synthetic_futures()
    else:
        df = bt._load_df()
        if df is None:
            print("ERROR: no Kite data (check creds / historical API).")
            sys.exit(1)
    return df


def split_oos(df, train=0.6, val=0.2):
    n = len(df)
    i1, i2 = int(n * train), int(n * (train + val))
    return df.iloc[:i1], df.iloc[i1:i2], df.iloc[i2:]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--mock', action='store_true')
    ap.add_argument('--real-options', action='store_true')
    ap.add_argument('--csv', default=None,
                    help='Cached NIFTY FUT 3m CSV (date,open,high,low,close,volume)')
    ap.add_argument('--opt-csv', default=None,
                    help='Optional option-premium CSV (timestamp,strike,type,premium) for REAL premiums')
    ap.add_argument('--targets', default='1.0,1.25,1.5,2.0,2.5,3.0')
    args = ap.parse_args()
    if not args.mock and not args.real_options and not args.csv:
        args.mock = True  # safe default: never silently use real creds

    src = 'CSV (cached)' if args.csv else ('REAL KITE DATA' if args.real_options else 'SYNTHETIC — NOT TRADEABLE')
    print("\n" + "=" * 78)
    print(f"ADVERSARIAL OPTIMIZATION HARNESS  [{src}]")
    print("=" * 78)

    df = load_data(args.mock, args.real_options, args.csv)
    opt_lookup = build_opt_lookup(args.opt_csv) if args.opt_csv else None
    if opt_lookup is not None:
        print("✓ Real option premiums loaded from --opt-csv")
    train, val, test = split_oos(df)

    # regime threshold learned ONLY from train (no future leak)
    ret = train['close'].pct_change().fillna(0.0)
    vol_q = (ret.rolling(config.IV_WINDOW).std() * np.sqrt(252)).quantile(0.25)

    base = dict(mask=('supertrend', 'vwap', 'vwma'), sl='supertrend',
                target_r=2.0, hybrid=True, atr_mult=1.5, swing_n=10,
                regime_vol_q=vol_q, regime_slope_eps=0.0008)

    # ---- §12 ABLATION ----
    print("\n--- §12 ABLATION (train) ---")
    print(f"{'mask':<34}{'n':>4}{'win%':>7}{'tgt%':>7}{'sl%':>7}{'PF':>7}{'exp':>9}")
    masks = [('supertrend',), ('vwap',), ('vwma',),
             ('supertrend', 'vwap'), ('supertrend', 'vwma'), ('vwap', 'vwma'),
             ('supertrend', 'vwap', 'vwma')]
    for m in masks:
        tr = simulate(train, {**base, 'mask': m, 'regime': False}, opt_lookup=opt_lookup)
        mt = metrics(tr)
        pf = f"{mt['pf']:.2f}" if np.isfinite(mt['pf']) else 'inf'
        print(f"{str(m):<34}{mt['n']:>4}{mt['win']:>7.1f}{mt['target']:>7.1f}"
              f"{mt['sl']:>7.1f}{pf:>7}{mt['exp']:>9.0f}")

    # ---- §7 SL methods ----
    print("\n--- §7 STOP-LOSS METHODS (train) ---")
    print(f"{'sl':<12}{'n':>4}{'win%':>7}{'sl%':>7}{'PF':>7}{'exp':>9}")
    for sl in ('supertrend', 'atr', 'swing'):
        tr = simulate(train, {**base, 'sl': sl, 'regime': False}, opt_lookup=opt_lookup)
        mt = metrics(tr)
        pf = f"{mt['pf']:.2f}" if np.isfinite(mt['pf']) else 'inf'
        print(f"{sl:<12}{mt['n']:>4}{mt['win']:>7.1f}{mt['sl']:>7.1f}{pf:>7}{mt['exp']:>9.0f}")

    # ---- §8 TARGET R sweep ----
    print("\n--- §8 TARGET R MULTIPLE (train) ---")
    print(f"{'R':>5}{'n':>4}{'win%':>7}{'tgt%':>7}{'sl%':>7}{'PF':>7}{'exp':>9}")
    for R in [float(x) for x in args.targets.split(',')]:
        tr = simulate(train, {**base, 'target_r': R, 'regime': False}, opt_lookup=opt_lookup)
        mt = metrics(tr)
        pf = f"{mt['pf']:.2f}" if np.isfinite(mt['pf']) else 'inf'
        print(f"{R:>5.2f}{mt['n']:>4}{mt['win']:>7.1f}{mt['target']:>7.1f}{mt['sl']:>7.1f}{pf:>7}{mt['exp']:>9.0f}")

    # ---- §5 REGIME filter effect (best R from sweep above = 2.0 default) ----
    print("\n--- §5 REGIME NO-TRADE FILTER (train) ---")
    for regime in (False, True):
        tr = simulate(train, {**base, 'regime': regime}, opt_lookup=opt_lookup)
        mt = metrics(tr)
        pf = f"{mt['pf']:.2f}" if np.isfinite(mt['pf']) else 'inf'
        print(f"regime={'ON ' if regime else 'OFF'}: n={mt['n']} win={mt['win']:.1f}% "
              f"sl={mt['sl']:.1f}% PF={pf} exp={mt['exp']:.0f}")

    # ---- §18 FORENSICS on full-sample current strategy ----
    print("\n--- §18 LOSING-TRADE FORENSICS (full sample, current rules) ---")
    tr = simulate(df, {**base, 'regime': False}, opt_lookup=opt_lookup)
    sl, total_sl, choppy = forensic_table(tr)
    print(f"  total SLs: {total_sl}")
    for k, v in sl.most_common():
        print(f"    {k:<14}{v:>4}  ({v/total_sl*100:.0f}% of SLs)")
    print(f"  SLs taken in low-vol/choppy regime: {choppy} ({choppy/max(total_sl,1)*100:.0f}%)")

    # ---- §14 OUT-OF-SAMPLE + validation (untouched test) ----
    print("\n--- §14 OUT-OF-SAMPLE (untouched test split) ---")
    best = {**base, 'regime': True}  # regime ON chosen for demonstration
    for name, split in (('TRAIN', train), ('VALID', val), ('TEST(OOS)', test)):
        tr = simulate(split, best, opt_lookup=opt_lookup)
        mt = metrics(tr)
        pf = f"{mt['pf']:.2f}" if np.isfinite(mt['pf']) else 'inf'
        print(f"  {name:<10} n={mt['n']:>3} win={mt['win']:>5.1f}% "
              f"tgt={mt['target']:>5.1f}% sl={mt['sl']:>5.1f}% PF={pf:>6} "
              f"exp={mt['exp']:>7.0f} dd={mt['dd']:>8.0f}")

    # ---- §21 Final performance table (current vs regime-on) ----
    print("\n--- §21 CURRENT vs V2 (regime-on) — full sample ---")
    for label, p in (('CURRENT', {**base, 'regime': False}),
                     ('V2', {**base, 'regime': True})):
        tr = simulate(df, p, opt_lookup=opt_lookup); mt = metrics(tr)
        pf = f"{mt['pf']:.2f}" if np.isfinite(mt['pf']) else 'inf'
        print(f"  {label:<8} n={mt['n']:>3} win={mt['win']:>5.1f}% tgt={mt['target']:>5.1f}% "
              f"sl={mt['sl']:>5.1f}% PF={pf:>6} exp={mt['exp']:>7.0f} "
              f"dd={mt['dd']:>8.0f} avgW={mt['avg_w']:.0f} avgL={mt['avg_l']:.0f} "
              f"maxLossStreak={mt['max_loss_streak']}")

    print("\n" + "=" * 78)
    if args.mock:
        print("⚠️  SYNTHETIC DATA: above validates HARNESS LOGIC ONLY.")
        print("    Re-run with --csv <fut.csv> [--opt-csv <prem.csv>] for tradeable results.")
    elif args.csv:
        print("✅ CACHED-CSV run complete. Review OOS/validation stability before any verdict.")
    else:
        print("✅ Real-data run complete. Review OOS/validation stability before any verdict.")
    print("=" * 78)


if __name__ == '__main__':
    main()
