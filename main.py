import json
import hashlib
import os
import subprocess
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from playwright.async_api import async_playwright
import asyncio

load_dotenv()

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
DATA_FILE = 'urls.json'
HASH_FILE = 'url_hashes.json'

# =============== STORAGE HELPERS ===============
def load_data():
    if not os.path.exists(DATA_FILE): return {}
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Invalid JSON in {DATA_FILE}, resetting.")
        return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    commit_and_push_changes("✅ Updated URL data")

def load_hashes():
    if not os.path.exists(HASH_FILE): return {}
    try:
        with open(HASH_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Invalid JSON in {HASH_FILE}, resetting.")
        return {}

def save_hashes(hashes):
    with open(HASH_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)
    commit_and_push_changes("✅ Updated hash data")

# =============== GIT AUTO COMMIT ===============
def commit_and_push_changes(message):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"], check=True)

        repo = os.getenv("GITHUB_REPOSITORY")
        token = os.getenv("GH_PAT")
        if not token or not repo:
            print("❌ GH_PAT or GITHUB_REPOSITORY missing")
            return

        subprocess.run(["git", "remote", "set-url", "origin",
            f"https://x-access-token:{token}@github.com/{repo}.git"], check=True)

        subprocess.run(["git", "add", DATA_FILE, HASH_FILE], check=True)
        subprocess.run(["git", "commit", "-m", message], check=False)
        subprocess.run(["git", "push"], check=True)
        print("✅ Pushed to GitHub successfully.")
    except Exception as e:
        print(f"❌ Commit failed: {e}")

# =============== MONITORING ===============
async def get_page_hash_async(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=15000)
            await page.wait_for_timeout(5000)
            content = await page.content()
            await browser.close()
            return hashlib.sha256(content.encode()).hexdigest(), content[:800]  # Return preview too
    except Exception as e:
        print(f"⚠️ Error fetching {url}: {e}")
        return None, None

async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_data()
    hashes = load_hashes()
    bot = context.bot

    for label, url in urls.items():
        new_hash, preview = await get_page_hash_async(url)
        if new_hash is None:
            continue

        old_hash = hashes.get(label)
        match = old_hash == new_hash

        print(f"\n🔍 [{label}]\n  OLD: {old_hash}\n  NEW: {new_hash}\n  STATUS: {'✅ MATCH' if match else '❌ DIFFERENT'}")
        print(f"🔍 Cleaned content preview:\n{preview}\n")

        if not match:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* changed!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            save_hashes(hashes)

    print("✅ check_all_urls executed")

# =============== TELEGRAM COMMANDS ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /add [label] [url] to monitor a page.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    data = load_data()
    if label in data:
        await update.message.reply_text(f"{label} already exists.")
        return

    data[label] = url
    save_data(data)

    hash_val, _ = await get_page_hash_async(url)
    if hash_val:
        hashes = load_hashes()
        hashes[label] = hash_val
        save_hashes(hashes)

    await update.message.reply_text(f"✅ Added: *{label}*\n{url}", parse_mode="Markdown")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        await update.message.reply_text("No URLs monitored.")
        return

    msg = "\n".join([f"*{label}*: {url}" for label, url in data.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
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
    await update.message.reply_text("Unknown command. Use /add, /remove, or /list.")

# =============== MAIN APP ===============
async def main():
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {os.getenv('GITHUB_REPOSITORY')}")
    print("Polling started...\n")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue:
        print("🕒 JobQueue found, setting up repeating check...")
        app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    await app.run_polling()
    print("📦 Finalizing... committing any unsaved state")
    commit_and_push_changes("🤖 Final auto-persist on shutdown")

# =============== BOOTSTRAP ===============
if __name__ == '__main__':
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(main())
        else:
            loop.run_until_complete(main())
    except RuntimeError:
        asyncio.run(main())
