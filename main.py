import os
import json
import hashlib
import difflib
import asyncio
import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from playwright.async_api import async_playwright

# === CONFIGURATION ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "N/A")
DATA_FILE = "urls.json"
SNAPSHOT_DIR = "snapshots"
DIFF_DIR = "diffs"

os.makedirs(SNAPSHOT_DIR, exist_ok=True)
os.makedirs(DIFF_DIR, exist_ok=True)

# === UTILITIES ===
def load_urls():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_urls(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

async def fetch_page_content(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(5000)
            content = await page.content()
            await browser.close()
            return content
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
        return None

def get_snapshot_path(label):
    return os.path.join(SNAPSHOT_DIR, f"{label}.html")

def get_diff_path(label):
    return os.path.join(DIFF_DIR, f"{label}.diff")

def save_snapshot(label, content):
    with open(get_snapshot_path(label), 'w') as f:
        f.write(content)

def load_snapshot(label):
    path = get_snapshot_path(label)
    if os.path.exists(path):
        with open(path) as f:
            return f.readlines()
    return []

def compute_diff(old, new):
    diff = list(difflib.unified_diff(old, new, lineterm='', n=3))
    return diff

async def notify_change(bot, label, url, diff):
    preview = '\n'.join(diff[:20]) if diff else 'No visual diff found.'
    message = f"\U0001F514 *{label}* has changed!\n{url}\n\n```
{preview}
```"
    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")

async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_urls()
    bot = context.bot
    print(f"\n🔍 Checking {len(urls)} URLs @ {datetime.datetime.now().isoformat()}")

    for label, url in urls.items():
        print(f"\n--- {label} ---\n{url}")
        new_content = await fetch_page_content(url)
        if new_content is None:
            print(f"⚠️ Skipping {label} due to fetch error.")
            continue

        old_lines = load_snapshot(label)
        new_lines = new_content.splitlines()
        diff = compute_diff(old_lines, new_lines)

        if diff:
            print(f"🔁 Change detected in {label}. Writing diff and notifying.")
            with open(get_diff_path(label), 'w') as f:
                f.write('\n'.join(diff))
            await notify_change(bot, label, url, diff)
            save_snapshot(label, new_content)
        else:
            print(f"✅ No changes in {label}.")

# === TELEGRAM COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Welcome to Website Watchdog!*\n\n"
        "Available commands:\n"
        "/add [label] [url] — Start monitoring a site\n"
        "/remove [label] — Stop monitoring\n"
        "/list — View current monitored sites"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return
    label, url = args[0], args[1]
    urls = load_urls()
    urls[label] = url
    save_urls(urls)
    content = await fetch_page_content(url)
    if content:
        save_snapshot(label, content)
        await update.message.reply_text(f"✅ Monitoring *{label}*", parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Usage: /remove [label]")
        return
    label = args[0]
    urls = load_urls()
    if label in urls:
        del urls[label]
        save_urls(urls)
        os.remove(get_snapshot_path(label))
        await update.message.reply_text(f"❌ Removed *{label}*", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Label not found: {label}")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urls = load_urls()
    if not urls:
        await update.message.reply_text("No URLs are being monitored.")
        return
    message = '\n'.join([f"*{k}*: {v}" for k, v in urls.items()])
    await update.message.reply_text(message, parse_mode="Markdown")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /add, /remove, or /list")

# === MAIN ===
if __name__ == '__main__':
    async def main():
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

    asyncio.run(main())
