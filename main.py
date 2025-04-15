import os
import json
import hashlib
import asyncio
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

# =============== ENV SETUP ===============
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
GH_PAT = os.getenv("GH_PAT")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"

# =============== FILE HELPERS ===============
def load_json(path):
    if not os.path.exists(path): return {}
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Warning: {path} is corrupted.")
        return {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# =============== GIT COMMIT ===============
def commit_and_push(message):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"], check=True)

        if not GH_PAT or not GITHUB_REPOSITORY:
            print("❌ GH_PAT or GITHUB_REPOSITORY missing.")
            return

        subprocess.run([
            "git", "remote", "set-url", "origin",
            f"https://x-access-token:{GH_PAT}@github.com/{GITHUB_REPOSITORY}.git"
        ], check=True)

        subprocess.run(["git", "add", DATA_FILE, HASH_FILE], check=True)
        subprocess.run(["git", "commit", "-m", message], check=False)
        subprocess.run(["git", "push"], check=False)
        print("✅ Pushed to GitHub.")
    except Exception as e:
        print(f"❌ Git push failed: {e}")

# =============== PAGE MONITORING ===============
async def get_rendered_hash(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(5000)  # Allow JS to run

            content = await page.content()
            print(f"\n🔍 Cleaned content preview:\n{content[:800]}...\n")

            await browser.close()
            return hashlib.sha256(content.encode()).hexdigest()
    except Exception as e:
        print(f"⚠️ Error rendering {url}: {e}")
        return None

async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)
    bot = context.bot

    for label, url in urls.items():
        new_hash = await get_rendered_hash(url)
        if new_hash is None:
            continue

        old_hash = hashes.get(label)
        status = "✅ SAME" if old_hash == new_hash else "❌ CHANGED"
        print(f"🔍 [{label}]\n  OLD: {old_hash}\n  NEW: {new_hash}\n  STATUS: {status}\n")

        if old_hash != new_hash:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* changed!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            save_json(HASH_FILE, hashes)
            commit_and_push("✅ Updated hash data")

# =============== TELEGRAM COMMANDS ===============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Use /add [label] [url] to monitor a page.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    data = load_json(DATA_FILE)
    if label in data:
        await update.message.reply_text("Label already exists.")
        return

    data[label] = url
    save_json(DATA_FILE, data)

    hash_val = await get_rendered_hash(url)
    if hash_val:
        hashes = load_json(HASH_FILE)
        hashes[label] = hash_val
        save_json(HASH_FILE, hashes)
        commit_and_push("✅ Updated URL data + hash")
        await update.message.reply_text(f"✅ Added: *{label}*", parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    label = args[0] if args else None
    if not label:
        await update.message.reply_text("Usage: /remove [label]")
        return

    data = load_json(DATA_FILE)
    if label not in data:
        await update.message.reply_text("Label not found.")
        return

    del data[label]
    save_json(DATA_FILE, data)

    hashes = load_json(HASH_FILE)
    if label in hashes:
        del hashes[label]
        save_json(HASH_FILE, hashes)

    commit_and_push("🗑️ Removed monitored URL")
    await update.message.reply_text(f"❌ Removed {label}.")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_json(DATA_FILE)
    if not data:
        await update.message.reply_text("No monitored URLs.")
        return

    msg = "\n".join([f"*{k}*: {v}" for k, v in data.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Try /add, /list or /remove.")

# =============== MAIN APP ===============
async def run_bot():
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {GITHUB_REPOSITORY}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("🕒 JobQueue found, setting up repeating check...")
    app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    await app.run_polling()

# =============== ENTRY POINT ===============
if __name__ == '__main__':
    try:
        asyncio.run(run_bot())
    except RuntimeError as e:
        if "already running" in str(e):
            print("⚠️ Already in an async loop, using existing loop.")
            loop = asyncio.get_event_loop()
            loop.create_task(run_bot())
            loop.run_forever()
        else:
            raise
