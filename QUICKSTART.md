# NIFTY Options Trading System - Quick Start Guide

## ✅ System Status: READY

All components have been built and tested successfully:
- ✓ Data fetcher module
- ✓ Technical indicators (VWAP, VWMA, Supertrend)
- ✓ Strategy engine (HTF + LTF logic)
- ✓ Backtesting engine
- ✓ Interactive dashboard
- ✓ Telegram notifications

## 🚀 Getting Started

### 1. Run Your First Backtest

```bash
cd ~/nifty-options-backtester
python3 main.py backtest --start 2024-01-01 --end 2024-08-07
```

### 2. Launch Interactive Dashboard

```bash
python3 main.py dashboard
```

Then open your browser to: `http://localhost:8501`

### 3. Set Up Telegram Notifications

Follow these steps to receive real-time alerts:

#### Step 1: Create Telegram Bot
1. Open Telegram, search for `@BotFather`
2. Send `/newbot`
3. Follow instructions to create bot
4. Copy the bot token (e.g., `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

#### Step 2: Get Your Chat ID
1. Search for `@userinfobot` on Telegram
2. Send `/start`
3. Copy your chat ID (a number like `123456789`)

#### Step 3: Configure
Open `config.py` and add these lines at the end:

```python
# Telegram Configuration
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"
```

#### Step 4: Test
```bash
python3 main.py test-telegram
```

You should receive a test message on Telegram!

## 📊 Understanding Your Results

### Key Metrics
- **Win Rate**: Percentage of profitable trades
- **Total P&L**: Cumulative profit/loss
- **Avg Win/Loss**: Average profit per winning/losing trade
- **CALL vs PUT Win Rate**: Breakdown by option type

### Dashboard Features
- **Equity Curve**: Visual P&L over time
- **Win Rate Chart**: Overall vs CALL vs PUT performance
- **P&L Distribution**: Histogram of trade outcomes
- **Trade Log**: Detailed table of all trades
- **CSV Export**: Download results for further analysis

## ⚙️ Customization

All parameters are in `config.py`:

### Common Adjustments

```python
# Change backtest period
BACKTEST_START_DATE = "2023-01-01"
BACKTEST_END_DATE = "2024-12-31"

# Adjust capital per trade
CAPITAL_PER_TRADE = 100000  # ₹1,00,000

# Modify VWMA length
VWMA_LENGTH = 30  # Default: 20

# Adjust Supertrend
SUPERTREND_PERIOD = 14  # Default: 10
SUPERTREND_MULTIPLIER = 2.5  # Default: 3.0

# Change target percentage
PARTIAL_TARGET_PERCENT = 40  # Default: 50
```

## 📝 Important Notes

### Data Limitations
⚠️ **Yahoo Finance Restrictions:**
- Only 8 days of 1-minute intraday data available
- For longer backtests (>8 days), system uses daily data
- For production: Consider NSE API or paid data provider

### For Better Backtesting
To get proper 3m/15m data, you need:
1. **NSE Official API** (free but requires registration)
2. **Paid Data Providers** (TrueData, Zerodha Historical API, etc.)
3. **Your Own Historical Data** (if you've been collecting)

### Option Price Simulation
- Current version uses simplified pricing model
- For production: Use actual historical option chain data

## 🎯 Telegram Notification Examples

Once configured, you'll receive messages like:

### Signal Alert
```
🟢 BUY CALL SIGNAL

💰 Spot: 24,632.00
🎯 Strike: 24600CE
📊 Confidence: 91%

📋 Reason:
✓ 15m Bullish
✓ Price Above VWAP
✓ Price Above VWMA(20)
✓ Supertrend Green
✓ 3m Candle Closed Above All Indicators

🕐 Time: 10:45 AM
```

### Trade Closed
```
✅ TRADE CLOSED - PROFIT

📍 BUY_CALL
🎯 Strike: 24600CE
💵 Entry: ₹85.50
💰 Exit: ₹112.30

📊 P&L: ₹1,340.00 (+31.35%)
📝 Reason: Target Reached (30%)
🕐 Duration: 1:23:00
```

## 🔧 Troubleshooting

### Issue: No intraday data
**Solution**: This is normal with Yahoo Finance. Use recent dates (<8 days) or accept daily data for testing.

### Issue: Dashboard won't start
**Solution**: 
```bash
# Try reinstalling Streamlit
pip3 install --upgrade streamlit

# Or run directly
streamlit run dashboard.py
```

### Issue: Import errors
**Solution**:
```bash
pip3 install -r requirements.txt --upgrade
```

## 📈 Next Steps for Production

### 1. Get Real Data
- Sign up for NSE API or paid data provider
- Modify `data_fetcher.py` to use new data source

### 2. Add Historical Options Data
- Collect option chain historical data
- Update `backtester.py` to use real option prices

### 3. Live Trading Integration
- Connect to broker API (Zerodha, Angel One, etc.)
- Implement order placement module
- Add risk management safeguards

### 4. Monitor & Optimize
- Track live performance
- Compare with backtest results
- Adjust parameters based on market conditions

## 📞 Support

For issues or questions:
1. Check `README.md` for detailed documentation
2. Review inline code comments
3. Test individual modules (instructions in README)

## 🎓 Strategy Rules Summary

### HTF (15m) Determines Bias
- **Bullish**: Price > VWAP + Price > VWMA + ST Green → Only CALL trades
- **Bearish**: Price < VWAP + Price < VWMA + ST Red → Only PUT trades
- **Mixed**: Any disagreement → NO TRADE

### LTF (3m) Confirms Entry
- All HTF + LTF conditions must align
- Candle must CLOSE past all indicators
- Never trades on partial candles (non-repainting)

### Exit Strategy
- **Stop Loss**: ST flip, VWAP cross, or swing violation
- **Target**: 30% profit (configurable) or trail with ST

## 🚀 Commands Reference

```bash
# Run backtest
python3 main.py backtest

# Run backtest with custom dates
python3 main.py backtest --start 2024-01-01 --end 2024-12-31

# Run backtest and notify via Telegram
python3 main.py backtest --notify

# Launch dashboard
python3 main.py dashboard

# Test Telegram connection
python3 main.py test-telegram

# Test individual components
python3 data_fetcher.py
python3 indicators.py
python3 strategy.py
python3 backtester.py
```

---

**Built on**: August 7, 2026  
**Status**: Production-grade architecture, ready for real data integration  
**Version**: 1.0
