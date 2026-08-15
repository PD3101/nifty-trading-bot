"""
Backtester — 11:15-12:15 NIFTY SPOT Range Breakout + EMA 9/21 Pullback Scalping.

PHASE 1 only (research). No live trading, no Telegram.

Rules (see STRATEGY_1115_RANGE_BREAKOUT_SPEC.md):
  * NIFTY 50 SPOT, 3m candles, IST.
  * Range = high/low of 3m candles in [11:15, 12:15]; locked at 12:15.
  * LONG breakout = close > Range_High ; SHORT = close < Range_Low (close-based).
  * Layer B adds momentum; Layer C adds EMA9/21 pullback + confirmation.
  * SL = Range_Low (LONG) / Range_High (SHORT). Targets 1:1 and 1:1.5 R.
  * Closed candles only (no look-ahead). Same-candle SL/target -> conservative SL.

Run:  python backtest_1115.py --csv <spot_3m.csv> [--layer C] [--target 1.5] ...
      python backtest_1115.py --csv <f.csv> --sweep     # full analysis table
"""
import argparse
import sys
import numpy as np
import pandas as pd

pd.set_option('display.width', 200)
pd.set_option('display.max_columns', 30)


# --------------------------------------------------------------------------
# Params
# --------------------------------------------------------------------------
class P:
    def __init__(self, **kw):
        self.layer = kw.get('layer', 'C')          # A / B / C
        self.target = kw.get('target', 1.5)         # R multiple
        self.version = kw.get('version', 1)         # 1=one entry/day, 2=re-entry
        self.max_entries = kw.get('max_entries', 3)
        self.entry_cutoff = kw.get('entry_cutoff', '14:30')  # last entry time
        self.body_min = kw.get('body_min', 0.30)    # min body/range for momentum
        self.close_in = kw.get('close_in', 0.60)    # close in upper/lower portion
        self.pullback_buf = kw.get('pullback_buf', 0.0005)  # 0.05% to EMA zone
        self.max_pull_candles = kw.get('max_pull_candles', 20)  # ~60 min to confirm
        self.ema_fast = kw.get('ema_fast', 9)
        self.ema_slow = kw.get('ema_slow', 21)
        self.same_candle = kw.get('same_candle', 'SL')  # SL or TARGET first
        self.min_window_candles = kw.get('min_window_candles', 15)


def ema_series(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


# --------------------------------------------------------------------------
# Load
# --------------------------------------------------------------------------
def load_csv(path):
    df = pd.read_csv(path)
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'])
    elif 'timestamp' in df.columns:
        df['date'] = pd.to_datetime(df['timestamp'])
    else:
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df.iloc[:, 0])
    df.set_index('date', inplace=True)
    df.index.name = None
    if df.index.tz is None:
        df.index = df.index.tz_localize('Asia/Kolkata')
    else:
        df.index = df.index.tz_convert('Asia/Kolkata')
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
    df = df.sort_index()
    df['ema_f'] = ema_series(df['close'], 9)
    df['ema_s'] = ema_series(df['close'], 21)
    return df


# --------------------------------------------------------------------------
# Single-day range
# --------------------------------------------------------------------------
def day_range(g, p):
    win = g[(g.index.time >= pd.to_datetime('11:15').time()) &
            (g.index.time <= pd.to_datetime('12:15').time())]
    if len(win) < p.min_window_candles:
        return None
    return win['high'].max(), win['low'].min()


