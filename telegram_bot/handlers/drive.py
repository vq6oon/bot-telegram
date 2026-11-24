"""Handlers for Google Drive commands supporting all Telegram media types."""
import asyncio
import html
import logging
import mimetypes
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


def _get_message(update: Update):
    return getattr(update, "effective_message", None) or getattr(update, "message", None)


def _guess_extension(mime_type: str | None, fallback_ext: str) -> str:
    if mime_type:
        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            return guessed
    return fallback_ext


_DIAGNOSTIC_ATTRS = (
    "document",
    "video",
    "audio",
    "animation",
    "voice",
    "video_note",
    "photo",
    "sticker",
    "story",
    "paid_media",
    "link_preview_options",
    "forum_topic_created",
)


def _present_attrs(obj) -> str:
    if obj is None:
        return "none"
    present = [attr for attr in _DIAGNOSTIC_ATTRS if getattr(obj, attr, None)]
    return ",".join(present) or type(obj).__name__


def _extract_upload_media(message) -> tuple[str, str, int | None] | None:
    """Extract (file_id, file_name, file_size) from a Telegram media attachment."""
    if message is None:
        return None

    media_specs = (
        ("document", "document", ""),
        ("video", "video", ".mp4"),
        ("audio", "audio", ".mp3"),
        ("animation", "animation", ".mp4"),
        ("voice", "voice", ".ogg"),
        ("video_note", "video_note", ".mp4"),
    )
    for attr, prefix, default_ext in media_specs:
        media = getattr(message, attr, None)
        if media and getattr(media, "file_id", None):
            unique_id = getattr(media, "file_unique_id", None) or media.file_id[:12]
            raw_name = getattr(media, "file_name", None)
            if raw_name:
                file_name = raw_name
            else:
                ext = _guess_extension(getattr(media, "mime_type", None), default_ext)
                file_name = f"{prefix}_{unique_id}{ext}"
            return media.file_id, file_name, getattr(media, "file_size", None)

    photos = getattr(message, "photo", None)
    if photos:
        best_photo = photos[-1]
        if getattr(best_photo, "file_id", None):
            unique_id = getattr(best_photo, "file_unique_id", None) or best_photo.file_id[:12]
            return best_photo.file_id, f"photo_{unique_id}.jpg", getattr(best_photo, "file_size", None)

    return None


async def check_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = _get_message(update)
    user = getattr(update, "effective_user", None)
    if not msg or not user or not _authorized(user.id):
        if msg:
            await msg.reply_text("Access denied.")
        return

    try:
        usage = await asyncio.to_thread(get_drive_usage)
        await msg.reply_text(f"Google Drive: {usage}")
    except GoogleDriveAuthError as e:
        await msg.reply_text(f"Auth error: {e}")
    except Exception as e:
        logging.error("Drive quota error: %s", sanitize_error(e))
        await msg.reply_text("Failed to check Drive quota.")


async def list_drive_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = _get_message(update)
    user = getattr(update, "effective_user", None)
    if not msg or not user or not _authorized(user.id):
        if msg:
            await msg.reply_text("Access denied.")
        return

    status = await msg.reply_text("Fetching file list...")
    try:
        data = await asyncio.to_thread(list_drive_files_sync, DRIVE_FOLDER_ID)
        files = data.get("files", [])
        if not files:
            return await status.edit_text("Drive folder is empty.")

        lines = ["Recent Drive files:"]
        for f in files:
            name = html.escape(f.get("name", "Untitled"))
            link = f"https://drive.google.com/file/d/{f['id']}/view"
            size = int(f.get("size", 0))
            size_mb = f"{size / (1024 * 1024):.1f} MB" if size else "Unknown"
            lines.append(f'• <a href="{link}">{name}</a> ({size_mb})')

        lines.append(f"\nUsed: {data.get('usage_fmt', '')} | Free: {data.get('free_fmt', '')}")
        await status.edit_text("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        logging.error("List files error: %s", sanitize_error(e))
        await status.edit_text("Failed to fetch files.")


async def clear_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = _get_message(update)
    user = getattr(update, "effective_user", None)
    if not msg or not user or not _is_owner(user.id):
        if msg:
            await msg.reply_text("Access denied. Owner only.")
        return

    keyboard = [[
        InlineKeyboardButton("Yes, delete all", callback_data="confirm_clear_drive"),
        InlineKeyboardButton("Cancel", callback_data="cancel_clear_drive"),
    ]]
    await msg.reply_text("Delete all files in Google Drive?", reply_markup=InlineKeyboardMarkup(keyboard))


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
    msg = _get_message(update)
    user = getattr(update, "effective_user", None)
    if not msg or not user or not _authorized(user.id):
        if msg:
            await msg.reply_text("Access denied.")
        return

    reply = getattr(msg, "reply_to_message", None)
    external_reply = getattr(msg, "external_reply", None)
    # Inspect in-chat reply, cross-chat/topic external_reply, then captioned media on current message.
    media_info = (
        _extract_upload_media(reply)
        or _extract_upload_media(external_reply)
        or _extract_upload_media(msg)
    )
    if not media_info:
        logging.warning(
            "[UPLOAD] %s missed media: chat=%s msg=[%s] reply=[%s] external_reply=[%s] has_caption=%s",
            get_user_info(user),
            getattr(msg, "chat_id", None),
            _present_attrs(msg),
            _present_attrs(reply),
            _present_attrs(external_reply),
            bool(getattr(msg, "caption", None)),
        )
        return await msg.reply_text(
            "Reply to any file, photo, video, audio, or voice message with /upload (or send media with /upload as the caption)."
        )

    file_id, file_name, file_size = media_info

    if file_size and file_size > MAX_TELEGRAM_DOWNLOAD_SIZE:
        size_mb = file_size / (1024 * 1024)
        return await msg.reply_text(
            f"File is {size_mb:.1f} MB. Telegram limits bot downloads to 20 MB."
        )

    status = await msg.reply_text(f"Downloading {file_name} from Telegram...")
    temp_path = None
    try:
        async with get_drive_upload_semaphore():
            try:
                tg_file = await context.bot.get_file(file_id)
            except BadRequest as e:
                if "file is too big" in str(e).lower():
                    return await status.edit_text("File exceeds Telegram's 20 MB bot limit.")
                raise

            suffix = os.path.splitext(file_name)[1]
            with tempfile.NamedTemporaryFile(prefix="tg-upload-", suffix=suffix, delete=False) as tmp:
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
