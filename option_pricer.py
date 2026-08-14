"""
Option pricing for the backtester — Black-Scholes, replacing the previous
toy model (intrinsic + 0.3*intrinsic) that ignored IV, theta and vega.

This makes the backtest's P&L *credible*: premiums now move with spot via
delta, decay with time via theta, and react to volatility via vega. It still
uses an estimated IV (realized vol of the underlying, or a fixed value) — not
live option IV — so treat absolute P&L as indicative, not exact. If you have
Kite option historical data, feed real IV per candle instead.
"""

import math
import numpy as np
import config


def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(S, K, T, r, sigma, option_type):
    """Black-Scholes price for a European option. T in years (floored)."""
    if T <= 0:
        T = 1.0 / 365.0
    if sigma <= 0:
        sigma = 1e-6
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "CALL":
        return S * _ncdf(d1) - K * math.exp(-r * T) * _ncdf(d2)
    return K * math.exp(-r * T) * _ncdf(-d2) - S * _ncdf(-d1)


def bs_delta(S, K, T, r, sigma, option_type):
    if T <= 0:
        T = 1.0 / 365.0
    if sigma <= 0:
        sigma = 1e-6
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    if option_type == "CALL":
        return _ncdf(d1)
    return _ncdf(d1) - 1.0


def estimate_iv(returns, window=30):
    """
    Annualized realized vol from underlying pct returns, clamped to a sane band.
    Used as a proxy IV when live option IV is unavailable.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.size < 5:
        iv = config.IV_FIXED
    else:
        rv = float(np.std(arr[-window:]) * math.sqrt(252))
        iv = rv
    return float(min(config.IV_CAP, max(config.IV_FLOOR, iv)))


def price_option(spot, strike, T, iv, option_type):
    return bs_price(spot, strike, T, config.BS_RISK_FREE_RATE, iv, option_type)


def option_costs(entry_premium, exit_premium, lot):
    """
    India F&O transaction cost model (per lot). Approximations, documented in
    config.py. Returns total cost in ₹ subtracted from gross P&L.
    """
    notional_in = entry_premium * lot
    notional_out = exit_premium * lot

    brokerage = 2 * config.BROKERAGE_PER_ORDER                      # entry + exit
    stt = config.STT_PCT * notional_out                            # STT on SELL premium
    exchange = config.EXCHANGE_CHARGE_PCT * (notional_in + notional_out)
    stamp = config.STAMP_PCT * (notional_in + notional_out)
    gst = config.GST_PCT * (brokerage + exchange)                  # GST on (brokerage+exchange)
    slippage = config.SLIPPAGE_PCT * (notional_in + notional_out)

    total = brokerage + stt + exchange + stamp + gst + slippage
    return total, {
        "brokerage": brokerage, "stt": stt, "exchange": exchange,
        "stamp": stamp, "gst": gst, "slippage": slippage,
    }


if __name__ == "__main__":
    # Sanity: ITM call should be worth more than its intrinsic floor, delta ~0.6-0.8
    p = price_option(24500, 24450, 7/252, 0.18, "CALL")
    d = bs_delta(24500, 24450, 7/252, 0.06, 0.18, "CALL")
    print(f"ITM CALL premium ≈ ₹{p:.2f}  delta ≈ {d:.2f}")
