from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import os
import logging
import tempfile
from ..handlers.general import get_user_info
from ..services.drive import get_drive_usage, get_or_create_folder
from ..config import DRIVE_FOLDER_ID, DRIVE_FOLDER_NAME, OWNER_ID

async def clear_drive_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if user_id != OWNER_ID:
        await query.edit_message_text("❌ Kamu tidak punya izin untuk ini.")
        return

    if query.data == "confirm_clear_drive":
        creds = Credentials.from_authorized_user_file('token.json')
        service = build('drive', 'v3', credentials=creds, cache_discovery=False)
        folder_id = get_or_create_folder(service, DRIVE_FOLDER_NAME)

        try:
            files = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="files(id, name)"
            ).execute().get('files', [])

            if not files:
                await query.edit_message_text("📂 Folder sudah kosong.")
                return

            for f in files:
                try:
                    service.files().delete(fileId=f['id']).execute()
                    logging.info(f"🗑️ Menghapus: {f['name']}")
                except Exception as e:
                    logging.warning(f"❌ Gagal hapus {f['name']}: {e}")

            await query.edit_message_text("✅ Semua file berhasil dihapus dari Google Drive.")

        except Exception as e:
            logging.error(f"Gagal clear drive: {e}")
            await query.edit_message_text(f"❌ Gagal menghapus: {e}")

    elif query.data == "cancel_clear_drive":
        await query.edit_message_text("🚫 Dibatalkan.")

async def check_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usage = get_drive_usage()
    await update.message.reply_text(f"💾 Kapasitas Google Drive:\n{usage}")

async def clear_drive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logging.info(f"[CLEARDRIVE] {get_user_info(user)} mencoba menghapus drive")
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Kamu tidak punya izin untuk menggunakan perintah ini.")
        return

    keyboard = [
        [
            InlineKeyboardButton("✅ Ya, hapus semua", callback_data="confirm_clear_drive"),
            InlineKeyboardButton("❌ Batal", callback_data="cancel_clear_drive")
        ]
    ]

    await update.message.reply_text(
        "❗ *Yakin ingin menghapus semua file dari Google Drive?*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def list_drive_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    creds = Credentials.from_authorized_user_file('token.json')
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    folder_id = get_or_create_folder(service, DRIVE_FOLDER_NAME)

    try:
        # Ambil kuota drive
        quota = service.about().get(fields="storageQuota").execute()["storageQuota"]
        limit = int(quota.get("limit", 0))
        usage = int(quota.get("usage", 0))
        free = limit - usage

        def fmt(b):
            for u in ['B', 'KB', 'MB', 'GB', 'TB']:
                if b < 1024:
                    return f"{b:.2f} {u}"
                b /= 1024
            return f"{b:.2f} PB"

        # Ambil daftar file
        results = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="files(id, name, size, createdTime)",
            orderBy="createdTime desc",
            pageSize=20
        ).execute()

        files = results.get('files', [])
        if not files:
            await update.message.reply_text("📂 Belum ada file yang diunggah ke Google Drive.")
            return

        text = "*📁 Daftar file terbaru di Google Drive:*\n\n"
        for f in files:
            size = int(f.get("size", 0))
            name = f["name"]
            link = f"https://drive.google.com/file/d/{f['id']}/view"
            size_mb = f"{size / 1024**2:.2f} MB" if size else "???"
            text += f"📄 [{name}]({link}) — {size_mb}\n"

        text += "\n"
        text += f"💾 Total terpakai: *{fmt(usage)}*\n"
        text += f"📦 Sisa kapasitas: *{fmt(free)}* dari total *{fmt(limit)}*"

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

    except Exception as e:
        logging.error(f"Gagal ambil daftar file Drive: {e}")
        await update.message.reply_text(f"❌ Gagal mengambil daftar file: {e}")

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if not message.reply_to_message or not message.reply_to_message.document:
        await message.reply_text("❗ Gunakan perintah /upload dengan *mereply* ke file yang ingin diunggah.", parse_mode="Markdown")
        return

    file = message.reply_to_message.document
    file_id = file.file_id
    file_name = file.file_name

    try:
        # Download file sementara
        tg_file = await context.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await tg_file.download_to_drive(tmp.name)

            # Load kredensial
            creds = Credentials.from_authorized_user_file('token.json')
            service = build('drive', 'v3', credentials=creds, cache_discovery=False)

            media = MediaFileUpload(tmp.name, resumable=True)
            uploaded = service.files().create(
                body={
                    "name": file_name,
                    "parents": [DRIVE_FOLDER_ID]
                },
                media_body=media,
                fields="id, webViewLink"
            ).execute()

        # Kirim link Drive ke user
        user = update.effective_user
        logging.info(f"[UPLOAD] {get_user_info(user)} mengunggah: {file_name}")
        await message.reply_text(f"✅ File berhasil diunggah!\n🔗 [Buka di Google Drive]({uploaded['webViewLink']})", parse_mode="Markdown")

    except Exception as e:
        await message.reply_text(f"❌ Gagal upload: {e}")

    finally:
        # Hapus file temp
        try:
            os.remove(tmp.name)
        except:
            pass
