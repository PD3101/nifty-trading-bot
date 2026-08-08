#!/bin/bash

# Quick Deploy Script for NIFTY Trading Bot
# Makes deployment to cloud platforms super easy

set -e

echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║       NIFTY OPTIONS TRADING BOT - QUICK DEPLOY              ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if we're in the right directory
if [ ! -f "cloud_bot.py" ]; then
    echo "❌ Error: Please run this script from the nifty-options-backtester directory"
    exit 1
fi

echo "📋 Deployment Options:"
echo ""
echo "1. Railway.app (Recommended - Easiest)"
echo "2. Render.com (750 hours free/month)"
echo "3. PythonAnywhere (Free forever)"
echo "4. Test Locally First"
echo "5. Setup Telegram Bot"
echo ""
read -p "Choose option (1-5): " choice

case $choice in
    1)
        echo ""
        echo "🚀 Deploying to Railway.app..."
        echo ""
        echo "Steps to follow:"
        echo "1. Create GitHub repo (if not done):"
        echo "   git init"
        echo "   git add ."
        echo "   git commit -m 'Deploy NIFTY trading bot'"
        echo "   # Create repo on github.com, then:"
        echo "   git remote add origin https://github.com/YOUR_USERNAME/nifty-trading-bot.git"
        echo "   git push -u origin main"
        echo ""
        echo "2. Go to https://railway.app"
        echo "3. Click 'Deploy from GitHub'"
        echo "4. Select your repo"
        echo "5. Add environment variables:"
        echo "   TELEGRAM_BOT_TOKEN = your_token"
        echo "   TELEGRAM_CHAT_ID = your_chat_id"
        echo ""
        echo "✅ Bot will start automatically!"
        ;;

    2)
        echo ""
        echo "🚀 Deploying to Render.com..."
        echo ""
        echo "Steps to follow:"
        echo "1. Push to GitHub (same as Railway)"
        echo "2. Go to https://render.com"
        echo "3. New + → Background Worker"
        echo "4. Connect GitHub repo"
        echo "5. Configure:"
        echo "   - Build: pip install -r requirements.txt"
        echo "   - Start: python3 cloud_bot.py"
        echo "6. Add environment variables"
        echo ""
        echo "✅ Bot will start automatically!"
        ;;

    3)
        echo ""
        echo "🚀 Deploying to PythonAnywhere..."
        echo ""
        echo "Steps to follow:"
        echo "1. Sign up at https://www.pythonanywhere.com"
        echo "2. In console, run:"
        echo "   git clone https://github.com/YOUR_USERNAME/nifty-trading-bot.git"
        echo "   cd nifty-trading-bot"
        echo "   pip3 install --user -r requirements.txt"
        echo "3. Set environment variables in ~/.bashrc"
        echo "4. Tasks tab → Create new task → python3 cloud_bot.py"
        echo ""
        echo "✅ Bot will run 24/7!"
        ;;

    4)
        echo ""
        echo "🧪 Testing bot locally..."
        echo ""

        # Check Telegram config
        if ! grep -q "TELEGRAM_BOT_TOKEN" config.py; then
            echo "⚠️  Warning: Telegram not configured in config.py"
            echo ""
            read -p "Do you have your Telegram bot token? (y/n): " has_token

            if [ "$has_token" = "y" ]; then
                read -p "Enter bot token: " bot_token
                read -p "Enter chat ID: " chat_id

                echo "" >> config.py
                echo "# Telegram Configuration" >> config.py
                echo "TELEGRAM_BOT_TOKEN = \"$bot_token\"" >> config.py
                echo "TELEGRAM_CHAT_ID = \"$chat_id\"" >> config.py

                echo "✅ Telegram configured!"
            else
                echo ""
                echo "Run this first: python3 telegram_notifier.py"
                echo "It will show you how to set up Telegram"
                exit 0
            fi
        fi

        echo ""
        echo "Starting bot locally..."
        echo "Press Ctrl+C to stop"
        echo ""
        python3 cloud_bot.py
        ;;

    5)
        echo ""
        echo "📱 Setting up Telegram Bot..."
        echo ""
        python3 telegram_notifier.py
        ;;

    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "Need help? Check these files:"
echo "  - CLOUD_DEPLOY.md (detailed cloud deployment guide)"
echo "  - QUICKSTART.md (quick start guide)"
echo "  - README.md (complete documentation)"
echo "═══════════════════════════════════════════════════════════════"
