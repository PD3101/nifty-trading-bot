"""
Update the trade book workbook from console tradebook JSON.

Reads /tmp/tb_all.json (from fetch_tradebook.py), appends new legs to
Raw_Trades, re-matches FIFO per contract in Trade_Log, updates
Open_Positions, and saves the workbook.

Usage:
    python update_trade_book.py [path_to_book.xlsx] [path_to_trades.json]
"""

import json
import os
import sys
from collections import defaultdict
from copy import copy
from datetime import datetime

import openpyxl
from openpyxl.utils import get_column_letter

BOOK_PATH = os.getenv(
    'TRADE_BOOK_PATH',
    os.path.expanduser('~/Desktop/Trade_Book_AQ9308.xlsx'))
TRADES_PATH = os.getenv('TRADES_JSON', '/tmp/tb_all.json')

CHARGES_CONFIG = {
    'opt_brokerage_per_order': 20.0,
    'opt_stt_sell_pct': 0.0015,
    'opt_txn_pct': 0.0003553,
    'opt_sebi_per_cr': 10.0,
    'opt_ipft_per_cr': 0.01,
    'opt_stamp_buy_pct': 0.00003,
    'gst_rate': 0.18,
}


def leg_charges(turnover, side, is_option=True):
    """Compute charges per leg (mirrors the workbook formulas)."""
    brokerage = CHARGES_CONFIG['opt_brokerage_per_order']  # flat ₹20/order
    stt = turnover * CHARGES_CONFIG['opt_stt_sell_pct'] if side == 'sell' else 0.0
    txn = turnover * CHARGES_CONFIG['opt_txn_pct']
    turnover_cr = turnover / 10_000_000.0
    sebi = turnover_cr * CHARGES_CONFIG['opt_sebi_per_cr']
    ipft = turnover_cr * CHARGES_CONFIG['opt_ipft_per_cr']
    stamp = turnover * CHARGES_CONFIG['opt_stamp_buy_pct'] if side == 'buy' else 0.0
    gst = (brokerage + sebi + txn + ipft) * CHARGES_CONFIG['gst_rate']
    total = brokerage + stt + txn + sebi + ipft + stamp + gst
    charge_per_unit = total / max(turnover / max(1, 1), 1)  # placeholder
    return {
        'brokerage': round(brokerage, 4),
        'stt': round(stt, 4),
        'txn': round(txn, 4),
        'sebi': round(sebi, 4),
        'ipft': round(ipft, 4),
        'stamp': round(stamp, 4),
        'gst': round(gst, 4),
        'total': round(total, 4),
        'charge_per_unit': round(total / max(1, turnover), 6),
    }


def read_existing_raw_trades(wb):
    """Read existing Raw_Trades rows as dicts keyed by trade_id."""
    ws = wb['Raw_Trades']
    existing = {}
    for row in ws.iter_rows(min_row=4, max_row=ws.max_row, values_only=True):
        if not row or not row[0]:
            continue
        trade_id = str(row[0]).strip()
        if trade_id:
            existing[trade_id] = {
                'trade_id': trade_id,
                'symbol': row[2],
                'trade_type': row[8],
                'quantity': row[9],
                'price': row[10],
                'trade_date': row[5],
                'execution_time': row[21] if len(row) > 21 else '',
            }
    return existing


def console_to_raw_row(trade):
    """Convert console trade dict to Raw_Trades row values."""
    td = trade
    symbol = td['tradingsymbol']
    quantity = td['quantity']
    price = td['price']
    turnover = quantity * price
    side = td['trade_type']
    charges = leg_charges(turnover, side)
    exec_time = td.get('order_execution_time', '')
    trade_date = td.get('trade_date', '')
    if isinstance(trade_date, str):
        trade_date = datetime.strptime(trade_date, '%Y-%m-%d')
    return [
        td['trade_id'],           # A: Trade ID
        td['order_id'],           # B: Order ID
        symbol,                   # C: Symbol
        'OPTION',                 # D: Instrument (value, not formula)
        trade_date,               # E: Expiry Date (from trade_date context)
        trade_date,               # F: Trade Date
        td['exchange'],           # G: Exchange
        td['segment'],            # H: Segment
        td['trade_type'],         # I: Trade Type
        quantity,                 # J: Quantity
        price,                    # K: Price
        turnover,                 # L: Turnover
        charges['brokerage'],     # M: Brokerage
        charges['stt'],           # N: STT
        charges['txn'],           # O: Exchange Txn Charges
        charges['sebi'],          # P: SEBI Charges
        charges['ipft'],          # Q: IPFT Charges
        charges['stamp'],         # R: Stamp Duty
        charges['gst'],           # S: GST
        charges['total'],         # T: Total Charges
        charges['charge_per_unit'], # U: Charge / Unit
        exec_time,                # V: Order Execution Time
        datetime.now(),           # W: Import Batch Date
    ]


