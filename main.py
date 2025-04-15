import json
import hashlib
import os
import requests
import subprocess
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
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
DATA_FILE = 'urls.json'
HASH_FILE = 'url_hashes.json'


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"⚠️ Warning: {DATA_FILE} was invalid. Reinitializing.")
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
        print(f"⚠️ Warning: {HASH_FILE} was invalid. Reinitializing.")
        return {}


def save_hashes(hashes):
    with open(HASH_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)
    commit_and_push_changes("✅ Updated hash data")


def commit_and_push_changes(message):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"], check=True)

        repo = os.getenv("GITHUB_REPOSITORY")
        token = os.getenv("GH_PAT")
        if not token or not repo:
            print("❌ GH_PAT or GITHUB_REPOSITORY not set")
            return

        subprocess.run([
            "git", "remote", "set-url", "origin",
            f"https://x-access-token:{token}@github.com/{repo}.git"
        ], check=True)

        subprocess.run(["git", "add", DATA_FILE, HASH_FILE], check=True)
        subprocess.run(["git", "commit", "-m", message], check=False)
        result = subprocess.run(["git", "push"], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Push failed:\n{result.stderr}")
        else:
            print("✅ Pushed to GitHub successfully.")
    except Exception as e:
        print(f"❌ Commit/Push failed: {e}")


async def get_page_hash(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, timeout=20000)
            await page.wait_for_timeout(6000)
            content = await page.content()
            await browser.close()
            print("🔍 Cleaned content preview:\n" + content[:600])
            return hashlib.sha256(content.encode()).hexdigest()
    except Exception as e:
        print(f"⚠️ Error fetching {url}: {e}")
        return None


async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_data()
    hashes = load_hashes()
    bot = context.bot

    for label, url in urls.items():
        new_hash = await get_page_hash(url)
        if new_hash is None:
            print(f"❌ Failed to fetch {label} - {url}")
            continue

        old_hash = hashes.get(label)
        status = "✅ MATCH" if old_hash == new_hash else "❌ DIFFERENT"
        print(f"🔍 [{label}]\n  OLD: {old_hash}\n  NEW: {new_hash}\n  STATUS: {status}")

        if old_hash != new_hash:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* changed!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            save_hashes(hashes)

    print("✅ check_all_urls executed")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Welcome! Use /add [label] [url] to begin monitoring pages.")


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Usage: /add [label] [url]")
        return

    label, url = args[0], args[1]
    data = load_data()

    if label in data:
        await update.message.reply_text(f"{label} already exists. Use /remove to delete first.")
        return

    data[label] = url
    save_data(data)

    hash_val = await get_page_hash(url)
    if hash_val:
        hashes = load_hashes()
        hashes[label] = hash_val
        save_hashes(hashes)

    await update.message.reply_text(f"✅ Added: *{label}*\n{url}", parse_mode="Markdown")


async def list_urls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No URLs are currently being monitored.")
        return

    msg = "\n".join([f"*{label}*: {url}" for label, url in data.items()])
    await update.message.reply_text(msg, parse_mode="Markdown")


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

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


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("Command not recognized. Use /add, /remove, or /list.")


async def main():
    print("🚀 Bot starting up...")
    print(f"Monitoring URLs defined in: {DATA_FILE}")
    print(f"Environment: {os.getenv('GITHUB_REPOSITORY')}")
    print("Polling started...\n", flush=True)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    # Delete webhook to avoid conflict with polling
    await app.bot.delete_webhook(drop_pending_updates=True)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue:
        print("🕒 JobQueue found, setting up repeating check...")
        app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    try:
        await app.run_polling()
    finally:
        print("📦 Finalizing... committing any unsaved state", flush=True)
        commit_and_push_changes("🤖 Final auto-persist on workflow shutdown")


if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
