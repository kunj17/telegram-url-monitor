import json
import hashlib
import os
import requests
import subprocess
from bs4 import BeautifulSoup
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

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if TELEGRAM_TOKEN is None:
    raise EnvironmentError("TELEGRAM_TOKEN environment variable not set.")

chat_id_str = os.getenv("CHAT_ID")
if chat_id_str is None:
    raise EnvironmentError("CHAT_ID environment variable not set.")
CHAT_ID = int(chat_id_str)

DATA_FILE = 'urls.json'
HASH_FILE = 'url_hashes.json'

# =============== STORAGE HELPERS ===============
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

# =============== COMMIT CHANGES IMMEDIATELY ===============
def commit_and_push_changes(message="🤖 Auto-update URL tracking state"):
    try:
        subprocess.run(["git", "config", "--global", "user.name", "bot-runner"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "bot@auto.commit"], check=True)

        repo = os.getenv("GITHUB_REPOSITORY")
        token = os.getenv("GH_PAT")
        if not token or not repo:
            print("❌ GH_PAT or GITHUB_REPOSITORY not set")
            return

        print(f"🔍 Repo: {repo}")
        print(f"🔐 Token starts with: {token[:6]}...")

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

# =============== MONITORING LOGIC ===============
def get_page_hash(url):
    try:
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, 'html.parser')
        return hashlib.sha256(soup.get_text().encode()).hexdigest()
    except Exception:
        return None

async def check_all_urls(context: ContextTypes.DEFAULT_TYPE):
    urls = load_data()
    hashes = load_hashes()
    bot = context.bot

    for label, url in urls.items():
        new_hash = get_page_hash(url)
        if new_hash is None:
            continue

        if hashes.get(label) != new_hash:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"🔔 *{label}* has been updated!\n{url}",
                parse_mode="Markdown"
            )
            hashes[label] = new_hash
            save_hashes(hashes)

# =============== TELEGRAM COMMANDS ===============
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

    hash_val = get_page_hash(url)
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

# =============== MAIN ===============
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("list", list_urls))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    if app.job_queue:
        app.job_queue.run_repeating(check_all_urls, interval=900, first=10)

    try:
        app.run_polling()
    finally:
        commit_and_push_changes("🤖 Final auto-persist on workflow shutdown")

if __name__ == '__main__':
    main()
