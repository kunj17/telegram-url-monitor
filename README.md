# DTProjectMonitorBot

This is a Telegram bot that monitors website pages for changes and sends notifications via Telegram.

## Features
- Add URLs to monitor with labels
- Check every 15 minutes for changes
- Telegram alert when content updates
- Manage everything via Telegram chat

## Commands
- `/add [label] [url]` – Start monitoring a webpage
- `/list` – List all monitored URLs
- `/remove [label]` – Stop monitoring a label

## Setup

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Get your `TELEGRAM_TOKEN` and `CHAT_ID` (use @userinfobot)
3. Create a `.env` file:

