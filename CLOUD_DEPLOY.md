# 🚀 CLOUD DEPLOYMENT GUIDE
# Deploy Your NIFTY Trading Bot to Run 24/7 (FREE)

## ✅ What You'll Get

- **24/7 Operation** - Runs in the cloud, not on your laptop
- **Auto-Restart** - Recovers from failures automatically
- **Live Monitoring** - Scans NIFTY every minute during market hours
- **Telegram Alerts** - Get notifications anywhere
- **Zero Maintenance** - Set it and forget it

---

## 🎯 OPTION 1: Railway.app (RECOMMENDED - Easiest)

### Why Railway?
- ✅ **$5 free credit/month** (enough for this bot)
- ✅ **One-click deploy from GitHub**
- ✅ **Auto-restart on failures**
- ✅ **Easy environment variables**

### Setup Steps (5 minutes)

#### 1. Create GitHub Repository
```bash
cd ~/nifty-options-backtester

# Initialize git (if not already)
git init
git add .
git commit -m "Initial commit - NIFTY trading bot"

# Create repo on GitHub and push
# Go to github.com, create new repo, then:
git remote add origin https://github.com/YOUR_USERNAME/nifty-trading-bot.git
git branch -M main
git push -u origin main
```

#### 2. Deploy to Railway
1. Go to **https://railway.app**
2. Click **"Start a New Project"**
3. Select **"Deploy from GitHub repo"**
4. Connect your GitHub account
5. Select **nifty-trading-bot** repository
6. Click **"Deploy Now"**

#### 3. Add Environment Variables
In Railway dashboard:
1. Click on your project
2. Go to **"Variables"** tab
3. Add these:
   ```
   TELEGRAM_BOT_TOKEN = your_bot_token_here
   TELEGRAM_CHAT_ID = your_chat_id_here
   ```
4. Click **"Save"**

#### 4. Done! 🎉
- Bot will automatically start
- You'll receive a Telegram message confirming it's running
- It will now monitor markets 24/7 and send you signals

---

## 🎯 OPTION 2: Render.com (Also FREE)

### Why Render?
- ✅ **750 hours/month free** (more than enough)
- ✅ **Easy deployment**
- ✅ **Reliable uptime**

### Setup Steps

#### 1. Push to GitHub (same as Railway option 1)

#### 2. Deploy to Render
1. Go to **https://render.com**
2. Click **"New +"** → **"Background Worker"**
3. Connect your GitHub repo
4. Configure:
   - **Name**: nifty-trading-bot
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python3 cloud_bot.py`
   - **Plan**: Free

#### 3. Add Environment Variables
1. Scroll to **"Environment Variables"**
2. Add:
   ```
   TELEGRAM_BOT_TOKEN = your_bot_token_here
   TELEGRAM_CHAT_ID = your_chat_id_here
   ```

#### 4. Click "Create Background Worker"
Done! Bot is now running 24/7.

---

## 🎯 OPTION 3: PythonAnywhere (FREE Forever)

### Why PythonAnywhere?
- ✅ **Free forever plan**
- ✅ **No credit card needed**
- ✅ **Simple setup**

### Setup Steps

#### 1. Create Account
Go to **https://www.pythonanywhere.com** and sign up for free

#### 2. Upload Files
1. Go to **"Files"** tab
2. Click **"Upload a file"**
3. Upload all `.py` files from your project

Or use Git:
```bash
# In PythonAnywhere console
git clone https://github.com/YOUR_USERNAME/nifty-trading-bot.git
cd nifty-trading-bot
```

#### 3. Install Dependencies
In PythonAnywhere console:
```bash
pip3 install --user -r requirements.txt
```

#### 4. Set Environment Variables
Edit `~/.bashrc`:
```bash
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

#### 5. Create Always-On Task
1. Go to **"Tasks"** tab
2. Create new task
3. Command: `python3 /home/YOUR_USERNAME/nifty-trading-bot/cloud_bot.py`
4. Frequency: Daily
5. Click **"Create"**

---

## 📱 Setting Up Telegram (If Not Done Yet)

### Quick Setup (2 minutes)

#### Step 1: Create Bot
1. Open Telegram
2. Search: `@BotFather`
3. Send: `/newbot`
4. Follow instructions
5. **Copy the bot token**

