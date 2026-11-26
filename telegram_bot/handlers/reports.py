from telegram import Update, ForceReply
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging
from ..config import GROUP_LAPOR_ID

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(
        "Type your report or message and send it.\n"
        "The bot will forward it to the admins.",
        reply_markup=ForceReply(selective=True)
    )

async def handle_report_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.reply_to_message:
        return
    if "report" not in (update.message.reply_to_message.text or "").lower():
        return
    user = update.effective_user
    if not user:
        return
    user_info = f"{user.id} (@{user.username or '-'} / {user.full_name})"
    report_text = update.message.text

    admin_text = (
        f"*New Report:*\n"
        f"{user_info}\n\n"
        f"Message:\n{report_text}"
    )

    status_msg = await update.message.reply_text("Sending your report to the admins...")
    logging.info("[REPORT] From %s: %s", user_info, report_text)

    try:
        await context.bot.send_message(
            chat_id=GROUP_LAPOR_ID,
            text=admin_text,
            parse_mode=ParseMode.MARKDOWN
        )
        await status_msg.edit_text("Report sent to the admins. Thank you!")
    except Exception as e:
        logging.error("[REPORT] Failed to send report to group: %s", e)
        await status_msg.edit_text(f"Failed to send report to the admins: {e}")
