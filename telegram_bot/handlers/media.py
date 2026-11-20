import asyncio
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes
import os
import requests
import yt_dlp
import logging
import telegram
import mimetypes
import time
import subprocess
import uuid
from urllib.parse import urlparse
from ..services.drive import get_drive_usage, upload_to_drive
from ..services.media import download_file_with_progress, download_youtube, normalize_media_url
from ..services.subtitles import download_subtitle, flag_for_lang
from ..services.tiktok import download_tiktok_file, is_tiktok_owner
from ..config import MAX_TELEGRAM_FILE_SIZE

async def convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.video:
        return await msg.reply_text("❗Balas video yang ingin diubah ke MP3.\n\nContoh: `/convert ujan`", parse_mode="Markdown")

    new_name = (context.args[0] if context.args else "audio") + ".mp3"
    video = msg.reply_to_message.video
    file = await video.get_file()

    os.makedirs("converted", exist_ok=True)
    input_path = "converted/input.mp4"
    output_path = f"converted/{new_name}"

    status_msg = await msg.reply_text("📥 Mengunduh video...")

    # 🔄 Simulasi progress bar (bukan real), karena download_to_drive tidak support streaming
    for i in range(0, 101, 20):
        try:
            bar = "█" * (i // 5) + "░" * ((100 - i) // 5)
            await status_msg.edit_text(f"📥 Mengunduh video...\n[{bar}] {i}%")
            await asyncio.sleep(0.3)
        except:
            pass

    try:
        await file.download_to_drive(input_path)

        # 🎵 Konversi pakai ffmpeg
        await status_msg.edit_text("🔄 Mengonversi ke audio...")
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, output_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )

        logging.info(f"[Convert] @{msg.from_user.username or '-'} ({msg.from_user.full_name} / {msg.from_user.id}) mengonversi video jadi: {new_name}")

        if os.path.getsize(output_path) > MAX_TELEGRAM_FILE_SIZE:
            await status_msg.edit_text("📤 File besar, mengunggah ke Google Drive...")
            link = upload_to_drive(output_path)
            await status_msg.edit_text(f"✅ Selesai! Link:\n{link}")
        else:
            with open(output_path, "rb") as f:
                await status_msg.delete()
                await msg.reply_audio(audio=InputFile(f, filename=new_name))

    except Exception as e:
        try:
            await status_msg.edit_text(f"❌ Gagal konversi: {e}")
        except:
            await msg.reply_text(f"❌ Gagal konversi: {e}")
    finally:
        for path in [input_path, output_path]:
            if os.path.exists(path):
                os.remove(path)

async def offer_youtube_format(update: Update, url: str, context: ContextTypes.DEFAULT_TYPE):
    # Keep callback payloads short; Telegram caps callback_data at 64 bytes.
    token = uuid.uuid4().hex[:12]
    context.bot_data[f"yt_{token}"] = url
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=False)
        subtitle_langs = list(info.get("subtitles", {}).keys())
    except Exception as e:
        logging.error(f"Gagal deteksi subtitle: {e}")
        subtitle_langs = []

    preferred_langs = ["id", "en", "es"]
    available_langs = [lang for lang in preferred_langs if lang in subtitle_langs]

    keyboard = [[
        InlineKeyboardButton("🎞️ 360p", callback_data=f"yt|video|360|{token}"),
        InlineKeyboardButton("🎞️ 720p", callback_data=f"yt|video|720|{token}"),
        InlineKeyboardButton("🎞️ 1080p", callback_data=f"yt|video|1080|{token}"),
    ]]
    row = [InlineKeyboardButton("🎵 MP3", callback_data=f"yt|audio||{token}")]
    if available_langs:
        row.append(InlineKeyboardButton("💬 Subtitle", callback_data=f"yt|submenu||{token}"))
    row.append(InlineKeyboardButton("❌ Cancel", callback_data="yt|cancel||"))
    keyboard.append(row)

    await update.message.reply_text(
        "Pilih format video/audio/subtitle yang ingin diunduh:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def tiktok_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("|")
    if len(parts) != 3:
        await query.edit_message_text("❌ Data tombol TikTok tidak valid.")
        return

    _, mode, short_id = parts
    data = context.user_data.get(f"tt_{short_id}")
    if not data:
        await query.answer("Data tidak ditemukan atau sudah kedaluwarsa.", show_alert=True)
        return
    if not is_tiktok_owner(data, update.effective_user.id):
        await query.answer("Tombol ini hanya bisa dipakai pengirim link.", show_alert=True)
        return

    title = data.get("title", "TikTok")
    url = data.get("video_url") if mode == "video" else data.get("audio_url")
    filename = None
    status_msg = None
    try:
        ext = ".mp4" if mode == "video" else ".mp3"
        status_msg = await update.callback_query.message.reply_text(f"⬇️ Mengunduh TikTok ({mode})...", reply_to_message_id=data["source_message_id"])
        filename = await asyncio.to_thread(download_tiktok_file, url, ext)
        size = os.path.getsize(filename)
        if size > MAX_TELEGRAM_FILE_SIZE:
            await status_msg.edit_text("⏳ File besar, mengunggah ke Google Drive...")
            link = upload_to_drive(filename)
            space = get_drive_usage()
            await context.bot.send_message(chat_id=update.effective_user.id, text=f"📁 {title}\n🔗 {link}\n💾 {space}")
        else:
            with open(filename, "rb") as media_file:
                if mode == "audio":
                    await context.bot.send_audio(chat_id=update.effective_user.id, audio=media_file, title=title)
                else:
                    await context.bot.send_video(chat_id=update.effective_user.id, video=media_file, caption=title)
            await status_msg.delete()
    except Exception as e:
        logging.error(f"TikTok media error: {e}")
        if status_msg:
            await status_msg.delete()
        await context.bot.send_message(chat_id=update.effective_user.id, text=f"❌ Gagal mengunduh: {e}")
    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)
        context.user_data.pop(f"tt_{short_id}", None)
        try:
            if status_msg:
                await status_msg.delete()
        except Exception:
            pass

