from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import logging
import requests
from ..config import GITHUB_LINK, OWNER_ID

from ..menus.welcome import ADMIN_CAPTION, MENU_CAPTION, WELCOME_MESSAGE
from ..menus.contributors import CONTRIBUTORS_CAPTION


async def shorten(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        return await update.message.reply_text("Example: /shorten https://youtube.com/...")

    url = context.args[0]

    if not url.startswith("http"):
        return await update.message.reply_text("Invalid URL. It must start with http or https.")

    try:
        res = requests.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=10)
        short_url = res.text
        await update.message.reply_text(f"Shortlink:\n{short_url}")
    except Exception as e:
        await update.message.reply_text(f"Failed to create shortlink: {e}")

async def github_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    logging.info("[GITHUB] %s opened GitHub", get_user_info(user))
    await update.message.reply_text(f"My GitHub profile:\n{GITHUB_LINK}")

async def contributor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(CONTRIBUTORS_CAPTION)

def get_user_info(user):
    return f"{user.id} (@{user.username or '-'} / {user.full_name})"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(WELCOME_MESSAGE)


async def _send_menu(update: Update, caption: str):
    image_path = Path(__file__).resolve().parents[2] / "assets" / "kamui.png"
    try:
        with image_path.open("rb") as image:
            await update.message.reply_photo(photo=image, caption=caption)
    except FileNotFoundError:
        logging.warning("[MENU] Banner image missing at %s; sending text menu", image_path)
        await update.message.reply_text(caption)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    args = list(getattr(context, "args", None) or [])
    if not args:
        return await _send_menu(update, MENU_CAPTION)

    if args == ["--admin"]:
        user = getattr(update, "effective_user", None)
        if not user or OWNER_ID <= 0 or user.id != OWNER_ID:
            return await update.message.reply_text("Owner only.")
        return await _send_menu(update, ADMIN_CAPTION)

    await update.message.reply_text("Usage: /menu [--admin]")


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Usage Rules for Lamp1on-Bot:*\n\n"
        "1. Use the bot responsibly; do not spam links or files.\n"
        "2. Supported links: *YouTube, TikTok, Instagram*.\n"
        "3. Large files are uploaded to *public Google Drive*.\n"
        "4. *Do not upload illegal, pornographic, or pirated content*.\n"
        "5. The bot may delete old files when Drive is full.\n"
        "6. Use /lapor to report bugs or issues.\n\n"
        "By using this bot, you agree to these rules."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    logging.info("[ID] %s viewed their ID", get_user_info(user))
    await update.message.reply_text(
        f"Your ID: `{user.id}`\n"
        f"Username: @{user.username or '-'}\n"
        f"Name: {user.full_name}",
        parse_mode=ParseMode.MARKDOWN
    )
