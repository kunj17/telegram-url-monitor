import json
import hashlib
import os
import subprocess
import asyncio
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
DATA_FILE = 'urls.json'
HASH_FILE = 'url_hashes.json'

# === STORAGE ===
def load_data():
    if not os.path.exists(DATA_FILE): return {}
    try:
        with open(DATA_FILE) as f: return json.load(f)
    except json.JSONDecodeError:
        print("⚠️ Invalid urls.json, resetting.")
        return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f: json.dump(data, f, indent=2)
    commit_and_push("✅ Updated URL data")

def load_hashes():
    if not os.path.exists(HASH_FILE): return {}
    try:
        with open(HASH_FILE) as f: return json.load(f)
    except json.JSONDecodeError:
        print("⚠️ Invalid url_hashes.json, resetting.")
        return {}

def save_hashes(hashes):
    with open(HASH_FILE, 'w') as f: json.dump(hashes, f, indent=2)
    commit_and_push("✅ Updated hash data")

# === COMMIT ===
def commit_and_push(msg):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"], check=True)

        repo = os.getenv("GITHUB_REPOSITORY")
        token = os.getenv("GH_PAT")
        if not token or not repo:
            print("❌ GH_PAT or GITHUB_REPOSITORY missing.")
            return

        subprocess.run(["git", "remote", "set-url", "origin",
                        f"https://x-access-token:{token}@github.com/{repo}.git"], check=True)

        subprocess.run(["git", "add", DATA_FILE, HASH_FILE], check=True)
        subprocess.run(["git", "commit", "-m", msg], check=False)
        subprocess.run(["git", "push"], check=False)
        print("✅ Git commit & push done.")
    except Exception as e:
        print(f"❌ Git commit failed: {e}")

# === RENDERED CONTENT ===
async def get_rendered_hash(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(7000)
            content = await page.content()
            await browser.close()
            return hashlib.sha256(content.encode()).hexdigest()
    except Exception as e:
        print(f"⚠️ Error rendering {url}: {e}")
        return None

# === URL CHECK ===
async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_data()
    hashes = load_hashes()
    bot = context.bot

    for label, url in urls.items():
        new_hash = await get_rendered_hash(url)
        if new_hash is None:
            print(f"❌ Failed: {label} - {url}")
            continue

        old_hash = hashes.get(label)
        print(f"🔍 [{label}]\nOLD: {old_hash}\nNEW: {new_hash}")
        if old_hash != new_hash:
            await bot.send_message(chat_id=CHAT_ID, text=f"🔔 *{label}* changed!\n{url}", parse_mode="Markdown")
            hashes[label] = new_hash
            save_hashes(hashes)
    print("✅ URL check complete\n")

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Welcome! Use /add [label] [url] to begin monitoring.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    data = load_data()
    if label in data:
        await update.message.reply_text(f"{label} already exists. Use /remove to delete first.")
        return

    data[label] = url
    save_data(data)
    hash_val = await get_rendered_hash(url)
    if hash_val:
        hashes = load_hashes()
        hashes[label] = hash_val
        save_hashes(hashes)
    await update.message.reply_text(f"✅ Monitoring: *{label}*\n{url}", parse_mode="Markdown")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        await update.message.reply_text("No URLs are being monitored.")
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
    if update.message:
        await update.message.reply_text("Command not recognized. Use /add, /remove, or /list.")

# === MAIN ===
def main():
    print("🚀 Bot initializing...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue:
        print("⏱️ Scheduling regular checks...")
        app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    try:
        app.run_polling()
    finally:
        print("📦 Shutting down. Saving data...")
        commit_and_push("🤖 Final save on exit")

if __name__ == '__main__':
    main()
