# main.py
import os
import json
import hashlib
import subprocess
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from playwright.async_api import async_playwright

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
GH_PAT = os.getenv("GH_PAT")
REPO = os.getenv("GITHUB_REPOSITORY")

DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"

# ---------- Utils ----------
def load_json(file):
    return json.load(open(file)) if os.path.exists(file) else {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

def commit_and_push(msg):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@ci"], check=True)
        subprocess.run([
            "git", "remote", "set-url", "origin",
            f"https://x-access-token:{GH_PAT}@github.com/{REPO}.git"
        ], check=True)
        subprocess.run(["git", "add", DATA_FILE, HASH_FILE], check=True)
        subprocess.run(["git", "commit", "-m", msg], check=False)
        subprocess.run(["git", "push"], check=False)
        print("✅ Pushed to GitHub")
    except Exception as e:
        print(f"❌ Git error: {e}")

# ---------- Core Monitoring ----------
async def get_hash(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(5000)
            html = await page.content()
            await browser.close()
            return hashlib.sha256(html.encode()).hexdigest()
    except Exception as e:
        print(f"⚠️ Error fetching {url}: {e}")
        return None

async def check_all(context: ContextTypes.DEFAULT_TYPE):
    urls = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)
    bot = context.bot

    for label, url in urls.items():
        new_hash = await get_hash(url)
        if not new_hash:
            continue

        old_hash = hashes.get(label)
        changed = old_hash != new_hash

        print(f"🔍 {label} — Match: {not changed}")
        if changed:
            await bot.send_message(chat_id=CHAT_ID, text=f"🔔 {label} changed!\n{url}")
            hashes[label] = new_hash
            save_json(HASH_FILE, hashes)
            commit_and_push("🔁 Updated hash")

# ---------- Bot Commands ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Ready! Use /add [label] [url]")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("Usage: /add [label] [url]")

    label, url = args[0], args[1]
    data = load_json(DATA_FILE)
    if label in data:
        return await update.message.reply_text("Label already exists!")

    data[label] = url
    save_json(DATA_FILE, data)

    new_hash = await get_hash(url)
    if new_hash:
        hashes = load_json(HASH_FILE)
        hashes[label] = new_hash
        save_json(HASH_FILE, hashes)
        commit_and_push("➕ New URL added")
        await update.message.reply_text(f"✅ Monitoring {label}")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    label = context.args[0] if context.args else None
    data = load_json(DATA_FILE)

    if label not in data:
        return await update.message.reply_text("Label not found!")

    del data[label]
    save_json(DATA_FILE, data)

    hashes = load_json(HASH_FILE)
    if label in hashes:
        del hashes[label]
        save_json(HASH_FILE, hashes)

    commit_and_push("❌ Removed URL")
    await update.message.reply_text(f"❌ Removed {label}")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_json(DATA_FILE)
    if not data:
        return await update.message.reply_text("No URLs are being tracked.")
    await update.message.reply_text("\n".join(f"{k}: {v}" for k, v in data.items()))

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unrecognized command. Try /add or /list.")

# ---------- App Setup ----------
async def run_async_bot():
    print("🚀 Bot starting up...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("🕒 JobQueue found, setting up repeating check...")
    app.job_queue.run_repeating(check_all, interval=900, first=5)

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()
    await app.stop()
    await app.shutdown()

# ---------- Entrypoint ----------
if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(run_async_bot())
        loop.run_forever()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
