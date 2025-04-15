import os
import json
import hashlib
import difflib
import logging
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

# === CONFIG ===
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "unknown")

DATA_FILE = "urls.json"
SNAPSHOT_DIR = Path("snapshots")
DIFF_DIR = Path("diffs")
SNAPSHOT_DIR.mkdir(exist_ok=True)
DIFF_DIR.mkdir(exist_ok=True)

# === UTILS ===
def load_urls():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE) as f:
        return json.load(f)

def save_urls(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_snapshot_path(label):
    return SNAPSHOT_DIR / f"{label}.html"

def get_diff_path(label):
    return DIFF_DIR / f"{label}.diff"

def compute_diff(old, new):
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    return "\n".join(difflib.unified_diff(old_lines, new_lines, lineterm="", n=3))

async def fetch_html(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(5000)  # wait for JS
            content = await page.content()
            await browser.close()
            return content
    except Exception as e:
        logging.error(f"❌ Error fetching {url}: {e}")
        return None

async def notify_change(bot, label, url, diff_text):
    # Truncate diff if too long
    short_diff = diff_text[:3000]
    escaped_diff = short_diff.replace("`", "'")  # avoid breaking Markdown
    message = (
        f"🔔 *{label}* has changed!\n{url}\n\n"
        f"```diff\n{escaped_diff}\n```"
    )
    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode=ParseMode.MARKDOWN)

# === MONITOR ===
async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    urls = load_urls()

    for label, url in urls.items():
        print(f"🔍 Checking {label}: {url}")
        new_html = await fetch_html(url)
        if not new_html:
            continue

        snapshot_path = get_snapshot_path(label)
        old_html = snapshot_path.read_text() if snapshot_path.exists() else ""
        if hashlib.sha256(new_html.encode()).hexdigest() != hashlib.sha256(old_html.encode()).hexdigest():
            snapshot_path.write_text(new_html)
            diff = compute_diff(old_html, new_html)
            get_diff_path(label).write_text(diff)
            print(f"❗ Detected change in {label}, diff written.")
            await notify_change(bot, label, url, diff)
        else:
            print(f"✅ No change in {label}.")

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 *Welcome to Website Change Monitor Bot!*\n\n"
        "Commands:\n"
        "• /add [label] [url] – Start tracking\n"
        "• /remove [label] – Stop tracking\n"
        "• /list – Show monitored URLs"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return
    label, url = args[0], args[1]
    urls = load_urls()
    if label in urls:
        await update.message.reply_text("Label already exists. Use a different one.")
        return
    urls[label] = url
    save_urls(urls)
    content = await fetch_html(url)
    if content:
        get_snapshot_path(label).write_text(content)
        await update.message.reply_text(f"✅ Added `{label}`", parse_mode=ParseMode.MARKDOWN)

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /remove [label]")
        return
    label = args[0]
    urls = load_urls()
    if label not in urls:
        await update.message.reply_text("Label not found.")
        return
    urls.pop(label)
    save_urls(urls)
    get_snapshot_path(label).unlink(missing_ok=True)
    get_diff_path(label).unlink(missing_ok=True)
    await update.message.reply_text(f"🗑️ Removed `{label}`", parse_mode=ParseMode.MARKDOWN)

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urls = load_urls()
    if not urls:
        await update.message.reply_text("No URLs are currently being tracked.")
        return
    msg = "\n".join([f"*{label}*: {url}" for label, url in urls.items()])
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /add, /remove or /list.")

# === MAIN ===
if __name__ == "__main__":
    import asyncio

    async def run():
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

    asyncio.run(run())
