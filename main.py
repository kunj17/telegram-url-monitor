import json
import hashlib
import os
import subprocess
import asyncio
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
DATA_FILE = 'urls.json'
HASH_FILE = 'url_hashes.json'

# ==== STORAGE HELPERS ====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ {DATA_FILE} is invalid. Reinitializing.")
        return {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    commit_and_push_changes("✅ Updated URL data")

def load_hashes():
    if not os.path.exists(HASH_FILE):
        return {}
    try:
        with open(HASH_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ {HASH_FILE} is invalid. Reinitializing.")
        return {}

def save_hashes(hashes):
    with open(HASH_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)
    commit_and_push_changes("✅ Updated hash data")

# ==== GIT COMMIT FUNCTION ====
def commit_and_push_changes(message):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"], check=True)
        repo = os.getenv("GITHUB_REPOSITORY")
        token = os.getenv("GH_PAT")

        subprocess.run([
            "git", "remote", "set-url", "origin",
            f"https://x-access-token:{token}@github.com/{repo}.git"
        ], check=True)

        subprocess.run(["git", "add", DATA_FILE, HASH_FILE], check=True)
        subprocess.run(["git", "commit", "-m", message], check=False)
        subprocess.run(["git", "push"], check=True)

        print("✅ Pushed to GitHub successfully.")
    except Exception as e:
        print(f"❌ Git commit/push failed: {e}")

# ==== FETCH AND COMPARE ====
async def get_page_content(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(7000)
            content = await page.content()
            await browser.close()
            return content
    except Exception as e:
        print(f"❌ Failed to fetch {url}: {e}")
        return None

async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_data()
    hashes = load_hashes()
    bot = context.bot

    for label, url in urls.items():
        content = await get_page_content(url)
        if not content:
            continue

        new_hash = hashlib.sha256(content.encode()).hexdigest()
        old_hash = hashes.get(label)
        print(f"🔍 [{label}]\n  OLD: {old_hash}\n  NEW: {new_hash}\n  STATUS: {'✅ SAME' if old_hash == new_hash else '❌ DIFFERENT'}")

        if new_hash != old_hash:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* changed!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            save_hashes(hashes)

# ==== TELEGRAM COMMANDS ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /add [label] [url] to begin monitoring.")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    data = load_data()
    if label in data:
        await update.message.reply_text("Label already exists. Use /remove to delete it first.")
        return

    data[label] = url
    save_data(data)

    content = await get_page_content(url)
    if content:
        hash_val = hashlib.sha256(content.encode()).hexdigest()
        hashes = load_hashes()
        hashes[label] = hash_val
        save_hashes(hashes)

    await update.message.reply_text(f"✅ Added: *{label}*\n{url}", parse_mode="Markdown")

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

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        await update.message.reply_text("No URLs currently monitored.")
        return

    msg = "\n".join([f"*{label}*: {url}" for label, url in data.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unrecognized command. Use /add, /remove, or /list.")

# ==== MAIN FUNCTION ====
async def main():
    print("🚀 Bot starting up...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue:
        app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    try:
        await app.run_polling()
    finally:
        print("📦 Finalizing... committing any unsaved state")
        commit_and_push_changes("🤖 Final auto-persist on workflow shutdown")

# ==== ENTRY POINT ====
if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            print("⚠️ Event loop is running. Running using create_task...")
            loop.create_task(main())
        else:
            loop.run_until_complete(main())
    except RuntimeError:
        asyncio.run(main())