def fifo_match(all_legs):
    """FIFO-match legs per contract (symbol). Returns (matched_trades, open_positions)."""
    legs_by_symbol = defaultdict(list)
    for leg in all_legs:
        legs_by_symbol[leg['tradingsymbol']].append(leg)

    matched = []
    open_positions = []

    for symbol, legs in sorted(legs_by_symbol.items()):
        legs.sort(key=lambda x: (x['trade_date'], x.get('order_execution_time', '')))
        buy_queue = []
        for leg in legs:
            if leg['trade_type'] == 'buy':
                buy_queue.append(leg)
            elif leg['trade_type'] == 'sell':
                remaining_qty = leg['quantity']
                sell_date = leg['trade_date']
                sell_time = leg.get('order_execution_time', '')
                sell_price = leg['price']
                sell_id = leg['trade_id']
                while remaining_qty > 0 and buy_queue:
                    buy = buy_queue[0]
                    match_qty = min(remaining_qty, buy['quantity'])
                    buy_remaining = buy['quantity'] - remaining_qty
                    if buy_remaining > 0:
                        buy['quantity'] = buy_remaining
                        buy_queue[0] = buy
                    else:
                        buy_queue.pop(0)
                    matched.append({
                        'symbol': symbol,
                        'quantity': match_qty,
                        'buy_trade_id': buy['trade_id'],
                        'buy_date': buy['trade_date'],
                        'buy_time': buy.get('order_execution_time', ''),
                        'buy_price': buy['price'],
                        'sell_trade_id': sell_id,
                        'sell_date': sell_date,
                        'sell_time': sell_time,
                        'sell_price': sell_price,
                    })
                    remaining_qty -= match_qty
        if buy_queue:
            for buy in buy_queue:
                open_positions.append(buy)

    matched.sort(key=lambda x: (x['sell_date'], x.get('sell_time', '')))
    return matched, open_positions


