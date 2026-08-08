# NIFTY Options Backtesting System

A production-grade backtesting system for NIFTY Weekly Options trading with real-time Telegram notifications and interactive dashboard.

## 🎯 Features

- **Rule-Based Strategy**: Exact implementation of your proprietary NIFTY options strategy
- **Multi-Timeframe Analysis**: 15m HTF bias + 3m LTF execution
- **Technical Indicators**: VWAP, VWMA(20), Supertrend
- **Option Strike Selection**: Automatic ITM strike recommendation
- **Comprehensive Backtesting**: Historical performance analysis
- **Interactive Dashboard**: Web-based visualization with Streamlit
- **Telegram Notifications**: Real-time signal alerts
- **Non-Repainting**: Production-quality, deterministic signals

## 📊 Strategy Overview

### Higher Timeframe (15 Minutes)
- **Bullish Bias**: Price > VWAP AND Price > VWMA(20) AND Supertrend Green
- **Bearish Bias**: Price < VWAP AND Price < VWMA(20) AND Supertrend Red
- **Mixed**: Any disagreement = NO TRADE

### Entry Rules (3 Minutes)

**BUY CALL:**
1. HTF is Bullish
2. Price above VWAP
3. Price above VWMA(20)
4. Supertrend Green
5. 3m candle closes above all indicators

**BUY PUT:**
1. HTF is Bearish
2. Price below VWAP
3. Price below VWMA(20)
4. Supertrend Red
5. 3m candle closes below all indicators

### Exit Rules

**Stop Loss:**
- Supertrend flips
- Price closes back across VWAP
- Recent swing high/low violated

**Target:**
- Book partial at 30% profit (configurable)
- Trail remaining with Supertrend

## 🚀 Quick Start

### 1. Installation

```bash
# Navigate to project directory
cd nifty-options-backtester

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Edit `config.py` to customize parameters:
- Backtest date range
- Indicator settings
- Capital per trade
- Stop loss and target rules

### 3. Run Backtest

```bash
# Run with default settings
python main.py backtest

# Run with custom dates
python main.py backtest --start 2024-01-01 --end 2024-12-31

# Run and send results to Telegram
python main.py backtest --notify
```

### 4. Launch Dashboard

```bash
python main.py dashboard
```

The dashboard will open in your browser at `http://localhost:8501`

## 📱 Telegram Notifications Setup

### Step 1: Create Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Choose a name (e.g., "NIFTY Options Alerts")
4. Choose a username (e.g., "my_nifty_bot")
5. Copy the bot token you receive

### Step 2: Get Your Chat ID

1. Search for `@userinfobot` on Telegram
2. Send `/start` to this bot
3. Copy your chat ID (a number)

### Step 3: Configure

Add to `config.py`:

```python
# Telegram Configuration
TELEGRAM_BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
TELEGRAM_CHAT_ID = "123456789"
```

### Step 4: Test Connection

```bash
python main.py test-telegram
```

You should receive a test message on Telegram!

## 📂 Project Structure

