import os
import json
import hashlib
import subprocess
import asyncio
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

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
DATA_FILE = "urls.json"
HASH_FILE = "url_hashes.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Warning: {DATA_FILE} corrupted. Reinitializing.")
        return {}


def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    commit_and_push("✅ Updated URL data")


def load_hashes():
    if not os.path.exists(HASH_FILE):
        return {}
    try:
        with open(HASH_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Warning: {HASH_FILE} corrupted. Reinitializing.")
        return {}


def save_hashes(hashes):
    with open(HASH_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)
    commit_and_push("✅ Updated hash data")


def commit_and_push(message):
    try:
        repo = os.getenv("GITHUB_REPOSITORY")
        token = os.getenv("GH_PAT")
        if not token or not repo:
            print("🚫 Missing GH_PAT or repo")
            return

        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"])
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"])
        subprocess.run(["git", "remote", "set-url", "origin",
                        f"https://x-access-token:{token}@github.com/{repo}.git"])
        subprocess.run(["git", "add", DATA_FILE, HASH_FILE])
        subprocess.run(["git", "commit", "-m", message], check=False)
        subprocess.run(["git", "push"])
        print("✅ Pushed to GitHub successfully.")
    except Exception as e:
        print(f"❌ Git push failed: {e}")


async def fetch_rendered_content(url: str) -> str | None:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(5000)  # wait for JS
            content = await page.content()
            await browser.close()
            return content
    except Exception as e:
        print(f"❌ Error fetching {url}: {e}")
        return None


async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    urls = load_data()
    hashes = load_hashes()

    for label, url in urls.items():
        content = await fetch_rendered_content(url)
        if not content:
            continue

        new_hash = hashlib.sha256(content.encode()).hexdigest()
        old_hash = hashes.get(label)

        print(f"\n🔍 [{label}]")
        print(f"  OLD: {old_hash}")
        print(f"  NEW: {new_hash}")
        print(f"  STATUS: {'✅ MATCH' if old_hash == new_hash else '❌ DIFFERENT'}")

        if old_hash != new_hash:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* changed!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            save_hashes(hashes)


# === Telegram Commands ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Use /add [label] [url] to monitor a page.")


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    data = load_data()
    if label in data:
        await update.message.reply_text(f"⚠️ {label} already exists. Use /remove first.")
        return

    data[label] = url
    save_data(data)

    content = await fetch_rendered_content(url)
    if content:
        hashes = load_hashes()
        hashes[label] = hashlib.sha256(content.encode()).hexdigest()
        save_hashes(hashes)

    await update.message.reply_text(f"✅ Added: {label} ({url})")


async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        await update.message.reply_text("🗂 No URLs are currently monitored.")
        return

    msg = "\n".join([f"*{label}* → {url}" for label, url in data.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: /remove [label]")
        return

    label = args[0]
    data = load_data()
    hashes = load_hashes()

    if label not in data:
        await update.message.reply_text(f"⚠️ No such label: {label}")
        return

    del data[label]
    save_data(data)

    if label in hashes:
        del hashes[label]
        save_hashes(hashes)

    await update.message.reply_text(f"🗑 Removed: {label}")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Unknown command. Try /add, /remove, or /list.")


async def main():
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {os.getenv('GITHUB_REPOSITORY')}")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue:
        print("🕒 JobQueue found, setting up repeating check...")
        app.job_queue.run_repeating(check_all_urls, interval=1800, first=5)

    await app.run_polling()


# === Safe Async Runner for All Environments ===
if __name__ == "__main__":
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(main())
        else:
            loop.run_until_complete(main())
    except RuntimeError:
        asyncio.run(main())
