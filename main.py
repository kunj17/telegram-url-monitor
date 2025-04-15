import os
import json
import difflib
import hashlib
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from playwright.async_api import async_playwright

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"
CONTENT_FILE = "latest_snapshots.json"
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")

# === FILE IO ===
def load_json(path):
    return json.load(open(path)) if os.path.exists(path) else {}

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# === SCRAPER ===
async def get_page_text(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(url, timeout=15000)
        await page.wait_for_timeout(5000)
        content = await page.inner_text("body")
        await browser.close()
        return content

def compute_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()

# === MONITOR ===
async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_json(DATA_FILE)
    hashes = load_json(HASH_FILE)
    contents = load_json(CONTENT_FILE)
    bot = context.bot

    for label, url in urls.items():
        try:
            print(f"\n🔍 Checking {label} => {url}")
            text = await get_page_text(url)
            new_hash = compute_hash(text)
            old_hash = hashes.get(label)

            if new_hash != old_hash:
                print(f"  ⚠️ Change detected for {label}")
                diff_html = difflib.HtmlDiff().make_file(
                    contents.get(label, "").splitlines(),
                    text.splitlines(),
                    fromdesc="Before", todesc="After"
                )
                os.makedirs("diffs", exist_ok=True)
                diff_path = f"diffs/{label}.html"
                with open(diff_path, "w") as f:
                    f.write(diff_html)

                await bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🔔 *{label}* has changed!\n{url}\nCheck details in GitHub repo's `diffs/{label}.html`",
                    parse_mode="Markdown"
                )

                hashes[label] = new_hash
                contents[label] = text

            else:
                print(f"  ✅ No change")
        except Exception as e:
            print(f"  ❌ Error checking {label}: {e}")

    save_json(HASH_FILE, hashes)
    save_json(CONTENT_FILE, contents)

# === COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the Website Monitor Bot!\n\n" +
        "Use /add [label] [url] to track a page.\n" +
        "Use /list to view tracked URLs.\n" +
        "Use /remove [label] to stop tracking."
    )

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return
    label, url = args[0], args[1]
    data = load_json(DATA_FILE)
    if label in data:
        await update.message.reply_text("Label already exists. Use /remove first.")
        return
    data[label] = url
    save_json(DATA_FILE, data)
    text = await get_page_text(url)
    hashes = load_json(HASH_FILE)
    hashes[label] = compute_hash(text)
    save_json(HASH_FILE, hashes)
    contents = load_json(CONTENT_FILE)
    contents[label] = text
    save_json(CONTENT_FILE, contents)
    await update.message.reply_text(f"✅ Now tracking {label}")

async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_json(DATA_FILE)
    if not data:
        await update.message.reply_text("No URLs are being tracked.")
    else:
        msg = "\n".join([f"*{k}*: {v}" for k, v in data.items()])
        await update.message.reply_text(msg, parse_mode="Markdown")

async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /remove [label]")
        return
    label = args[0]
    data = load_json(DATA_FILE)
    if label in data:
        del data[label]
        save_json(DATA_FILE, data)
        hashes = load_json(HASH_FILE)
        hashes.pop(label, None)
        save_json(HASH_FILE, hashes)
        contents = load_json(CONTENT_FILE)
        contents.pop(label, None)
        save_json(CONTENT_FILE, contents)
        await update.message.reply_text(f"❌ Stopped tracking {label}")
    else:
        await update.message.reply_text("Label not found.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Unknown command. Use /start for help.")

# === MAIN ===
async def run_async_bot():
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {GITHUB_REPOSITORY}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(run_async_bot())