```
nifty-options-backtester/
├── config.py              # Configuration parameters
├── data_fetcher.py        # Historical data fetching
├── indicators.py          # Technical indicator calculations
├── strategy.py            # Strategy logic and signal generation
├── backtester.py          # Backtesting engine
├── telegram_notifier.py   # Telegram integration
├── dashboard.py           # Interactive Streamlit dashboard
├── main.py                # Main entry point
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## 🔧 Configuration Parameters

### Market Settings
- `FUTURES_SYMBOL`: NIFTY Futures symbol
- `SPOT_SYMBOL`: NIFTY Spot symbol
- `HIGHER_TIMEFRAME`: 15 minutes
- `EXECUTION_TIMEFRAME`: 3 minutes

### Indicators
- `VWMA_LENGTH`: 20 (configurable)
- `SUPERTREND_PERIOD`: 10 (configurable)
- `SUPERTREND_MULTIPLIER`: 3.0 (configurable)

### Option Strike Selection
- `ITM_RANGE_MIN`: 20 points
- `ITM_RANGE_MAX`: 50 points
- `DELTA_MIN`: 0.55
- `DELTA_MAX`: 0.70
- `STRIKE_INTERVAL`: 50 points

### Risk Management
- `CAPITAL_PER_TRADE`: ₹50,000 (configurable)
- `MAX_POSITIONS`: 1
- `PARTIAL_TARGET_PERCENT`: 50%

### Backtesting
- `BACKTEST_START_DATE`: "2024-01-01"
- `BACKTEST_END_DATE`: "2026-08-07"

## 📊 Dashboard Features

The interactive dashboard provides:

- **Key Metrics**: Win rate, total P&L, avg win/loss
- **Equity Curve**: Cumulative P&L over time
- **Win Rate Analysis**: Overall, CALL, and PUT breakdown
- **P&L Distribution**: Histogram of trade outcomes
- **Trades Timeline**: Daily trade activity
- **Confidence Analysis**: Signal confidence vs actual performance
- **Trade Log**: Detailed table of all trades
- **Export**: Download results as CSV

## 🔔 Telegram Notification Examples

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

### Trade Exit
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

## ⚠️ Important Notes

### Data Limitations

- Yahoo Finance limits intraday data to ~60 days
- For longer backtests, the system uses daily data
- For production: Use NSE API or data provider with full history

### Option Price Simulation

- Current version uses simplified option pricing
- For production: Use historical option chain data or Black-Scholes

### System Rules (Non-Negotiable)

- ✓ Never repaint
- ✓ Never use future candles
- ✓ Never use lookahead
- ✓ Only closed candles evaluated
- ✓ Deterministic signals

## 🎨 Customization

All strategy parameters are configurable in `config.py`:

```python
# Example: Change VWMA length
VWMA_LENGTH = 30  # Default: 20

# Example: Adjust Supertrend
SUPERTREND_PERIOD = 14  # Default: 10
SUPERTREND_MULTIPLIER = 2.5  # Default: 3.0

# Example: Change target
PARTIAL_TARGET_PERCENT = 40  # Default: 50
```

## 🧪 Testing Individual Components

```bash
# Test data fetcher
python data_fetcher.py

# Test indicators
python indicators.py

# Test strategy
python strategy.py

# Test backtester
python backtester.py

# Test Telegram
python telegram_notifier.py
```

## 📈 Performance Metrics

The system calculates:

- **Win Rate**: Percentage of profitable trades
- **Total P&L**: Cumulative profit/loss
- **Average Win**: Mean profit per winning trade
- **Average Loss**: Mean loss per losing trade
- **CALL vs PUT**: Separate analysis by option type
- **Confidence Scoring**: Signal quality assessment

## 🔮 Future Enhancements

Planned features (architecture ready for plugin):

- [ ] Volume filters
- [ ] ATR filters
- [ ] Momentum filters
- [ ] Market structure analysis
- [ ] Liquidity filters
- [ ] Open interest data
- [ ] Option chain analysis
- [ ] AI confidence scoring
- [ ] Broker API integration
- [ ] Auto trading
- [ ] Trade journal
- [ ] Advanced analytics

## 🐛 Troubleshooting

### Issue: No data fetched
**Solution**: Check date range. Yahoo Finance limits intraday data to ~60 days.

### Issue: Telegram not working
**Solution**: 
1. Verify bot token and chat ID
2. Send `/start` to your bot on Telegram
3. Run `python main.py test-telegram`

### Issue: Dashboard won't start
**Solution**: 
1. Install Streamlit: `pip install streamlit`
2. Run manually: `streamlit run dashboard.py`

### Issue: Import errors
**Solution**: Install all dependencies: `pip install -r requirements.txt`

## 📝 License

This is proprietary trading software. Unauthorized distribution prohibited.

## 📧 Support

For questions or issues, refer to the inline code comments or configuration guide.

---

**Disclaimer**: This is a backtesting system for educational and research purposes. Past performance does not guarantee future results. Always test thoroughly before live trading.
