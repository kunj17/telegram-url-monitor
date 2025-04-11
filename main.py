# telegram_url_monitor/main.py
import logging, json, hashlib, os, requests
from bs4 import BeautifulSoup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from dotenv import load_dotenv

load_dotenv()

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID"))
DATA_FILE = 'urls.json'
HASH_FILE = 'url_hashes.json'

# =============== STORAGE HELPERS ===============
def load_data():
    return json.load(open(DATA_FILE)) if os.path.exists(DATA_FILE) else {}

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_hashes():
    return json.load(open(HASH_FILE)) if os.path.exists(HASH_FILE) else {}

def save_hashes(hashes):
    with open(HASH_FILE, 'w') as f:
        json.dump(hashes, f, indent=2)

# =============== MONITORING LOGIC ===============
def get_page_hash(url):
    try:
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, 'html.parser')
        return hashlib.sha256(soup.get_text().encode()).hexdigest()
    except Exception as e:
        return None

def check_all_urls(context):
    job = context.job
    chat_id = job.context
    urls = load_data()
    hashes = load_hashes()
    updated = False

    for label, url in urls.items():
        new_hash = get_page_hash(url)
        if new_hash is None:
            continue

        if hashes.get(label) != new_hash:
            context.bot.send_message(chat_id, f"\ud83d\udd14 *{label}* has been updated!\n{url}", parse_mode="Markdown")
            hashes[label] = new_hash
            updated = True

    if updated:
        save_hashes(hashes)

# =============== TELEGRAM COMMANDS ===============
def start(update, context):
    update.message.reply_text("Welcome! Use /add [label] [url] to begin monitoring pages.")

def add(update, context):
    args = context.args
    if len(args) < 2:
        return update.message.reply_text("Usage: /add [label] [url]")

    label = args[0]
    url = args[1]
    data = load_data()

    if label in data:
        return update.message.reply_text(f"{label} already exists. Use /remove to delete first.")

    data[label] = url
    save_data(data)

    hash_val = get_page_hash(url)
    if hash_val:
        hashes = load_hashes()
        hashes[label] = hash_val
        save_hashes(hashes)

    update.message.reply_text(f"\u2705 Added: *{label}*\n{url}", parse_mode="Markdown")

def list_urls(update, context):
    data = load_data()
    if not data:
        return update.message.reply_text("No URLs are currently being monitored.")
    msg = "\n".join([f"*{label}*: {url}" for label, url in data.items()])
    update.message.reply_text(msg, parse_mode="Markdown")

def remove(update, context):
    args = context.args
    if not args:
        return update.message.reply_text("Usage: /remove [label]")

    label = args[0]
    data = load_data()

    if label not in data:
        return update.message.reply_text(f"No such label: {label}")

    del data[label]
    save_data(data)

    hashes = load_hashes()
    if label in hashes:
        del hashes[label]
        save_hashes(hashes)

    update.message.reply_text(f"\u274c Removed {label}.")

def unknown(update, context):
    update.message.reply_text("Command not recognized. Use /add, /remove, or /list.")

# =============== MAIN LOOP ===============
def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("add", add))
    dp.add_handler(CommandHandler("list", list_urls))
    dp.add_handler(CommandHandler("remove", remove))
    dp.add_handler(MessageHandler(Filters.command, unknown))

    updater.job_queue.run_repeating(check_all_urls, interval=900, first=10, context=CHAT_ID)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
