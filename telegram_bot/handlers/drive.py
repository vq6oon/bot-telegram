"""Handlers for Google Drive commands using shared upload concurrency control."""
import asyncio
import html
import logging
import os
import tempfile
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from ..config import (
    DRIVE_ALLOWED_USER_IDS,
    DRIVE_FOLDER_ID,
    MAX_TELEGRAM_DOWNLOAD_SIZE,
    OWNER_ID,
)
from ..handlers.general import get_user_info
from ..services.drive import (
    GoogleDriveAuthError,
    clear_drive_files_sync,
    get_drive_usage,
    list_drive_files_sync,
    sanitize_error,
    upload_to_drive,
)
from ..services.job_tracker import get_drive_upload_semaphore


def _authorized(user_id: int | None) -> bool:
    return bool(user_id and user_id in DRIVE_ALLOWED_USER_IDS)


def _is_owner(user_id: int | None) -> bool:
    return bool(user_id and OWNER_ID > 0 and user_id == OWNER_ID)


async def check_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _authorized(update.effective_user.id):
        if update.message:
            await update.message.reply_text("Access denied.")
        return

    try:
        usage = await asyncio.to_thread(get_drive_usage)
        await update.message.reply_text(f"Google Drive: {usage}")
    except GoogleDriveAuthError as e:
        await update.message.reply_text(f"Auth error: {e}")
    except Exception as e:
        logging.error("Drive quota error: %s", sanitize_error(e))
        await update.message.reply_text("Failed to check Drive quota.")


async def list_drive_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _authorized(update.effective_user.id):
        if update.message:
            await update.message.reply_text("Access denied.")
        return

    msg = await update.message.reply_text("Fetching file list...")
    try:
        data = await asyncio.to_thread(list_drive_files_sync, DRIVE_FOLDER_ID)
        files = data.get("files", [])
        if not files:
            return await msg.edit_text("Drive folder is empty.")

        lines = ["Recent Drive files:"]
        for f in files:
            name = html.escape(f.get("name", "Untitled"))
            link = f"https://drive.google.com/file/d/{f['id']}/view"
            size = int(f.get("size", 0))
            size_mb = f"{size / (1024 * 1024):.1f} MB" if size else "Unknown"
            lines.append(f'• <a href="{link}">{name}</a> ({size_mb})')

        lines.append(f"\nUsed: {data.get('usage_fmt', '')} | Free: {data.get('free_fmt', '')}")
        await msg.edit_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.error("List files error: %s", sanitize_error(e))
        await msg.edit_text("Failed to fetch files.")


async def clear_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not _is_owner(update.effective_user.id):
        if update.message:
            await update.message.reply_text("Access denied. Owner only.")
        return

    keyboard = [[
        InlineKeyboardButton("Yes, delete all", callback_data="confirm_clear_drive"),
        InlineKeyboardButton("Cancel", callback_data="cancel_clear_drive"),
    ]]
    await update.message.reply_text("Delete all files in Google Drive?", reply_markup=InlineKeyboardMarkup(keyboard))


async def clear_drive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not _is_owner(query.from_user.id):
        if query:
            await query.answer("Owner only.", show_alert=True)
        return

    await query.answer()
    if query.data == "confirm_clear_drive":
        await query.edit_message_text("Clearing Drive folder...")
        deleted, total = await asyncio.to_thread(clear_drive_files_sync, DRIVE_FOLDER_ID)
        await query.edit_message_text(f"Deleted {deleted} of {total} file(s).")
    else:
        await query.edit_message_text("Cancelled.")


async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    if not msg or not user or not _authorized(user.id):
        if msg:
            await msg.reply_text("Access denied.")
        return

    if not msg.reply_to_message or not msg.reply_to_message.document:
        return await msg.reply_text("Reply to a file with /upload to send it to Google Drive.")

    doc = msg.reply_to_message.document
    file_name = doc.file_name or f"document_{doc.file_unique_id}"

    # Telegram bot getFile limit check
    if getattr(doc, "file_size", None) and doc.file_size > MAX_TELEGRAM_DOWNLOAD_SIZE:
        size_mb = doc.file_size / (1024 * 1024)
        return await msg.reply_text(
            f"File is {size_mb:.1f} MB. Telegram limits bot downloads to 20 MB."
        )

    status = await msg.reply_text(f"Downloading {file_name} from Telegram...")
    temp_path = None
    try:
        async with get_drive_upload_semaphore():
            try:
                tg_file = await context.bot.get_file(doc.file_id)
            except BadRequest as e:
                if "file is too big" in str(e).lower():
                    return await status.edit_text("File exceeds Telegram's 20 MB bot limit.")
                raise

            with tempfile.NamedTemporaryFile(prefix="tg-upload-", delete=False) as tmp:
                temp_path = tmp.name

            await tg_file.download_to_drive(temp_path)
            await status.edit_text("Uploading to Google Drive...")
            link = await asyncio.to_thread(upload_to_drive, temp_path, DRIVE_FOLDER_ID, file_name)

        logging.info("[UPLOAD] %s uploaded: %s", get_user_info(user), file_name)
        await status.edit_text(f"Uploaded: {link}", disable_web_page_preview=True)
    except Exception as e:
        logging.error("Upload failed: %s", sanitize_error(e))
        await status.edit_text("Upload failed.")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