#### Step 2: Get Chat ID
1. Search: `@userinfobot`
2. Send: `/start`
3. **Copy your chat ID**

#### Step 3: Start Chat with Your Bot
1. Search for your bot by username
2. Send: `/start`
3. This activates the bot

---

## ✅ Verification

After deployment, you should receive:

```
🚀 CLOUD BOT STARTED

✅ Running 24/7 on cloud
📊 Monitoring NIFTY markets
📱 Telegram alerts enabled

You will receive signals automatically during market hours
```

If you don't receive this:
1. Check environment variables are set correctly
2. Check bot logs in your cloud platform dashboard
3. Verify you sent `/start` to your Telegram bot

---

## 🔔 What Happens Now?

### During Market Hours (9:15 AM - 3:30 PM IST)
- Bot scans NIFTY every minute
- Calculates indicators (VWAP, VWMA, Supertrend)
- Generates signals when conditions meet
- Sends instant Telegram alerts

### Outside Market Hours
- Bot stays alive but doesn't scan
- Waits for next market open
- Sends heartbeat every 6 hours to confirm it's running

### When Signal Generated
You'll receive:
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

---

## 🎮 Managing Your Bot

### View Logs
- **Railway**: Dashboard → Logs tab
- **Render**: Dashboard → Logs
- **PythonAnywhere**: Files → cloud_bot.log

### Stop Bot
- **Railway**: Dashboard → Settings → Delete service
- **Render**: Dashboard → Delete service
- **PythonAnywhere**: Tasks → Delete task

### Restart Bot
- **Railway**: Dashboard → Deploy → Manual deploy
- **Render**: Dashboard → Manual deploy
- **PythonAnywhere**: Tasks → Run now

---

## 🆘 Troubleshooting

### Issue: Not receiving messages
**Solution:**
1. Check environment variables are correct
2. Send `/start` to your bot on Telegram
3. Check logs for errors

### Issue: Bot keeps restarting
**Solution:**
1. Check logs for error messages
2. Verify data source is working (Yahoo Finance)
3. Check if market is actually open

### Issue: Bot stopped after some time
**Solution:**
- Railway: Check free credit balance
- Render: Check free hours remaining (750/month)
- PythonAnywhere: Restart the task

---

## 💡 Pro Tips

### 1. Monitor Bot Health
Bot sends heartbeat every 6 hours. If you don't receive it, check the cloud dashboard.

### 2. Test First
Before relying on it, monitor for a few days to ensure signals match your expectations.

### 3. Backup Configuration
Save your bot token and chat ID somewhere safe.

### 4. Check Logs Regularly
First few days, check logs to ensure everything is working smoothly.

---

## 🔄 Updates

To update the bot after changes:

### If using GitHub + Railway/Render
```bash
# Make changes locally
git add .
git commit -m "Update bot"
git push

# Railway/Render will auto-deploy
```

### If using PythonAnywhere
```bash
# In PythonAnywhere console
cd nifty-trading-bot
git pull
# Restart the task
```

---

## 📊 Cost Breakdown

### Railway.app
- **Free tier**: $5 credit/month
- **This bot usage**: ~$2-3/month
- **Total**: FREE (within free credit)

### Render.com
- **Free tier**: 750 hours/month
- **This bot usage**: 720 hours/month (24/7)
- **Total**: FREE

### PythonAnywhere
- **Free tier**: Forever free
- **Limitations**: One always-on task
- **Total**: FREE

**All options are completely FREE for this bot!**

---

## 🎯 Next Steps

1. **Choose a platform** (Railway recommended)
2. **Deploy in 5 minutes**
3. **Receive your first signal**
4. **Relax** - bot runs 24/7 automatically

---

## ⚡ Quick Deploy (Copy-Paste Commands)

### For Railway/Render:
```bash
cd ~/nifty-options-backtester
git init
git add .
git commit -m "Deploy NIFTY trading bot"
# Push to GitHub, then deploy via web dashboard
```

### For PythonAnywhere:
```bash
# In PythonAnywhere console
git clone https://github.com/YOUR_USERNAME/nifty-trading-bot.git
cd nifty-trading-bot
pip3 install --user -r requirements.txt
python3 cloud_bot.py
```

---

**You're now ready to deploy! Choose your platform and follow the steps above.**

Any questions during deployment, just ask! 🚀