# --------------------------------------------------------------------------
# Core backtest
# --------------------------------------------------------------------------
def backtest(df, p):
    df = df.sort_index()
    df['day'] = df.index.date
    trades = []
    rejected = []  # breakouts that failed to become trades
    cutoff_t = pd.to_datetime(p.entry_cutoff).time()

    for day, g in df.groupby('day'):
        g = g[(g.index.time >= pd.to_datetime('09:15').time()) &
              (g.index.time <= pd.to_datetime('15:30').time())]
        if len(g) < 30:
            continue
        rng = day_range(g, p)
        if rng is None:
            continue
        RH, RL = rng
        post = g[g.index.time > pd.to_datetime('12:15').time()].copy()
        if len(post) == 0:
            continue
        post['ema_f'] = df.loc[post.index, 'ema_f'].values
        post['ema_s'] = df.loc[post.index, 'ema_s'].values

        entries_today = 0
        cap = 1 if p.version == 1 else p.max_entries
        i = 0
        state = 'IDLE'
        direction = None
        breakout_idx = 0
        pullback_done = False

        while i < len(post):
            row = post.iloc[i]
            t = row.name
            ef, es = row['ema_f'], row['ema_s']

            if state == 'IDLE':
                long_b = row['close'] > RH
                short_b = row['close'] < RL
                if not long_b and not short_b:
                    i += 1
                    continue
                direction = 'LONG' if long_b else 'SHORT'
                if p.layer == 'A':
                    if t.time() <= cutoff_t and entries_today < cap:
                        trades.append(_open_trade(post, i, direction, RH, RL, row['close'], p, day))
                        entries_today += 1
                        if p.version == 1:
                            entries_today = cap
                    i += 1
                    continue
                if p.layer == 'B':
                    if _momentum(row, direction, RH, RL, ef, es, p):
                        if t.time() <= cutoff_t and entries_today < cap:
                            trades.append(_open_trade(post, i, direction, RH, RL, row['close'], p, day))
                            entries_today += 1
                            if p.version == 1:
                                entries_today = cap
                    i += 1
                    continue
                # Layer C: wait for momentum breakout then pullback+confirm
                if _momentum(row, direction, RH, RL, ef, es, p):
                    state = 'PULLBACK'
                    breakout_idx = i
                    pullback_done = False
                i += 1
                continue

            elif state == 'PULLBACK':
                # invalidation
                if direction == 'LONG' and row['close'] < RH:
                    rejected.append(_rej(day, direction, 'invalidated', t))
                    state, direction = 'IDLE', None
                    i += 1
                    continue
                if direction == 'SHORT' and row['close'] > RL:
                    rejected.append(_rej(day, direction, 'invalidated', t))
                    state, direction = 'IDLE', None
                    i += 1
                    continue
                # pullback to EMA zone
                if direction == 'LONG':
                    zone = max(ef, es)
                    if row['low'] <= zone * (1 + p.pullback_buf):
                        pullback_done = True
                    confirmed = pullback_done and (row['close'] > ef and row['close'] > row['open'])
                else:
                    zone = min(ef, es)
                    if row['high'] >= zone * (1 - p.pullback_buf):
                        pullback_done = True
                    confirmed = pullback_done and (row['close'] < ef and row['close'] < row['open'])
                if confirmed:
                    if t.time() <= cutoff_t and entries_today < cap:
                        trades.append(_open_trade(post, i, direction, RH, RL, row['close'], p, day))
                        entries_today += 1
                        if p.version == 1:
                            entries_today = cap
                    else:
                        rejected.append(_rej(day, direction, 'cutoff', t))
                    state, direction, pullback_done = 'IDLE', None, False
                    i += 1
                    continue
                if (i - breakout_idx) > p.max_pull_candles:
                    rejected.append(_rej(day, direction, 'no_confirm', t))
                    state, direction, pullback_done = 'IDLE', None, False
                i += 1
                continue

    return trades, rejected


def _momentum(row, direction, RH, RL, ef, es, p):
    body = abs(row['close'] - row['open'])
    rng = row['high'] - row['low']
    if rng <= 0:
        return False
    if body / rng < p.body_min:
        return False
    if direction == 'LONG':
        if row['close'] <= RH:
            return False
        if row['close'] < row['low'] + p.close_in * rng:
            return False
        return row['close'] > ef > es
    else:
        if row['close'] >= RL:
            return False
        if row['close'] > row['low'] + (1 - p.close_in) * rng:
            return False
        return row['close'] < ef < es


def _open_trade(post, i, direction, RH, RL, entry, p, day):
    sl = RL if direction == 'LONG' else RH
    risk = abs(entry - sl)
    target = entry + risk * p.target if direction == 'LONG' else entry - risk * p.target
    # exit scan
    exit_price, reason, exit_idx = None, None, i
    for j in range(i + 1, len(post)):
        r2 = post.iloc[j]
        if direction == 'LONG':
            hit_sl = r2['low'] <= sl
            hit_tg = r2['high'] >= target
        else:
            hit_sl = r2['high'] >= sl
            hit_tg = r2['low'] <= target
        if hit_sl and hit_tg:
            exit_price, reason = (sl, 'SL') if p.same_candle == 'SL' else (target, 'TARGET')
            exit_idx = j
            break
        elif hit_sl:
            exit_price, reason = sl, 'SL'
            exit_idx = j
            break
        elif hit_tg:
            exit_price, reason = target, 'TARGET'
            exit_idx = j
            break
    if exit_price is None:
        exit_price = post.iloc[-1]['close']
        reason = 'EOD'
        exit_idx = len(post) - 1
    pnl = (exit_price - entry) if direction == 'LONG' else (entry - exit_price)
    R = pnl / risk if risk > 0 else 0.0
    return dict(day=str(day), direction=direction, entry_time=str(post.iloc[i].name),
                entry=round(entry, 2), sl=round(sl, 2), target=round(target, 2),
                exit_time=str(post.iloc[exit_idx].name),
                exit=round(exit_price, 2), pnl=round(pnl, 2), R=round(R, 3),
                reason=reason, rh=round(RH, 2), rl=round(RL, 2))


