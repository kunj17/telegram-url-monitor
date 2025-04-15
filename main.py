import json
import os
import hashlib
import subprocess
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
GH_PAT = os.getenv("GH_PAT")

DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"

# ==== STORAGE ====
def load_json(filename):
    if not os.path.exists(filename):
        return {}
    try:
        with open(filename) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Warning: {filename} is invalid JSON. Resetting.")
        return {}

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

# ==== COMMIT CHANGES ====
def commit_and_push(message):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"], check=True)
        subprocess.run(["git", "add", DATA_FILE, HASH_FILE], check=True)
        subprocess.run(["git", "commit", "-m", message], check=False)
        subprocess.run([
            "git", "remote", "set-url", "origin",
            f"https://x-access-token:{GH_PAT}@github.com/{GITHUB_REPOSITORY}.git"
        ], check=True)
        subprocess.run(["git", "push"], check=False)
        print("✅ Pushed to GitHub successfully.")
    except Exception as e:
        print(f"❌ Commit/Push failed: {e}")

# ==== FETCH AND HASH PAGE ====
async def get_rendered_page_hash(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(5000)
            content = await page.content()
            soup = BeautifulSoup(content, "html.parser")
            text = soup.get_text(separator="\n", strip=True)
            await browser.close()
            return hashlib.sha256(text.encode()).hexdigest(), text[:500]
    except Exception as e:
        print(f"⚠️ Error fetching {url}: {e}")
        return None, None

# ==== JOB CHECK ====
async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    print("🔍 Starting scheduled check_all_urls...")
    data = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)
    updated = False

    for label, url in data.items():
        new_hash, preview = await get_rendered_page_hash(url)
        old_hash = hashes.get(label)

        if new_hash is None:
            print(f"❌ Could not hash {label}")
            continue

        status = "✅ MATCH" if new_hash == old_hash else "❌ DIFFERENT"
        print(f"🔍 [{label}]\n  OLD: {old_hash}\n  NEW: {new_hash}\n  STATUS: {status}\n  PREVIEW: {preview}\n")

        if new_hash != old_hash:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* changed!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            updated = True

    if updated:
        save_json(HASH_FILE, hashes)
        commit_and_push("✅ Updated hash data")

# ==== TELEGRAM COMMANDS ====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Use /add [label] [url], /list, or /remove [label]")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return
    label, url = args[0], args[1]
    data = load_json(DATA_FILE)
    if label in data:
        await update.message.reply_text(f"{label} already exists.")
        return
    data[label] = url
    save_json(DATA_FILE, data)

    hash_val, _ = await get_rendered_page_hash(url)
    if hash_val:
        hashes = load_json(HASH_FILE)
        hashes[label] = hash_val
        save_json(HASH_FILE, hashes)
        commit_and_push("✅ Added new URL and hash")

    await update.message.reply_text(f"✅ Added *{label}*", parse_mode="Markdown")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_json(DATA_FILE)
    if not data:
        await update.message.reply_text("📭 No URLs are currently being monitored.")
        return
    msg = "\n".join([f"*{label}*: {url}" for label, url in data.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /remove [label]")
        return
    label = args[0]
    data = load_json(DATA_FILE)
    if label not in data:
        await update.message.reply_text(f"No such label: {label}")
        return
    del data[label]
    save_json(DATA_FILE, data)

    hashes = load_json(HASH_FILE)
    if label in hashes:
        del hashes[label]
        save_json(HASH_FILE, hashes)

    commit_and_push("🗑️ Removed URL and hash")
    await update.message.reply_text(f"❌ Removed {label}")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Command not recognized.")

# ==== ENTRY ====
async def run_bot():
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {GITHUB_REPOSITORY}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue:
        print("🕒 JobQueue found, setting up repeating check...")
        app.job_queue.run_repeating(check_all_urls, interval=900, first=5)

    await app.run_polling()

# ==== MAIN ====
if __name__ == "__main__":
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(run_bot())
        else:
            loop.run_until_complete(run_bot())
    except RuntimeError:
        asyncio.run(run_bot())
