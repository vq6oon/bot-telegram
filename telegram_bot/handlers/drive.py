"""Telegram handlers for Google Drive commands."""
import asyncio
import html
import logging
import os
import tempfile
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from ..config import (
    DRIVE_ALLOWED_USER_IDS,
    DRIVE_FOLDER_ID,
    DRIVE_MAX_CONCURRENT_UPLOADS,
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

# Limit concurrent uploads to protect bandwidth and disk
_upload_semaphore = asyncio.Semaphore(DRIVE_MAX_CONCURRENT_UPLOADS)


def _is_drive_authorized(user_id: int | None) -> bool:
    """Check user against authorized Drive whitelist."""
    if not user_id or not DRIVE_ALLOWED_USER_IDS:
        return False
    return user_id in DRIVE_ALLOWED_USER_IDS


def _is_owner(user_id: int | None) -> bool:
    """Verify that user is the bot owner."""
    return bool(user_id and OWNER_ID > 0 and user_id == OWNER_ID)


async def clear_drive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return

    user_id = query.from_user.id
    await query.answer()

    if not _is_owner(user_id):
        await query.edit_message_text("❌ Kamu tidak punya izin untuk tindakan ini.")
        return

    if query.data == "confirm_clear_drive":
        await query.edit_message_text("⏳ Sedang membersihkan Google Drive...")
        try:
            deleted, total = await asyncio.to_thread(clear_drive_files_sync, DRIVE_FOLDER_ID)
            if total == 0:
                await query.edit_message_text("📂 Folder Google Drive sudah kosong.")
            else:
                await query.edit_message_text(
                    f"✅ Berhasil menghapus {deleted} dari {total} file di Google Drive."
                )
        except GoogleDriveAuthError:
            await query.edit_message_text(
                "❌ <b>Autentikasi Google Drive Gagal.</b>\n"
                "Token kedaluwarsa atau belum tersedia. Hubungi admin untuk menjalankan <code>get_token.py</code>.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logging.error("Failed to clear drive: %s", sanitize_error(e))
            await query.edit_message_text(
                "❌ Terjadi kesalahan saat membersihkan Google Drive. Silakan coba lagi."
            )

    elif query.data == "cancel_clear_drive":
        await query.edit_message_text("🚫 Dibatalkan.")


async def check_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if not _is_drive_authorized(update.effective_user.id):
        await update.message.reply_text("❌ Kamu tidak punya izin untuk mengakses Google Drive.")
        return

    try:
        usage = await asyncio.to_thread(get_drive_usage)
        await update.message.reply_text(
            f"💾 <b>Kapasitas Google Drive:</b>\n{html.escape(usage)}",
            parse_mode=ParseMode.HTML,
        )
    except GoogleDriveAuthError:
        await update.message.reply_text(
            "❌ <b>Autentikasi Google Drive Gagal.</b>\n"
            "Token kedaluwarsa atau belum tersedia. Hubungi admin untuk menjalankan <code>get_token.py</code>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logging.error("Failed to check drive: %s", sanitize_error(e))
        await update.message.reply_text(
            "❌ Gagal memeriksa kapasitas Google Drive. Silakan coba lagi."
        )


async def clear_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    logging.info("[CLEARDRIVE] %s requested drive clear", get_user_info(user))
    if not _is_owner(user.id):
        await update.message.reply_text("❌ Kamu tidak punya izin untuk menggunakan perintah ini.")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Ya, hapus semua", callback_data="confirm_clear_drive"),
            InlineKeyboardButton("❌ Batal", callback_data="cancel_clear_drive"),
        ]
    ]

    await update.message.reply_text(
        "❗ <b>Yakin ingin menghapus semua file dari Google Drive?</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def list_drive_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    if not _is_drive_authorized(update.effective_user.id):
        await update.message.reply_text("❌ Kamu tidak punya izin untuk mengakses Google Drive.")
        return

    msg = await update.message.reply_text("🔍 Mengambil daftar file dari Google Drive...")
    try:
        data = await asyncio.to_thread(list_drive_files_sync, DRIVE_FOLDER_ID)
        files = data["files"]

        if not files:
            await msg.edit_text("📂 Belum ada file yang diunggah ke Google Drive.")
            return

        lines = ["<b>📁 Daftar file terbaru di Google Drive:</b>", ""]
        for item in files:
            size = int(item.get("size", 0))
            safe_name = html.escape(item.get("name", "Tanpa Nama"))
            link = f"https://drive.google.com/file/d/{item['id']}/view"
            size_mb = f"{size / 1024**2:.2f} MB" if size else "???"
            lines.append(f'📄 <a href="{link}">{safe_name}</a> — {size_mb}')

        lines.append("")
        lines.append(f"💾 Total terpakai: <b>{html.escape(data['usage_fmt'])}</b>")
        lines.append(
            f"📦 Sisa kapasitas: <b>{html.escape(data['free_fmt'])}</b> "
            f"dari total <b>{html.escape(data['limit_fmt'])}</b>"
        )

        await msg.edit_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except GoogleDriveAuthError:
        await msg.edit_text(
            "❌ <b>Autentikasi Google Drive Gagal.</b>\n"
            "Token kedaluwarsa atau belum tersedia. Hubungi admin untuk menjalankan <code>get_token.py</code>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logging.error("Failed to list drive files: %s", sanitize_error(e))
        await msg.edit_text("❌ Gagal mengambil daftar file Google Drive. Silakan coba lagi.")


async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user
    if not message or not user:
        return

    if not _is_drive_authorized(user.id):
        await message.reply_text("❌ Kamu tidak punya izin untuk mengunggah file ke Google Drive.")
        return

    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply_text(
            "❗ Gunakan perintah /upload dengan <b>mereply</b> ke file/dokumen yang ingin diunggah.",
            parse_mode=ParseMode.HTML,
        )
        return

    document = message.reply_to_message.document
    file_id = document.file_id
    file_name = document.file_name or f"document_{document.file_unique_id}"
    safe_file_name = html.escape(file_name)

    msg = await message.reply_text(
        f"⏳ Menunggu antrean &amp; mengunduh <code>{safe_file_name}</code> dari Telegram...",
        parse_mode=ParseMode.HTML,
    )

    tmp_path = None
    try:
        async with _upload_semaphore:
            tg_file = await context.bot.get_file(file_id)

            # Close temp file handle before download on Windows
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name

            await tg_file.download_to_drive(tmp_path)

            await msg.edit_text(
                f"☁️ Mengunggah <code>{safe_file_name}</code> ke Google Drive...",
                parse_mode=ParseMode.HTML,
            )

            link = await asyncio.to_thread(upload_to_drive, tmp_path, DRIVE_FOLDER_ID, file_name)

        logging.info("[UPLOAD] %s uploaded: %s", get_user_info(user), file_name)
        await msg.edit_text(
            f"✅ <b>File berhasil diunggah!</b>\n\n"
            f"📄 <code>{safe_file_name}</code>\n"
            f'🔗 <a href="{link}">Buka di Google Drive</a>',
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except GoogleDriveAuthError:
        await msg.edit_text(
            "❌ <b>Autentikasi Google Drive Gagal.</b>\n"
            "Token kedaluwarsa atau belum tersedia. Hubungi admin untuk menjalankan <code>get_token.py</code>.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logging.error("Failed to upload to Drive: %s", sanitize_error(e))
        await msg.edit_text("❌ Gagal mengunggah file ke Google Drive. Silakan coba lagi.")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as cleanup_err:
                logging.warning("Failed to remove temporary file: %s", sanitize_error(cleanup_err))
