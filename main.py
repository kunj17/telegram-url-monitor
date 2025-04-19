import os
import json
import hashlib
import difflib
import asyncio
from datetime import datetime
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
import nest_asyncio

# === Load environment variables ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "local-debug")

# === File paths ===
DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"
DIFF_DIR = "diffs"
os.makedirs(DIFF_DIR, exist_ok=True)

# === Utility functions ===
def load_json(file):
    if os.path.exists(file):
        with open(file, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_json(data, file):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

# === Web page snapshot ===
async def get_page_text(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(5000)
            content = await page.content()
            await browser.close()
            return content.strip()
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
        return None

def get_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

# === URL Monitor ===
async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    urls = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)

    for label, url in urls.items():
        print(f"\n🔍 Checking [{label}]: {url}")
        content = await get_page_text(url)
        if content is None:
            continue

        new_hash = get_hash(content)
        old_hash = hashes.get(label)

        if old_hash != new_hash:
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            old_file = os.path.join(DIFF_DIR, f"{label}_old_{timestamp}.html")
            new_file = os.path.join(DIFF_DIR, f"{label}_new_{timestamp}.html")

            old_content = hashes.get(f"{label}_content", "")
            with open(old_file, 'w') as f:
                f.write(old_content)
            with open(new_file, 'w') as f:
                f.write(content)

            hashes[label] = new_hash
            hashes[f"{label}_content"] = content
            save_json(hashes, HASH_FILE)

            print("📤 Change detected. Saved diffs.")
            message = f"\U0001F514 *{label}* updated. View: {url}"
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        else:
            print("✅ No change detected.")

# === Bot Commands ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the URL Monitor Bot!\n"
        "Use /add <label> <url> to start monitoring.\n"
        "Use /list to see URLs. /remove <label> to stop."
    )

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add <label> <url>")
        return

    label, url = args[0], args[1]
    urls = load_json(DATA_FILE)
    if label in urls:
        await update.message.reply_text(f"⚠️ {label} already exists. Remove it first.")
        return

    content = await get_page_text(url)
    if content is None:
        await update.message.reply_text("❌ Couldn't fetch the URL.")
        return

    urls[label] = url
    save_json(urls, DATA_FILE)

    hashes = load_json(HASH_FILE)
    hashes[label] = get_hash(content)
    hashes[f"{label}_content"] = content
    save_json(hashes, HASH_FILE)

    await update.message.reply_text(f"✅ Monitoring *{label}*\n{url}", parse_mode="Markdown")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urls = load_json(DATA_FILE)
    if not urls:
        await update.message.reply_text("No URLs being monitored.")
        return
    text = '\n'.join([f"*{k}*: {v}" for k, v in urls.items()])
    await update.message.reply_text(text, parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remove <label>")
        return
    label = args[0]
    urls = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)

    if label in urls:
        del urls[label]
        hashes.pop(label, None)
        hashes.pop(f"{label}_content", None)
        save_json(urls, DATA_FILE)
        save_json(hashes, HASH_FILE)
        await update.message.reply_text(f"❌ Stopped monitoring {label}.")
    else:
        await update.message.reply_text("Label not found.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Try /add, /list, or /remove.")

# === Main Runner ===
async def run():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    app.job_queue.run_repeating(check_all_urls, interval=900, first=5)
    await app.run_polling()

if __name__ == "__main__":
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {GITHUB_REPOSITORY}")
    nest_asyncio.apply()

    try:
        asyncio.run(run())
    except RuntimeError as e:
        if "already running" in str(e):
            print("⚠️ Detected running event loop. Using loop.create_task().")
            loop = asyncio.get_event_loop()
            loop.create_task(run())
            loop.run_forever()
        else:
            raise
