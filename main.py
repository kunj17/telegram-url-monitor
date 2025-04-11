import json
import hashlib
import os
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    JobQueue,
)
from dotenv import load_dotenv

load_dotenv()

# === CONFIG ===
TELEGRAM_TOKEN = "7935964890:AAH__dT03uCuPDr4ht8CNJ7_7nL5yb6Ukig"
CHAT_ID = 1002644823532
DATA_FILE = 'urls.json'
HASH_FILE = 'url_hashes.json'

# =============== STORAGE HELPERS ===============
def load_data():
    return json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_hashes():
    return json.load(open(HASH_FILE)) if os.path.exists(HASH_FILE) else {}

def save_hashes(hashes):
    with open(HASH_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)

# =============== MONITORING LOGIC ===============
def get_page_hash(url: str) -> str | None:
    try:
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, 'html.parser')
        return hashlib.sha256(soup.get_text().encode()).hexdigest()
    except Exception:
        return None

async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_data()
    hashes = load_hashes()
    updated = False
    bot = context.bot
    chat_id = CHAT_ID

    for label, url in urls.items():
        new_hash = get_page_hash(url)
        if new_hash is None:
            continue

        if hashes.get(label) != new_hash:
            await bot.send_message(
                chat_id=chat_id,
                text=f"🔔 *{label}* has been updated!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            updated = True

    if updated:
        save_hashes(hashes)

# =============== TELEGRAM COMMANDS ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Welcome! Use /add [label] [url] to begin monitoring pages.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    data = load_data()

    if label in data:
        await update.message.reply_text(f"{label} already exists. Use /remove to delete first.")
        return

    data[label] = url
    save_data(data)

    hash_val = get_page_hash(url)
    if hash_val:
        hashes = load_hashes()
        hashes[label] = hash_val
        save_hashes(hashes)

    await update.message.reply_text(f"✅ Added: *{label}*\n{url}", parse_mode="Markdown")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No URLs are currently being monitored.")
        return

    msg = "\n".join([f"*{label}*: {url}" for label, url in data.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remove [label]")
        return

    label = args[0]
    data = load_data()

    if label not in data:
        await update.message.reply_text(f"No such label: {label}")
        return

    del data[label]
    save_data(data)

    hashes = load_hashes()
    if label in hashes:
        del hashes[label]
        save_hashes(hashes)

    await update.message.reply_text(f"❌ Removed {label}.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Command not recognized. Use /add, /remove, or /list.")

# =============== MAIN APP ===============
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    # ✅ Run job queue task ONLY if job queue exists
    if app.job_queue:
        app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    app.run_polling()

if __name__ == '__main__':
    main()

