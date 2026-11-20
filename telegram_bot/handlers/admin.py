from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import shutil
from datetime import datetime
from ..state import BOT_START
from ..config import OWNER_ID

async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Hanya admin yang bisa pakai perintah ini.")

    delta = datetime.now() - BOT_START
    await update.message.reply_text(f"⏱️ Bot aktif selama: `{str(delta).split('.')[0]}`", parse_mode="Markdown")

async def clearcache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Hanya admin yang bisa pakai perintah ini.")

    try:
        shutil.rmtree("youtube-dump", ignore_errors=True)
        shutil.rmtree("ig-dump", ignore_errors=True)
        shutil.rmtree("subs", ignore_errors=True)
        await update.message.reply_text("🧹 Semua cache lokal berhasil dihapus.")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal hapus cache: {e}")

async def whois(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("❌ Hanya admin yang bisa pakai perintah ini.")

    if not context.args:
        return await update.message.reply_text("Contoh: /whois 123456789")

    try:
        user_id = int(context.args[0])
        user = await context.bot.get_chat(user_id)

        info = (
            f"👤 *Info Pengguna:*\n"
            f"🆔 ID: `{user.id}`\n"
            f"👨‍💼 Nama: {user.full_name}\n"
        )
        if user.username:
            info += f"🔗 Username: @{user.username}"

        await update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal cari user: {e}")
