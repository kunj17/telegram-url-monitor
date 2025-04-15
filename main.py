import os
import json
import hashlib
import difflib
import asyncio
import nest_asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)
from playwright.async_api import async_playwright

# === CONFIGURATION ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "unknown")
DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"
DIFF_DIR = "diffs"

os.makedirs(DIFF_DIR, exist_ok=True)

# === STORAGE ===
def load_json(file):
    if not os.path.exists(file):
        return {}
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_json(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

# === FETCH PAGE CONTENT ===
async def fetch_page_content(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(5000)
            content = await page.content()
            await browser.close()
            return content.strip()
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
        return None

# === HASHING ===
def compute_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

# === DIFFERENCE DETECTION ===
def save_diff(label, old_text, new_text):
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    diff_path = os.path.join(DIFF_DIR, f"{label}_{timestamp}.diff")
    with open(diff_path, 'w') as f:
        diff = difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile='old',
            tofile='new',
            lineterm=''
        )
        f.write('\n'.join(diff))
    return diff_path

# === CHECK ALL URLS ===
async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    print("\n🔍 Starting scheduled check...")
    urls = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)

    for label, url in urls.items():
        print(f"\n🌐 Checking: {label} -> {url}")
        content = await fetch_page_content(url)
        if content is None:
            continue

        new_hash = compute_hash(content)
        old_hash = hashes.get(label)

        if old_hash != new_hash:
            print(f"🔔 Change detected in: {label}")
            old_content_path = os.path.join(DIFF_DIR, f"{label}_previous.html")
            with open(old_content_path, 'w') as f:
                f.write(content)

            previous_text = ""
            if old_hash and os.path.exists(old_content_path):
                with open(old_content_path, 'r') as f:
                    previous_text = f.read()

            diff_file = save_diff(label, previous_text, content)

            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔄 *{label}* has changed!\nURL: {url}\nDiff saved to: `{diff_file}`",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            save_json(HASH_FILE, hashes)
        else:
            print(f"✅ No change in: {label}")

# === TELEGRAM HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to URL Monitor Bot!\n"
        "Commands:\n"
        "/add [label] [url] - Monitor a new page\n"
        "/remove [label] - Stop monitoring\n"
        "/list - List all monitored pages"
    )

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return
    label, url = args
    urls = load_json(DATA_FILE)
    if label in urls:
        await update.message.reply_text("That label already exists.")
        return
    urls[label] = url
    save_json(DATA_FILE, urls)
    content = await fetch_page_content(url)
    if content:
        hashes = load_json(HASH_FILE)
        hashes[label] = compute_hash(content)
        save_json(HASH_FILE, hashes)
    await update.message.reply_text(f"✅ Monitoring started for *{label}*", parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /remove [label]")
        return
    label = args[0]
    urls = load_json(DATA_FILE)
    if label in urls:
        del urls[label]
        save_json(DATA_FILE, urls)
        hashes = load_json(HASH_FILE)
        hashes.pop(label, None)
        save_json(HASH_FILE, hashes)
        await update.message.reply_text(f"🗑️ Removed monitoring for {label}.")
    else:
        await update.message.reply_text("Label not found.")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urls = load_json(DATA_FILE)
    if not urls:
        await update.message.reply_text("No URLs currently being monitored.")
        return
    message = "\n".join([f"*{k}*: {v}" for k, v in urls.items()])
    await update.message.reply_text(message, parse_mode="Markdown")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /start to see options.")

# === MAIN ===
async def run_async_bot():
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {GITHUB_REPOSITORY}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    app.job_queue.run_repeating(check_all_urls, interval=900, first=5)

    await app.run_polling()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    nest_asyncio.apply(loop)
    loop.run_until_complete(run_async_bot())
