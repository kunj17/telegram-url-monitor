from telegram.ext import Updater, CommandHandler

TELEGRAM_TOKEN = "7935964890:AAH__dT03uCuPDr4ht8CNJ7_7nL5yb6Ukig"

def start(update, context):
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=chat_id, text=f"✅ This is your Chat ID:\n`{chat_id}`", parse_mode="Markdown")
    print(f"[LOG] Chat ID: {chat_id}")

updater = Updater(TELEGRAM_TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(CommandHandler("start", start))
updater.start_polling()
updater.idle()

