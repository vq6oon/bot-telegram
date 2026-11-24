from telegram import Update, ForceReply
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging
from ..config import GROUP_LAPOR_ID

async def lapor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📨 Silakan ketik laporan atau pesan Anda lalu kirim.\n"
        "Bot akan meneruskannya ke admin.",
        reply_markup=ForceReply(selective=True)
    )

async def handle_laporan_balasan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message and "lapor" in update.message.reply_to_message.text.lower():
        user = update.effective_user
        user_info = f"{user.id} (@{user.username or '-'} / {user.full_name})"
        isi_laporan = update.message.text

        text_admin = (
            f"📬 *Laporan Baru dari Pengguna:*\n"
            f"{user_info}\n\n"
            f"📝 Pesan:\n{isi_laporan}"
        )

        # Notify user that report is being sent
        status_msg = await update.message.reply_text("⏳ Mengirim laporan kamu ke admin...")

        # Log report details to terminal
        logging.info(f"[LAPOR] Dari {user_info}: {isi_laporan}")

        try:
            await context.bot.send_message(
                chat_id=GROUP_LAPOR_ID,
                text=text_admin,
                parse_mode=ParseMode.MARKDOWN
            )
            await status_msg.edit_text("✅ Laporan berhasil dikirim ke admin. Terima kasih!")
            return
        except Exception as e:
            logging.error(f"[LAPOR] Gagal kirim laporan ke grup: {e}")
            await status_msg.edit_text(f"❌ Gagal kirim laporan ke admin: {e}")
            return