async def yt_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("|")
    if len(parts) != 4:
        await query.edit_message_text("❌ Data callback tidak valid.")
        return

    _, mode, resolution, token = parts
    if mode == "cancel":
        await query.edit_message_text("❌ Operasi dibatalkan.")
        return

    url = context.bot_data.get(f"yt_{token}")
    if not url:
        await query.edit_message_text("❌ Link sudah kedaluwarsa. Kirim ulang link YouTube.")
        return

    if mode == "sub":
        msg = await query.edit_message_text("⏳ Mengunduh subtitle...")
        result = download_subtitle(url, lang=resolution or "id")
        if result:
            filepath, title = result
            try:
                with open(filepath, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat_id,
                        document=InputFile(f, filename=os.path.basename(filepath)),
                        caption=f"📄 Subtitle: {title}"
                    )
                await msg.delete()
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                await msg.edit_text(f"❌ Gagal kirim subtitle: {e}")
        else:
            await msg.edit_text("❌ Subtitle tidak tersedia atau gagal diunduh.")
        return

    if mode == "submenu":
        try:
            with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                subtitle_langs = list(info.get("subtitles", {}).keys())
        except Exception as e:
            logging.error(f"Gagal deteksi subtitle submenu: {e}")
            subtitle_langs = []

        preferred_langs = ["id", "en", "es"]
        available_langs = [lang for lang in preferred_langs if lang in subtitle_langs]

        if not available_langs:
            await query.edit_message_text("❌ Subtitle tidak tersedia untuk video ini.")
            return

        subtitle_buttons = [
            InlineKeyboardButton(f"{flag_for_lang(lang)} {lang.upper()}", callback_data=f"yt|sub|{lang}|{token}")
            for lang in available_langs
        ]

        rows = [subtitle_buttons[i:i+3] for i in range(0, len(subtitle_buttons), 3)]
        rows.append([InlineKeyboardButton("❌ Cancel", callback_data="yt|cancel||")])

        await query.edit_message_text("Pilih bahasa subtitle:", reply_markup=InlineKeyboardMarkup(rows))
        return

    try:
        msg = await query.edit_message_text("⏳ Mengunduh dari YouTube...", disable_web_page_preview=True)
    except telegram.error.BadRequest:
        msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⏳ Mengunduh dari YouTube...",
            disable_web_page_preview=True
        )

    start_time = time.time()
    result = await asyncio.to_thread(download_youtube, url, mode, resolution if resolution else None)
    end_time = time.time()
    duration = round(end_time - start_time)
    m, s = divmod(duration, 60)
    duration_str = f"{m}m{s}s" if m else f"{s}s"

    if not result:
        await msg.edit_text("❌ Gagal unduh dari YouTube.")
        return

    filepath, title = result
    try:
        size = os.path.getsize(filepath)
        if size > MAX_TELEGRAM_FILE_SIZE:
            await msg.edit_text("⏳ Ukuran file >50MB, mengunggah ke Google Drive...", disable_web_page_preview=True)
            link = upload_to_drive(filepath)
            space = get_drive_usage()
        else:
            with open(filepath, "rb") as f:
                await msg.delete()
                try:
                    if mode == "audio":
                        await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, title=title)
                    else:
                        await context.bot.send_document(chat_id=query.message.chat_id, document=InputFile(f, filename=os.path.basename(filepath)), caption=title)
                    return
                except telegram.error.TimedOut:
                    warn_msg = await context.bot.send_message(chat_id=query.message.chat_id, text="⚠️ Gagal kirim file ke Telegram. File terlalu besar atau koneksi lambat, mengunggah ke Google Drive...")
                    link = upload_to_drive(filepath)
                    space = get_drive_usage()
                    await warn_msg.delete()

        filename = os.path.basename(filepath)
        filesize_mb = round(size / (1024 * 1024), 2)
        filetype = mimetypes.guess_type(filename)[0] or "Unknown"
        file_id = link.split("/d/")[1].split("/")[0]
        view_url = f"https://drive.google.com/file/d/{file_id}/view"
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "✅ *File berhasil diunggah ke Google Drive!*\n\n"
                f"📁 *Nama*: `{filename}`\n"
                f"📄 *Ukuran*: `{filesize_mb} MB`\n"
                f"🧾 *Tipe*: `{filetype}`\n"
                f"⏱️ *Durasi proses*: `{duration_str}`\n"
                f"☁️ *Server*: Google Drive\n"
                f"\n💾 {space}"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 View / Download", url=download_url)]
            ]),
            parse_mode=telegram.constants.ParseMode.MARKDOWN,
            disable_web_page_preview=True
            )

    except Exception as e:
        await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Gagal proses file: {e}")
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

