# Strategy Spec — 11:15–12:15 Range Breakout + EMA 9/21 Pullback Scalping

**Instrument:** NIFTY 50 SPOT (Kite token `256265`, INDICES segment)
**Resolution:** 3-minute candles (primary). The 1-hour "reference" range is
**constructed from 3m candles** (see §Range) rather than read from a native 1h
candle, because a platform 1h candle labelled 12:00 does NOT equal 11:15–12:15.
**Timezone:** Asia/Kolkata (IST). **Session:** NSE 09:15–15:30 IST.
**Phase:** BACKTEST ONLY. No live automation, no Telegram, until approved.

---

## 1. Range construction (the 11:15–12:15 box)
For each trading day, take all **closed** 3m candles whose timestamp `t` satisfies
`11:15:00 <= t <= 12:15:00` IST (inclusive; the 12:12–12:15 candle closes exactly
at 12:15 and is included).

- `Range_High = max(high)` over those candles
- `Range_Low  = min(low)`  over those candles
- `Range_Size = Range_High - Range_Low`

The range is **fixed at 12:15 IST** (after the 12:15-close candle is complete).
Breakout monitoring begins on the **next** 3m candle (12:15–12:18, evaluated at
12:18). This is non-repainting (only closed candles used).

**Data-quality gate:** require at least 15 of the ~20 possible window candles to be
present; otherwise skip the day (handles holidays/half-sessions/gaps).

## 2. Breakout / breakdown (Layer A — base)
Using **closed** 3m candles from 12:15 onward:
- **LONG breakout:** a 3m candle **CLOSE > Range_High**
- **SHORT breakout:** a 3m candle **CLOSE < Range_Low**

Wick-only pierces (high/low crosses the level but close does not) are recorded
separately as *false-breakout* candidates but do **not** trigger.

## 3. Momentum confirmation (Layer B)
Added on top of Layer A. Baseline (to be swept in robustness):
- LONG:  `close > Range_High` AND body ≥ 30% of candle range
  (`|close-open| >= 0.30*(high-low)`) AND close in upper 60% of candle
  (`close >= low + 0.60*(high-low)`) AND `close > EMA9 > EMA21`.
- SHORT: mirror (close < Range_Low, body ≥ 30%, close in lower 60%, `close < EMA9 < EMA21`).

## 4. EMA pullback entry (Layer C — final)
EMAs computed on 3m SPOT: `EMA9`, `EMA21` (standard Wilder/span smoothing).
After a Layer-B momentum breakout in direction D:
1. Wait for a **pullback** to the EMA zone: a 3m candle whose `low (LONG)` / `high (SHORT)`
   reaches within a buffer of `max(EMA9, EMA21)` (baseline buffer = 0.05% of price).
   Pullback must **NOT** invalidate: close stays on the breakout side
   (`close >= Range_High` for LONG / `close <= Range_Low` for SHORT).
2. **Renewed confirmation** candle: closes back **above EMA9 (LONG)** / **below EMA9 (SHORT)**
   with `close > open` (bullish) / `close < open` (bearish).
3. **Entry = confirmation candle close.**

Direction D (LONG/SHORT) is locked at the momentum breakout and cannot flip within a setup.

## 5. Stop loss & targets
- **LONG SL = Range_Low** ; **SHORT SL = Range_High** (per spec — directional, not "high of 1h").
- `Risk = |Entry - SL|`.
- **Target 1:1  = Entry ± 1×Risk**
- **Target 1:1.5 = Entry ± 1.5×Risk** (symmetrical for SHORT).

## 6. Exit / trade management
Scan each subsequent **closed** 3m candle:
- LONG exit at SL if `low <= SL`; at target if `high >= Target`.
- SHORT exit at SL if `high >= SL`; at target if `low <= Target`.
- **Same-candle ambiguity (both SL and target touched):** BASELINE = conservative →
  count as **SL hit** (worst case). A target-first alternative is reported as sensitivity.
- EMA re-cross / flat-EMA handling: not an auto-exit; trade runs to SL or target
  (keeps the rule objective). Documented as a possible improvement.
- **Session cutoff (entry):** baseline last entry **14:30 IST** (swept: 14:00 / 14:30 / 15:00).
  Trades entered before cutoff may exit after cutoff (run to SL/target).

## 7. Trade-count versions
- **V1:** at most **one entry per day** (first valid completed setup).
- **V2:** allow the **next valid setup after the first trade closes** (win or loss);
  i.e., re-entry permitted, capped at e.g. 3 entries/day.
Compared on profitability, consistency, drawdown, R-adj return, frequency.

## 8. Statistics captured per trade
breakout_time, pullback_time, entry_time, entry_price, direction, Range_High,
Range_Low, EMA9, EMA21, SL, Target1, Target2, exit_time, exit_price, P&L(points),
R_multiple, exit_reason.

## 9. Analysis plan (matches backtest requirements)
- **Layered lift:** A (breakout) → B (+momentum) → C (+EMA pullback). Show incremental PF / expectancy / win-rate per layer.
- **Targets:** 1:1 vs 1:1.5 (and 1:1.25 in robustness).
- **Entry buckets:** 12:15–12:30, 12:30–13:00, 13:00–13:30, 13:30–14:00, 14:00–14:30, 14:30+.
- **Regime:** classify each day — trending / range-bound / high-vol / low-vol / gap-up / gap-down / strong-bull / strong-bear — and split stats. Test an optional regime filter (no overfit).
- **False-breakout:** count wick-only pierces, % returning inside range, how often pullback prevents bad entries; quantify Layer B→C improvement.
- **Robustness:** EMA(9,21) vs (8,20) vs (10,21); momentum body 20/30/40%; close-in-candle 50/60/70%; targets 1:1/1.25/1.5; cutoffs 14:00/14:30/15:00.
- **OOS:** chronological split (e.g., first 60% develop, last 40% validate). Walk-forward if sample permits.
- **Costs:** baseline GROSS (index points). Sensitivity: subtract a per-trade cost (point slippage + later mapped to option charges) and re-report PF/expectancy.

## 10. Edge verdict framework
Edge = `expectancy > 0` AND `profit factor > 1` AND holds under robustness + OOS
(not merely high win-rate). Verdict: **YES / NO / INCONCLUSIVE**.
- INCONCLUSIVE if sample too small (data depth limited) to separate signal from noise.

## 11. Options translation (post-validation only, separate backtest)
Underlying signal stays SPOT-based. Options layer (ATM / 1-ITM / delta, liquidity,
bid-ask, slippage, STT, expiry) backtested **separately** — a profitable SPOT edge
does not imply profitable options P&L.

---
### Baseline decisions flagged for your review BEFORE I bake them into the engine
1. Breakout = **close-based** (not wick). 2. Range built from **3m** (not native 1h).
3. Same-candle SL/target = **SL first (conservative)**. 4. Momentum body≥30%, close-in-60%.
5. Pullback buffer = **0.05%** to EMA zone. 6. Cutoff baseline **14:30**. 7. V1 vs V2 both tested.
If any baseline is wrong, tell me and I'll change it before running.