def update_workbook():
    trades = json.load(open(TRADES_PATH))
    wb = openpyxl.load_workbook(BOOK_PATH)
    existing = read_existing_raw_trades(wb)
    print(f'Existing legs: {len(existing)}')

    new_legs = [t for t in trades if t['trade_id'] not in existing]
    print(f'New legs to add: {len(new_legs)}')
    for t in new_legs:
        print(f"  {t['trade_date']} {t['trade_type']:<5} {t['tradingsymbol']:<18} qty={t['quantity']} price={t['price']} id={t['trade_id']}")

    # Append new rows to Raw_Trades
    ws_rt = wb['Raw_Trades']
    next_row = ws_rt.max_row + 1
    for t in new_legs:
        row_vals = console_to_raw_row(t)
        for col, val in enumerate(row_vals, 1):
            ws_rt.cell(row=next_row, column=col, value=val)
        next_row += 1
    print(f'Raw_Trades now: {next_row - 4} data rows')

    # Rebuild FIFO matching across ALL legs
    all_legs = list(trades)
    matched, open_positions = fifo_match(all_legs)
    print(f'Matched trades: {len(matched)}, Open positions: {len(open_positions)}')

    # Write Trade_Log
    ws_tl = wb['Trade_Log']
    # Clear existing data rows
    for row in range(4, ws_tl.max_row + 1):
        for col in range(1, ws_tl.max_column + 1):
            ws_tl.cell(row=row, column=col, value=None)

    for i, m in enumerate(matched, 1):
        row = i + 3  # data starts at row 4
        charges_buy = leg_charges(m['quantity'] * m['buy_price'], 'buy')
        charges_sell = leg_charges(m['quantity'] * m['sell_price'], 'sell')
        total_charges = charges_buy['total'] + charges_sell['total']
        gross = (m['sell_price'] - m['buy_price']) * m['quantity']
        net = gross - total_charges
        result = 'Win' if net > 0 else ('Loss' if net < 0 else 'Breakeven')
        holding = (m['sell_date'] - m['buy_date']).days if isinstance(m['sell_date'], datetime) else 0
        exit_month = m['sell_date'].strftime('%b-%Y') if isinstance(m['sell_date'], datetime) else ''

        ws_tl.cell(row=row, column=1, value=i)           # Match ID
        ws_tl.cell(row=row, column=2, value=m['symbol'])  # Symbol
        ws_tl.cell(row=row, column=3, value='OPTION')     # Instrument
        ws_tl.cell(row=row, column=4, value=m['sell_date'])  # Expiry Date
        ws_tl.cell(row=row, column=5, value=m['quantity']) # Quantity
        ws_tl.cell(row=row, column=6, value=m['buy_trade_id'])
        ws_tl.cell(row=row, column=7, value=m['buy_date'])
        ws_tl.cell(row=row, column=8, value=m['buy_time'])
        ws_tl.cell(row=row, column=9, value=m['buy_price'])
        ws_tl.cell(row=row, column=10, value=m['quantity'] * m['buy_price'])  # Buy Turnover
        ws_tl.cell(row=row, column=11, value=m['sell_trade_id'])
        ws_tl.cell(row=row, column=12, value=m['sell_date'])
        ws_tl.cell(row=row, column=13, value=m['sell_time'])
        ws_tl.cell(row=row, column=14, value=m['sell_price'])
        ws_tl.cell(row=row, column=15, value=m['quantity'] * m['sell_price']) # Sell Turnover
        ws_tl.cell(row=row, column=16, value=gross)        # Gross P&L
        ws_tl.cell(row=row, column=17, value=total_charges) # Charges
        ws_tl.cell(row=row, column=18, value=net)          # Net P&L
        ws_tl.cell(row=row, column=19, value=result)       # Result
        ws_tl.cell(row=row, column=20, value=holding)      # Holding
        ws_tl.cell(row=row, column=21, value=exit_month)   # Exit Month

    # Write Open_Positions
    ws_op = wb['Open_Positions']
    for row in range(4, ws_op.max_row + 1):
        for col in range(1, ws_op.max_column + 1):
            ws_op.cell(row=row, column=col, value=None)
    for i, pos in enumerate(open_positions, 1):
        row = i + 3
        ws_op.cell(row=row, column=1, value=pos['tradingsymbol'])
        ws_op.cell(row=row, column=2, value='OPTION')
        ws_op.cell(row=row, column=3, value=pos['trade_date'])
        side = 'SHORT' if pos['trade_type'] == 'sell' else 'LONG'
        ws_op.cell(row=row, column=4, value=side)
        ws_op.cell(row=row, column=5, value=pos['quantity'])
        ws_op.cell(row=row, column=6, value=pos['trade_id'])
        ws_op.cell(row=row, column=7, value=pos['trade_date'])
        ws_op.cell(row=row, column=8, value=pos.get('order_execution_time', ''))
        ws_op.cell(row=row, column=9, value=pos['price'])
        ws_op.cell(row=row, column=10, value=pos['quantity'] * pos['price'])

    # Save
    backup = BOOK_PATH.replace('.xlsx', '_backup.xlsx')
    wb.save(BOOK_PATH)
    print(f'\n✅ Workbook updated and saved to {BOOK_PATH}')
    print(f'   Trade_Log: {len(matched)} matched trades')
    print(f'   Open: {len(open_positions)} open position(s)')
    for p in open_positions:
        print(f"     {p['tradingsymbol']} {p['trade_type']} qty={p['quantity']} @ {p['price']} (trade_id={p['trade_id']})")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        BOOK_PATH = sys.argv[1]
    if len(sys.argv) > 2:
        TRADES_PATH = sys.argv[2]
    update_workbook()
