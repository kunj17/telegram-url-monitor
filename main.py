import asyncio
import os
import json
import hashlib
import difflib
import subprocess
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GH_PAT = os.getenv("GH_PAT")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"
HTML_FILE = "url_html_snapshots.json"

# === UTILS ===
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def commit_and_push_changes(message="🔁 Updated hash"):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"])
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"])
        subprocess.run(["git", "add", HASH_FILE, HTML_FILE], check=True)
        subprocess.run(["git", "commit", "-m", message], check=False)
        subprocess.run(["git", "push"], check=True)
        print("✅ Pushed to GitHub successfully.")
    except Exception as e:
        print(f"❌ Git push failed: {e}")

# === SCRAPER ===
async def fetch_page_data(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=30000)
            await page.wait_for_timeout(5000)
            body_text = await page.inner_text("body")
            full_html = await page.content()
            await browser.close()
            return body_text, full_html
    except Exception as e:
        print(f"⚠️ Error fetching {url}: {e}")
        return None, None

# === MONITOR ===
async def check_all_urls(context):
    urls = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)
    htmls = load_json(HTML_FILE)

    for label, url in urls.items():
        print(f"\n🔍 Checking: {label} | {url}")
        text, html = await fetch_page_data(url)
        if not text or not html:
            print(f"❌ Failed to fetch: {label}")
            continue

        new_hash = hashlib.sha256(text.encode()).hexdigest()
        old_hash = hashes.get(label)
        hashes[label] = new_hash

        if new_hash != old_hash:
            print(f"🔔 CHANGE DETECTED in {label}!")

            # Save diff
            old_html = htmls.get(label, "")
            diff = difflib.unified_diff(
                old_html.splitlines(), html.splitlines(), lineterm=""
            )
            diff_text = "\n".join(diff)

            # Save HTML snapshot and notify
            htmls[label] = html
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* changed!\n{url}\n\n📄 _Logged diff and snapshot._",
                parse_mode="Markdown"
            )

            now = datetime.now().strftime("%Y%m%d-%H%M%S")
            with open(f"diffs/{label}-{now}.diff", "w") as f:
                f.write(diff_text)

        else:
            print("✅ No changes")

    save_json(HASH_FILE, hashes)
    save_json(HTML_FILE, htmls)
    commit_and_push_changes()
    print("✅ check_all_urls executed")

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_msg = (
        "👋 Welcome to the *Website Monitor Bot*!\n\n"
        "Use the following commands:\n"
        "/add [label] [url] – Start monitoring a new page\n"
        "/remove [label] – Stop monitoring a page\n"
        "/list – Show all monitored URLs"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown")

async def add(update: Update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    urls = load_json(DATA_FILE)
    if label in urls:
        await update.message.reply_text("Label already exists.")
        return

    text, html = await fetch_page_data(url)
    if not html:
        await update.message.reply_text("Couldn't fetch page.")
        return

    urls[label] = url
    hashes = load_json(HASH_FILE)
    htmls = load_json(HTML_FILE)
    hashes[label] = hashlib.sha256(text.encode()).hexdigest()
    htmls[label] = html

    save_json(DATA_FILE, urls)
    save_json(HASH_FILE, hashes)
    save_json(HTML_FILE, htmls)

    await update.message.reply_text(f"✅ Now tracking: {label}")

async def remove(update: Update, context):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remove [label]")
        return

    label = args[0]
    urls = load_json(DATA_FILE)
    if label not in urls:
        await update.message.reply_text("Label not found.")
        return

    del urls[label]
    hashes = load_json(HASH_FILE)
    htmls = load_json(HTML_FILE)
    hashes.pop(label, None)
    htmls.pop(label, None)

    save_json(DATA_FILE, urls)
    save_json(HASH_FILE, hashes)
    save_json(HTML_FILE, htmls)

    await update.message.reply_text(f"❌ Stopped monitoring: {label}")

async def list_urls(update: Update, context):
    urls = load_json(DATA_FILE)
    if not urls:
        await update.message.reply_text("No URLs are being monitored.")
        return
    msg = "\n".join([f"*{label}* → {url}" for label, url in urls.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")

# === MAIN ===
if __name__ == '__main__':
    import asyncio
    import nest_asyncio
    from telegram.ext import CommandHandler, MessageHandler, filters

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

        if not os.path.exists("diffs"):
            os.mkdir("diffs")

        print("🕒 JobQueue found, setting up repeating check...")
        app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

        await app.run_polling()

    # ✅ Apply fix for "already running loop" error
    try:
        asyncio.run(run_async_bot())
    except RuntimeError as e:
        if "already running" in str(e):
            print("⚠️ Detected existing asyncio loop. Applying `nest_asyncio` patch...")
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            loop.create_task(run_async_bot())
            loop.run_forever()
        else:
            raise