async def download_youtube_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Pakai: /yt <link YouTube>")
    url = " ".join(context.args).strip()
    if not media_service_url(url, "youtube"):
        return await update.message.reply_text("❌ Link YouTube tidak valid. Contoh: /yt https://youtu.be/...")
    await offer_youtube_format(update, url, context)


async def download_instagram_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Pakai: /ig <link Instagram>")
    url = " ".join(context.args).strip()
    if not media_service_url(url, "instagram"):
        return await update.message.reply_text("❌ Link Instagram tidak valid. Contoh: /ig https://www.instagram.com/reel/...")
    await _download_instagram(update, url)


async def _download_instagram(update: Update, url: str):
    msg = await update.message.reply_text("🔍 Mengunduh media Instagram...")
    filepath = None
    try:
        os.makedirs("ig-dump", exist_ok=True)
        options = {
            "quiet": True,
            "noplaylist": True,
            "restrictfilenames": True,
            "outtmpl": f"ig-dump/{uuid.uuid4().hex}_%(id)s_%(title).80s.%(ext)s",
            "merge_output_format": "mp4",
        }

        def download():
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                candidate = info.get("filepath") or ydl.prepare_filename(info)
                if not os.path.exists(candidate) and not candidate.endswith(".mp4"):
                    mp4_candidate = os.path.splitext(candidate)[0] + ".mp4"
                    if os.path.exists(mp4_candidate):
                        candidate = mp4_candidate
                return candidate, info.get("title", "Instagram")

        filepath, title = await asyncio.to_thread(download)
        if not os.path.isfile(filepath):
            raise FileNotFoundError("yt-dlp tidak menemukan file hasil unduhan")
        if os.path.getsize(filepath) > MAX_TELEGRAM_FILE_SIZE:
            await msg.edit_text("⏳ File besar, mengunggah ke Google Drive...")
            link = await asyncio.to_thread(upload_to_drive, filepath)
            space = await asyncio.to_thread(get_drive_usage)
            await update.message.reply_text(f"✅ Instagram media tersimpan di Google Drive:\n{link}\n\n💾 {space}")
        else:
            with open(filepath, "rb") as media_file:
                await msg.delete()
                await update.message.reply_video(
                    video=InputFile(media_file, filename=os.path.basename(filepath)),
                    caption=title,
                )
    except Exception as error:
        logging.error("Instagram download error: %s", error)
        await msg.edit_text(f"❌ Gagal unduh IG: {error}")
    finally:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)


