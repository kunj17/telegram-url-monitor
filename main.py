import os
import json
import hashlib
import difflib
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters)
from playwright.async_api import async_playwright

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
            old_file = os.path.join(DIFF_DIR, f"{label}_old.html")
            new_file = os.path.join(DIFF_DIR, f"{label}_new.html")

            if old_hash:
                with open(old_file, 'w') as f:
                    f.write(hashes.get(f"{label}_content", ""))

            with open(new_file, 'w') as f:
                f.write(content)

            hashes[label] = new_hash
            hashes[f"{label}_content"] = content
            save_json(hashes, HASH_FILE)

            # Create diff summary
            diff = difflib.unified_diff(
                hashes.get(f"{label}_content", "").splitlines(),
                content.splitlines(),
                fromfile='before',
                tofile='after',
                lineterm=''  # No trailing newlines
            )
            diff_snippet = '\n'.join(list(diff)[:20]) or "(Large diff or dynamic content - see log.)"

            message = (
                f"\U0001F514 *{label}* has changed!\n"
                f"{url}\n\n"
                f"```diff\n{diff_snippet}\n```"
            )
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        else:
            print("✅ No change detected.")

# === Bot Commands ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the URL Monitor Bot!\n"
        "Use /add <label> <url> to begin monitoring a site.\n"
        "Use /list to see current URLs. /remove <label> to stop monitoring."
    )

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add <label> <url>")
        return

    label, url = args[0], args[1]
    urls = load_json(DATA_FILE)
    if label in urls:
        await update.message.reply_text(f"⚠️ {label} already exists. Remove first.")
        return

    content = await get_page_text(url)
    if content is None:
        await update.message.reply_text("❌ Couldn't fetch URL.")
        return

    urls[label] = url
    save_json(urls, DATA_FILE)

    hashes = load_json(HASH_FILE)
    hashes[label] = get_hash(content)
    hashes[f"{label}_content"] = content
    save_json(hashes, HASH_FILE)

    await update.message.reply_text(f"✅ Now monitoring *{label}*\n{url}", parse_mode="Markdown")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    urls = load_json(DATA_FILE)
    if not urls:
        await update.message.reply_text("No URLs are being monitored.")
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
    await update.message.reply_text("❓ Unknown command. Use /add /list /remove.")

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
    asyncio.run(run())
