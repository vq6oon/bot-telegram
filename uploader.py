# uploader.py
import os
from pathlib import Path


def load_dotenv(path):
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\'"))
    except FileNotFoundError:
        pass


load_dotenv(Path(__file__).with_name(".env"))
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

UPLOAD_TOKEN = os.environ.get("UPLOAD_TOKEN", "")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document:
        return
    file = await update.message.document.get_file()
    file_path = f"temp_upload/{update.message.document.file_name}"
    await file.download_to_drive(file_path)
    with open(file_path, "rb") as f:
        msg = await context.bot.send_document(CHANNEL_ID, InputFile(f), caption=update.message.caption)
        await update.message.reply_text(f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{msg.message_id}")

if __name__ == "__main__":
    import os
    os.makedirs("temp_upload", exist_ok=True)
    app = ApplicationBuilder().token(UPLOAD_TOKEN).build()
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    print("Uploader bot is active.")
    app.run_polling()