def media_service_url(url: str, platform: str):
    return normalize_media_url(url, platform)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    user = update.effective_user

    # Each update is handled independently; no global/user cooldown.

    # ✅ Log semua link http/https yang dikirim
    if text.startswith("http"):
        logging.info(f"[Link] Dari @{user.username or '-'} ({user.first_name} / {user.id}): {text}")

    # YouTube and YouTube Music links
    youtube_url = media_service_url(text, "youtube")
    if youtube_url:
        logging.info(f"[YouTube] Memproses: {youtube_url}")

        if (urlparse(youtube_url).hostname or "").lower().endswith("music.youtube.com"):
            msg = await update.message.reply_text("🎵 Mengunduh lagu dari YouTube Music...")
            result = await asyncio.to_thread(download_youtube, youtube_url, mode="audio", music=True)
            if result:
                filepath, title = result
                try:
                    if not os.path.isfile(filepath):
                        raise FileNotFoundError("yt-dlp tidak menemukan file hasil unduhan")
                    size = os.path.getsize(filepath)
                    if size > MAX_TELEGRAM_FILE_SIZE:
                        await msg.edit_text("⏳ Ukuran file >50MB, mengunggah ke Google Drive...")
                        link = await asyncio.to_thread(upload_to_drive, filepath)
                        space = await asyncio.to_thread(get_drive_usage)
                        await update.message.reply_text(f"⚠️ File terlalu besar.\n📁 Diupload ke Google Drive:\n{link}\n\n💾 {space}")
                    else:
                        with open(filepath, "rb") as f:
                            await msg.delete()
                            await update.message.reply_audio(audio=InputFile(f, filename=os.path.basename(filepath)), title=title)
                except Exception as error:
                    await msg.edit_text(f"❌ Gagal kirim file: {error}")
                finally:
                    if os.path.exists(filepath):
                        os.remove(filepath)
            else:
                await msg.edit_text("❌ Gagal unduh lagu dari YouTube Music.")
        else:
            await offer_youtube_format(update, youtube_url, context)
        return

    elif "tiktok.com" in text:
        logging.info(f"[TikTok] Memproses: {text}")
        msg = await update.message.reply_text("🔍 Mendeteksi link TikTok...")
        try:
            r = requests.get("https://tikwm.com/api/", params={"url": text})
            res = r.json()
            data = res.get("data")
            if res.get("code") == 0 and data:
                from telegram import InputMediaPhoto

                if data.get("images"):
                    await msg.edit_text("📸 Deteksi slide foto, mengirim...")

                    # Siapkan list foto untuk dikirim dalam 1 grup
                    media_group = [
                        InputMediaPhoto(media=url) for url in data["images"][:10]
                    ]

                    try:
                        await context.bot.send_media_group(chat_id=user.id, media=media_group)
                        await update.message.reply_text(
                            "✅ Album foto TikTok dikirim lewat chat pribadi Anda.",
                            reply_to_message_id=update.message.message_id,
                        )
                    except Exception as e:
                        logging.error(f"Gagal kirim album TikTok secara privat: {e}")
                        await msg.edit_text("❌ Buka chat pribadi bot, kirim /start, lalu kirim ulang link TikTok di grup.")
                    else:
                        await msg.delete()
                    return

                # Simpan data ke context
                short_id = str(uuid.uuid4())[:8]
                context.user_data[f"tt_{short_id}"] = {
                    "video_url": data.get("play"),
                    "audio_url": data.get("music"),
                    "title": data.get("title", "TikTok"),
                    "owner_id": user.id,
                    "chat_id": update.effective_chat.id,
                    "source_message_id": update.message.message_id,
                }

                logging.info(f"[TikTok] Menyediakan pilihan privat untuk user {user.id}")
                try:
                    await context.bot.send_message(
                        chat_id=user.id,
                        text="Pilih format TikTok ini. Hasil hanya dikirim lewat chat pribadi Anda:",
                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("🎞️ Video", callback_data=f"tt|video|{short_id}"),
                                InlineKeyboardButton("🎧 Audio", callback_data=f"tt|audio|{short_id}")
                            ]
                        ]),
                    )
                    await update.message.reply_text("✅ Pilihan dikirim lewat chat pribadi Anda. Unduhan juga akan dikirim ke chat pribadi.", reply_to_message_id=update.message.message_id)
                except Exception as e:
                    logging.info(f"TikTok private delivery unavailable: {e}")
                    context.user_data.pop(f"tt_{short_id}", None)
                    await msg.edit_text("❌ Buka chat pribadi bot, kirim /start, lalu kirim ulang link TikTok di grup.")
                return

            await msg.edit_text("❌ Gagal unduh TikTok: Respon tidak valid.")
        except Exception as e:
            logging.error(f"TikTok error: {e}")
            await msg.edit_text(f"❌ Gagal unduh TikTok: {e}")

    instagram_url = media_service_url(text, "instagram")
    if instagram_url:
        logging.info(f"[Instagram] Memproses: {instagram_url}")
        await _download_instagram(update, instagram_url)
        return

    await update.message.reply_text("❌ Link tidak dikenali. Kirim link dari YouTube, TikTok, Instagram.")