def _rej(day, direction, kind, t):
    return dict(day=str(day), direction=direction, kind=kind, time=str(t))


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------
def stats(trades):
    if not trades:
        return dict(trades=0)
    d = pd.DataFrame(trades)
    n = len(d)
    wins = (d['pnl'] > 0).sum()
    losses = (d['pnl'] < 0).sum()
    total_r = d['R'].sum()
    pf = (d.loc[d['pnl'] > 0, 'pnl'].sum() / -d.loc[d['pnl'] < 0, 'pnl'].sum()
          if losses > 0 else float('inf'))
    win_r = wins / n
    exp = d['R'].mean()
    maxdd = _max_drawdown(d['R'].cumsum().values)
    return dict(
        trades=n, wins=int(wins), losses=int(losses),
        win_rate=round(win_r, 4), loss_rate=round(1 - win_r, 4),
        avg_R=round(d['R'].mean(), 4), median_R=round(d['R'].median(), 4),
        total_R=round(total_r, 2), profit_factor=(round(pf, 2) if pf != float('inf') else 'inf'),
        expectancy=round(exp, 4),
        max_consec_wins=int(_streak(d['pnl'] > 0)),
        max_consec_losses=int(_streak(d['pnl'] < 0)),
        max_dd=round(maxdd, 2),
        avg_win=round(d.loc[d['pnl'] > 0, 'R'].mean(), 3) if wins else 0,
        avg_loss=round(d.loc[d['pnl'] < 0, 'R'].mean(), 3) if losses else 0,
        largest_win=round(d['R'].max(), 3), largest_loss=round(d['R'].min(), 3),
    )


def _max_drawdown(cum):
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return dd.min() if len(dd) else 0.0


def _streak(cond):
    best = run = 0
    for v in cond:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


# --------------------------------------------------------------------------
# Analysis helpers
# --------------------------------------------------------------------------
def run_layer(df, layer, target, version):
    p = P(layer=layer, target=target, version=version)
    tr, rej = backtest(df, p)
    s = stats(tr)
    s.update(dict(layer=layer, target=target, version=version,
                  rejected=len(rej)))
    return s, tr, rej


def print_table(rows, title):
    print(f"\n=== {title} ===")
    cols = ['layer', 'target', 'version', 'trades', 'win_rate', 'profit_factor',
            'expectancy', 'total_R', 'max_dd', 'rejected']
    dfp = pd.DataFrame(rows)
    for c in cols:
        if c not in dfp.columns:
            dfp[c] = np.nan
    print(dfp[cols].to_string(index=False))


