from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import shutil
from datetime import datetime
from ..state import BOT_START
from ..config import OWNER_ID

OWNER_ONLY = "Only the owner can use this command."


async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text(OWNER_ONLY)

    delta = datetime.now() - BOT_START
    await update.message.reply_text(
        f"Bot uptime: `{str(delta).split('.')[0]}`", parse_mode=ParseMode.MARKDOWN
    )


async def clearcache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text(OWNER_ONLY)

    try:
        shutil.rmtree("youtube-dump", ignore_errors=True)
        shutil.rmtree("ig-dump", ignore_errors=True)
        shutil.rmtree("subs", ignore_errors=True)
        shutil.rmtree("anime-dump", ignore_errors=True)
        await update.message.reply_text("All local cache cleared.")
    except Exception as e:
        await update.message.reply_text(f"Failed to clear cache: {e}")


async def whois(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text(OWNER_ONLY)

    if not context.args:
        return await update.message.reply_text("Example: /whois 123456789")

    try:
        user_id = int(context.args[0])
        user = await context.bot.get_chat(user_id)

        info = (
            f"*User info:*\n"
            f"ID: `{user.id}`\n"
            f"Name: {user.full_name}\n"
        )
        if user.username:
            info += f"Username: @{user.username}"

        await update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Failed to look up user: {e}")