def regime_classify(df):
    """Per-day regime tags from SPOT day bars."""
    df = df.sort_index()
    daily = df.resample('D').agg(open=('open', 'first'), close=('close', 'last'),
                                high=('high', 'max'), low=('low', 'min'))
    daily = daily.dropna()
    daily['prev_close'] = daily['close'].shift(1)
    daily['gap'] = (daily['open'] - daily['prev_close']) / daily['prev_close']
    daily['ret'] = (daily['close'] - daily['open']) / daily['open']
    daily['rng'] = (daily['high'] - daily['low']) / daily['open']
    median_rng = daily['rng'].median()
    out = {}
    for day, r in daily.iterrows():
        tags = []
        if r['gap'] > 0.003:
            tags.append('gap_up')
        elif r['gap'] < -0.003:
            tags.append('gap_down')
        if abs(r['ret']) > 0.005:
            tags.append('trending')
        else:
            tags.append('range_bound')
        if r['rng'] > median_rng:
            tags.append('high_vol')
        else:
            tags.append('low_vol')
        if r['ret'] > 0.008:
            tags.append('strong_bull')
        elif r['ret'] < -0.008:
            tags.append('strong_bear')
        out[str(day.date())] = tags
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--layer', default='C')
    ap.add_argument('--target', type=float, default=1.5)
    ap.add_argument('--version', type=int, default=1)
    ap.add_argument('--sweep', action='store_true', help='full analysis')
    args = ap.parse_args()

    df = load_csv(args.csv)
    print(f"Loaded {len(df)} candles: {df.index[0]} .. {df.index[-1]}")

    if args.sweep:
        rows = []
        for layer in ['A', 'B', 'C']:
            for tgt in [1.0, 1.5]:
                s, _, _ = run_layer(df, layer, tgt, 1)
                rows.append(s)
        print_table(rows, "LAYERED (Version 1)")

        rows = []
        for ver in [1, 2]:
            for tgt in [1.0, 1.5]:
                s, _, _ = run_layer(df, 'C', tgt, ver)
                rows.append(s)
        print_table(rows, "FINAL Layer C — Version x Target")

        # entry-time buckets
        s, tr, _ = run_layer(df, 'C', args.target, 1)
        if tr:
            d = pd.DataFrame(tr)
            d['et'] = pd.to_datetime(d['entry_time'])
            bins = ['12:15', '12:30', '13:00', '13:30', '14:00', '14:30', '15:30']
            d['bucket'] = pd.cut(d['et'], bins=pd.to_datetime(
                ['1900-01-01 ' + b for b in bins]).time, labels=bins[1:], right=False)
            print("\n=== Entry-time buckets (Layer C, 1:%s, V1) ===" % args.target)
            print(d.groupby('bucket', observed=True)['R'].agg(['count', 'mean', 'sum']).to_string())
        else:
            print("\n=== Entry-time buckets: 0 trades ===")

        # long vs short
        print("\n=== Long vs Short (Layer C, 1:%s, V1) ===" % args.target)
        for d_ in ['LONG', 'SHORT']:
            sub = [t for t in tr if t['direction'] == d_]
            print(d_, stats(sub))

        # regime
        reg = regime_classify(df)
        if tr:
            d2 = pd.DataFrame(tr)
            d2['reg'] = d2['day'].map(lambda x: reg.get(x, []))
            print("\n=== Regime analysis (Layer C) ===")
            for tag in ['trending', 'range_bound', 'high_vol', 'low_vol',
                        'gap_up', 'gap_down', 'strong_bull', 'strong_bear']:
                sub = [t for t in tr if tag in reg.get(t['day'], [])]
                st = stats(sub)
                print(f"  {tag:12} trades={st.get('trades',0):4} win={st.get('win_rate','-')} "
                       f"exp={st.get('expectancy','-')} totalR={st.get('total_R','-')}")
        else:
            print("\n=== Regime analysis: 0 trades ===")

        # false-breakout
        _, _, rej = run_layer(df, 'C', args.target, 1)
        if rej:
            rj = pd.DataFrame(rej)
            print("\n=== False-breakout / rejected setups (Layer C) ===")
            print(rj['kind'].value_counts().to_string())

        # robustness
        print("\n=== Robustness (Layer C, target 1.5, V1) ===")
        for ef, es in [(8, 20), (9, 21), (10, 21), (9, 20)]:
            p = P(layer='C', target=1.5, version=1, ema_fast=ef, ema_slow=es)
            tr2, _ = backtest(df, p)
            s = stats(tr2); s.update(dict(ema=f"{ef}/{es}"))
            rows.append(s)
        print(pd.DataFrame([r for r in rows if 'ema' in r])[['ema', 'trades', 'win_rate', 'expectancy', 'total_R']].to_string(index=False))

        # OOS
        days = sorted(df['day'].unique())
        split = int(len(days) * 0.6)
        train_days, test_days = set(days[:split]), set(days[split:])
        s, tr, _ = run_layer(df, 'C', args.target, 1)
        tr_tr = [t for t in tr if t['day'] in train_days]
        tr_te = [t for t in tr if t['day'] in test_days]
        print("\n=== Out-of-sample (first 60% train / last 40% test) ===")
        print("TRAIN:", stats(tr_tr))
        print("TEST :", stats(tr_te))
    else:
        s, tr, rej = run_layer(df, args.layer, args.target, args.version)
        print("\n=== Single run ===")
        for k, v in s.items():
            print(f"  {k}: {v}")


if __name__ == '__main__':
    main()
