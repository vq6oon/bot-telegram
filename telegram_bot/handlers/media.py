"""Media commands (/yt, /ytm, /ig) with button locks, Drive deduplication cache, and live progress."""
import asyncio
import html
import logging
import os
import subprocess
import time
import uuid
from urllib.parse import urlparse
import requests
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, InputMediaPhoto, Update
from telegram.error import BadRequest, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

from ..config import DRIVE_FOLDER_ID, MAX_TELEGRAM_DOWNLOAD_SIZE, MAX_TELEGRAM_FILE_SIZE
from ..services.drive import (
    build_youtube_app_properties,
    find_cached_youtube_file,
    sanitize_error,
    upload_to_drive,
)
from ..services.job_tracker import (
    add_job,
    format_active_jobs,
    get_download_semaphore,
    get_drive_upload_semaphore,
    remove_job,
    snapshot,
    update_job,
)
from ..services.media import (
    download_youtube,
    extract_available_resolutions,
    extract_youtube_info,
    format_youtube_filename,
    normalize_media_url,
    probe_video_resolution,
)
from ..services.subtitles import download_subtitle, flag_for_lang
from ..services.tiktok import download_tiktok_file, is_tiktok_owner
from .drive import deliver_fresh_message


def _user_tag(user) -> str:
    if not user:
        return "Unknown"
    return f"@{user.username}" if user.username else (user.first_name or str(user.id))


def _safe_user(update) -> str:
    if not update:
        return "Unknown"
    user = getattr(update, "effective_user", None)
    if not user and hasattr(update, "message"):
        user = getattr(update.message, "from_user", None)
    if not user and hasattr(update, "callback_query"):
        user = getattr(update.callback_query, "from_user", None)
    return _user_tag(user)


def _safe_chat_id(update) -> str:
    if not update:
        return "unknown"
    chat = getattr(update, "effective_chat", None)
    if chat and hasattr(chat, "id"):
        return str(chat.id)
    msg = getattr(update, "message", None)
    if msg and hasattr(msg, "chat_id"):
        return str(msg.chat_id)
    if msg and hasattr(msg, "chat") and hasattr(msg.chat, "id"):
        return str(msg.chat.id)
    return "unknown"


async def _safe_edit_text(message, text: str, **kwargs) -> None:
    try:
        await message.edit_text(text, **kwargs)
    except (BadRequest, RetryAfter, TelegramError):
        pass


async def _upload_to_drive_guarded(
    filepath: str,
    status_msg,
    title: str,
    *,
    job_id: str | None = None,
    app_properties: dict[str, str] | None = None,
    custom_name: str | None = None,
) -> str:
    """Acquire shared Drive upload semaphore and stream chunked upload with progress updates."""
    size_mb = os.path.getsize(filepath) / (1024 * 1024)
    loop = asyncio.get_running_loop()
    last_edit = [0.0]

    if job_id:
        update_job(job_id, stage="Queued for Drive", progress=0)
    await _safe_edit_text(
        status_msg,
        f"File is {size_mb:.1f} MB. Queued for Google Drive upload...",
    )

    def _on_upload_progress(pct: int) -> None:
        if job_id:
            update_job(job_id, stage="Uploading to Drive", progress=pct)
        now = time.time()
        if now - last_edit[0] >= 4.0:
            last_edit[0] = now
            asyncio.run_coroutine_threadsafe(
                _safe_edit_text(status_msg, f"Uploading {title} to Google Drive: {pct}%"),
                loop,
            )

    target_folder = DRIVE_FOLDER_ID or None
    async with get_drive_upload_semaphore():
        if job_id:
            update_job(job_id, stage="Uploading to Drive", progress=0)
        await _safe_edit_text(
            status_msg,
            f"File is {size_mb:.1f} MB. Uploading to Google Drive (0%)...",
        )
        return await asyncio.to_thread(
            upload_to_drive,
            filepath,
            target_folder,
            custom_name,
            _on_upload_progress,
            app_properties,
        )


async def _upload_and_notify_drive(
    filepath: str,
    status_msg,
    title: str,
    log_tag: str,
    target_id: int | str,
    *,
    job_id: str | None = None,
    app_properties: dict[str, str] | None = None,
    custom_name: str | None = None,
    bot=None,
    chat_id: int | str | None = None,
    requester_tag: str | None = None,
    reply_to_message_id: int | None = None,
) -> str:
    link = await _upload_to_drive_guarded(
        filepath,
        status_msg,
        title,
        job_id=job_id,
        app_properties=app_properties,
        custom_name=custom_name,
    )
    label = custom_name or title
    header = f"Done ({requester_tag}): {label}" if requester_tag else f"Done: {label}"
    text = f"{header}\nSaved to Google Drive:\n{link}"
    await deliver_fresh_message(
        status_msg,
        text,
        bot=bot,
        chat_id=chat_id,
        reply_to_message_id=reply_to_message_id,
    )
    logging.info("[%s] Uploaded to Drive for %s: %s (%s)", log_tag, target_id, title, link)
    return link


async def active_downloads_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        logging.info("[STATUS] %s checked active download stack", _safe_user(update))
        await update.message.reply_text(format_active_jobs(), parse_mode="HTML")


async def offer_youtube_format(update: Update, url: str, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    owner_id = update.effective_user.id
    token = uuid.uuid4().hex[:12]

    try:
        info = await asyncio.to_thread(extract_youtube_info, url)
    except Exception as e:
        err_text = sanitize_error(e)
        logging.error("Failed to fetch YouTube metadata: %s", err_text)
        if "sign in to confirm" in str(e).lower() or "not a bot" in str(e).lower():
            await update.message.reply_text(
                "YouTube requires valid authentication cookies on the server. "
                "Please refresh <code>cookies.txt</code> and try again.",
                parse_mode="HTML",
            )
            return
        await update.message.reply_text("Failed to fetch video information. Please try again.")
        return

    if not info:
        await update.message.reply_text("Could not find video information for this link.")
        return

    title = info.get("title") or "YouTube Video"
    video_id = info.get("id") or ""
    subtitle_langs = list((info.get("subtitles") or {}).keys())
    resolutions = extract_available_resolutions(info)
    max_height = max(resolutions) if resolutions else None

    context.bot_data[f"yt_{token}"] = {
        "url": url,
        "owner_id": owner_id,
        "title": title,
        "video_id": video_id,
        "max_height": max_height,
        "source_message_id": getattr(update.message, "message_id", None),
        "created_at": time.time(),
    }

    preferred_langs = ["id", "en", "es"]
    available_langs = [lang for lang in preferred_langs if lang in subtitle_langs]

    if resolutions:
        video_buttons = [
            InlineKeyboardButton(f"{res}p", callback_data=f"yt|video|{res}|{token}")
            for res in resolutions
        ]
    else:
        video_buttons = [InlineKeyboardButton("Best", callback_data=f"yt|video||{token}")]

    keyboard = [video_buttons]
    row = [InlineKeyboardButton("MP3", callback_data=f"yt|audio||{token}")]
    if available_langs:
        row.append(InlineKeyboardButton("Subtitle", callback_data=f"yt|submenu||{token}"))
    row.append(InlineKeyboardButton("Cancel", callback_data=f"yt|cancel||{token}"))
    keyboard.append(row)

    active_count = len(snapshot())
    stack_note = (
        f"\n\nActive downloads: <b>{active_count}</b> (use <code>/status</code> to inspect)"
        if active_count
        else ""
    )

    safe_user = html.escape(_user_tag(update.effective_user))
    logging.info("[YT] Offered formats to %s for '%s'", _user_tag(update.effective_user), title)
    await update.message.reply_text(
        f"<b>{html.escape(title)}</b>\n"
        f"Select format (locked to {safe_user}):{stack_note}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def yt_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    parts = (query.data or "").split("|")
    if len(parts) != 4:
        return await query.answer("Invalid request.", show_alert=True)

    _, mode, resolution, token = parts
    session = context.bot_data.get(f"yt_{token}")
    if not session:
        return await query.answer("Session expired. Please send the link again.", show_alert=True)

    owner_id = session.get("owner_id")
    user_id = (
        query.from_user.id
        if getattr(query, "from_user", None)
        else (update.effective_user.id if update.effective_user else None)
    )
    if owner_id and user_id and user_id != owner_id:
        caller = _user_tag(query.from_user or update.effective_user)
        logging.warning("[YT] Unauthorized button click by %s (owner: %s)", caller, owner_id)
        return await query.answer(
            "This button belongs to the user who requested the link.",
            show_alert=True,
        )

    await query.answer()
    if mode == "cancel":
        context.bot_data.pop(f"yt_{token}", None)
        logging.info("[YT] %s cancelled format selection", _user_tag(query.from_user or update.effective_user))
        return await query.edit_message_text("Cancelled.")

    if mode == "submenu":
        url = session["url"]
        logging.info("[YT] %s opened subtitle menu for '%s'", _user_tag(query.from_user or update.effective_user), session.get("title", ""))
        try:
            info = await asyncio.to_thread(extract_youtube_info, url)
            subtitles = info.get("subtitles") or {}
        except Exception:
            subtitles = {}

        langs = [lang for lang in ["id", "en", "es"] if lang in subtitles]
        if not langs:
            return await query.edit_message_text("No subtitles available for this video.")

        buttons = [
            InlineKeyboardButton(
                f"{flag_for_lang(lang)} ({lang.upper()})" if flag_for_lang(lang) else lang.upper(),
                callback_data=f"yt|sub|{lang}|{token}",
            )
            for lang in langs
        ]
        rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
        rows.append([InlineKeyboardButton("Cancel", callback_data=f"yt|cancel||{token}")])
        return await query.edit_message_text(
            "Select subtitle language:", reply_markup=InlineKeyboardMarkup(rows)
        )

    if mode == "sub":
        url = session["url"]
        context.bot_data.pop(f"yt_{token}", None)
        lang = resolution or "id"
        caller = _user_tag(query.from_user or update.effective_user)
        logging.info("[YT] %s requested subtitle (%s) for '%s'", caller, lang.upper(), session.get("title", ""))
        status = await query.edit_message_text("Downloading subtitle...")
        result = await asyncio.to_thread(download_subtitle, url, lang=lang)
        if not result:
            return await status.edit_text("Failed to download subtitle.")

        sub_path, sub_title = result
        try:
            with open(sub_path, "rb") as f:
                await status.delete()
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=InputFile(f, filename=os.path.basename(sub_path)),
                    caption=f"Subtitle ({lang.upper()}): {sub_title}",
                )
            logging.info("[YT] Sent subtitle (%s) to chat %s: %s", lang.upper(), query.message.chat_id, sub_title)
        except Exception as e:
            logging.error("Failed to send subtitle: %s", sanitize_error(e))
            await status.edit_text("Failed to send subtitle.")
        finally:
            if os.path.exists(sub_path):
                try:
                    os.remove(sub_path)
                except OSError:
                    pass
        return

    context.bot_data.pop(f"yt_{token}", None)
    url = session["url"]
    title = session["title"]
    video_id = session.get("video_id") or ""
    max_height = session.get("max_height")
    if mode == "video" and resolution and resolution.isdigit() and max_height and int(resolution) > max_height:
        resolution = str(max_height)
    user_tag = _user_tag(update.effective_user)

    if video_id:
        try:
            cached = await asyncio.to_thread(
                find_cached_youtube_file,
                video_id,
                mode,
                resolution or None,
                DRIVE_FOLDER_ID or None,
            )
            if cached:
                size_note = f" ({cached['size'] / 1024**2:.1f} MB)" if cached.get("size") else ""
                logging.info(
                    "[YT] Cache hit on Drive for %s (%s %s): %s",
                    video_id,
                    mode,
                    resolution or "default",
                    cached["link"],
                )
                return await query.edit_message_text(
                    f"Already available on Google Drive{size_note}:\n{cached['link']}",
                    disable_web_page_preview=True,
                )
        except Exception as cache_err:
            logging.warning("[YT] Drive cache lookup skipped: %s", sanitize_error(cache_err))

    job_id = token[:4]
    logging.info(
        "[YT] %s queued %s download (res: %s) for '%s'",
        user_tag,
        mode,
        resolution or "default",
        title,
    )
    add_job(job_id, user_tag, title)
    status = await query.edit_message_text(f"Queued: {title}...")

    filepath = None
    loop = asyncio.get_running_loop()
    yt_props = build_youtube_app_properties(video_id, mode, resolution or None) if video_id else None

    try:
        async with get_download_semaphore():
            update_job(job_id, stage="Downloading")
            await _safe_edit_text(status, f"Downloading: {title}...")

            last_edit = [0.0]

            def _progress(pct: int) -> None:
                update_job(job_id, progress=pct)
                now = time.time()
                if now - last_edit[0] >= 4.0:
                    last_edit[0] = now
                    asyncio.run_coroutine_threadsafe(
                        _safe_edit_text(status, f"Downloading {title}: {pct}%"),
                        loop,
                    )

            result = await asyncio.to_thread(
                download_youtube, url, mode=mode, resolution=resolution or None, on_progress=_progress
            )
            if not result:
                return await _safe_edit_text(status, "Download failed. Format may not be available.")

            filepath, final_title = result

        actual_res = resolution or None
        if mode == "video":
            probed_res = await asyncio.to_thread(probe_video_resolution, filepath)
            if probed_res:
                actual_res = str(probed_res)
                if video_id:
                    yt_props = build_youtube_app_properties(video_id, mode, actual_res)

        ext = os.path.splitext(filepath)[1].lstrip(".") or None
        display_name = format_youtube_filename(
            final_title,
            mode=mode,
            resolution=actual_res,
            ext=ext,
        )

        size = os.path.getsize(filepath)
        if size > MAX_TELEGRAM_FILE_SIZE:
            await _upload_and_notify_drive(
                filepath,
                status,
                final_title,
                "YT",
                f"chat {query.message.chat_id}",
                job_id=job_id,
                app_properties=yt_props,
                custom_name=display_name,
                bot=context.bot,
                chat_id=query.message.chat_id,
                requester_tag=user_tag,
                reply_to_message_id=session.get("source_message_id"),
            )
        else:
            try:
                with open(filepath, "rb") as media_file:
                    await status.delete()
                    if mode == "audio":
                        await context.bot.send_audio(
                            chat_id=query.message.chat_id,
                            audio=InputFile(media_file, filename=display_name),
                            title=final_title,
                        )
                    else:
                        await context.bot.send_document(
                            chat_id=query.message.chat_id,
                            document=InputFile(media_file, filename=display_name),
                            caption=final_title,
                        )
                logging.info("[YT] Sent %s to chat %s: %s", mode, query.message.chat_id, final_title)
            except (BadRequest, TimedOut) as tg_err:
                logging.warning(
                    "Telegram direct send failed (%s); falling back to Google Drive.",
                    sanitize_error(tg_err),
                )
                fallback = await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="Telegram upload limit reached. Routing to Google Drive...",
                )
                await _upload_and_notify_drive(
                    filepath,
                    fallback,
                    final_title,
                    "YT",
                    f"chat {query.message.chat_id}",
                    job_id=job_id,
                    app_properties=yt_props,
                    custom_name=display_name,
                    bot=context.bot,
                    chat_id=query.message.chat_id,
                    requester_tag=user_tag,
                    reply_to_message_id=session.get("source_message_id"),
                )
    except Exception as e:
        logging.error("Processing error: %s", sanitize_error(e))
        await context.bot.send_message(chat_id=query.message.chat_id, text="Failed to process video.")
    finally:
        remove_job(job_id)
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


async def download_youtube_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        return await update.message.reply_text("Usage: /yt <YouTube URL>")
    url = context.args[0].strip()
    if not normalize_media_url(url, "youtube"):
        return await update.message.reply_text("Invalid YouTube URL.")
    logging.info("[YT] %s requested: %s", _safe_user(update), url)
    await offer_youtube_format(update, url, context)


async def download_youtube_music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        return await update.message.reply_text("Usage: /ytm <YouTube Music URL>")
    url = context.args[0].strip()
    if not normalize_media_url(url, "youtube") or "music.youtube.com" not in url:
        return await update.message.reply_text("URL must be from music.youtube.com.")

    chat_id = _safe_chat_id(update)
    logging.info("[YTM] %s requested: %s", _safe_user(update), url)
    status = await update.message.reply_text("Downloading audio...")
    filepath = None
    try:
        result = await asyncio.to_thread(download_youtube, url, mode="audio", music=True)
        if not result:
            return await status.edit_text("Failed to download track.")
        filepath, title = result
        ext = os.path.splitext(filepath)[1].lstrip(".") or "mp3"
        display_name = format_youtube_filename(title, mode="audio", ext=ext)
        if os.path.getsize(filepath) > MAX_TELEGRAM_FILE_SIZE:
            await _upload_and_notify_drive(
                filepath,
                status,
                title,
                "YTM",
                f"chat {chat_id}",
                custom_name=display_name,
                bot=context.bot,
                chat_id=getattr(update.message, "chat_id", None),
                requester_tag=_safe_user(update),
                reply_to_message_id=getattr(update.message, "message_id", None),
            )
        else:
            with open(filepath, "rb") as f:
                await status.delete()
                await update.message.reply_audio(
                    audio=InputFile(f, filename=display_name), title=title
                )
            logging.info("[YTM] Sent track to chat %s: %s", chat_id, title)
    except Exception as e:
        logging.error("YouTube Music error: %s", sanitize_error(e))
        await _safe_edit_text(status, "Failed to process YouTube Music track.")
    finally:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


async def download_instagram_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        return await update.message.reply_text("Usage: /ig <Instagram URL>")
    url = context.args[0].strip()
    if not normalize_media_url(url, "instagram"):
        return await update.message.reply_text("Invalid Instagram URL.")

    chat_id = _safe_chat_id(update)
    logging.info("[IG] %s requested: %s", _safe_user(update), url)
    status = await update.message.reply_text("Downloading Instagram media...")
    filepath = None
    try:
        os.makedirs("ig-dump", exist_ok=True)
        outtmpl = f"ig-dump/{uuid.uuid4().hex[:6]}_%(id)s.%(ext)s"
        opts = {
            "quiet": True,
            "noplaylist": True,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
        }

        def _fetch():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info), info.get("title", "Instagram")

        filepath, title = await asyncio.to_thread(_fetch)
        if not os.path.isfile(filepath):
            filepath = os.path.splitext(filepath)[0] + ".mp4"

        if os.path.getsize(filepath) > MAX_TELEGRAM_FILE_SIZE:
            await _upload_and_notify_drive(
                filepath,
                status,
                title,
                "IG",
                f"chat {chat_id}",
                bot=context.bot,
                chat_id=getattr(update.message, "chat_id", None),
                requester_tag=_safe_user(update),
                reply_to_message_id=getattr(update.message, "message_id", None),
            )
        else:
            with open(filepath, "rb") as f:
                await status.delete()
                await update.message.reply_video(
                    video=InputFile(f, filename=os.path.basename(filepath)), caption=title
                )
            logging.info("[IG] Sent media to chat %s: %s", chat_id, title)
    except Exception as e:
        logging.error("Instagram error: %s", sanitize_error(e))
        await _safe_edit_text(status, "Failed to download Instagram media.")
    finally:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


async def tiktok_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    parts = (query.data or "").split("|")
    if len(parts) != 3:
        return await query.answer("Invalid payload.", show_alert=True)

    _, mode, short_id = parts
    data = context.user_data.get(f"tt_{short_id}")
    user_id = (
        query.from_user.id
        if getattr(query, "from_user", None)
        else (update.effective_user.id if update.effective_user else None)
    )
    if not data or not is_tiktok_owner(data, user_id):
        logging.warning("[TIKTOK] Unauthorized button click by user %s", user_id)
        return await query.answer("This button belongs to the requester.", show_alert=True)

    await query.answer()
    url = data.get("video_url") if mode == "video" else data.get("audio_url")
    ext = ".mp4" if mode == "video" else ".mp3"
    status = await query.message.reply_text(f"Downloading TikTok {mode}...")
    filename = None
    try:
        filename = await asyncio.to_thread(download_tiktok_file, url, ext)
        if os.path.getsize(filename) > MAX_TELEGRAM_FILE_SIZE:
            await _upload_and_notify_drive(
                filename,
                status,
                data.get("title", "TikTok"),
                "TIKTOK",
                f"user {user_id}",
                bot=context.bot,
                chat_id=user_id,
                requester_tag=_user_tag(query.from_user),
            )
        else:
            with open(filename, "rb") as f:
                if mode == "audio":
                    await context.bot.send_audio(chat_id=user_id, audio=f, title=data.get("title"))
                else:
                    await context.bot.send_video(chat_id=user_id, video=f, caption=data.get("title"))
            await status.delete()
            logging.info("[TIKTOK] Delivered %s to user %s: %s", mode, user_id, data.get("title"))
    except Exception as e:
        logging.error("TikTok error: %s", sanitize_error(e))
        await _safe_edit_text(status, "Failed to download TikTok.")
    finally:
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except OSError:
                pass
        context.user_data.pop(f"tt_{short_id}", None)


async def convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.reply_to_message or not msg.reply_to_message.video:
        if msg:
            await msg.reply_text("Reply to a video with /convert to extract MP3.")
        return

    video = msg.reply_to_message.video
    video_size = getattr(video, "file_size", None)
    if (
        MAX_TELEGRAM_DOWNLOAD_SIZE > 0
        and video_size
        and video_size > MAX_TELEGRAM_DOWNLOAD_SIZE
    ):
        return await msg.reply_text("Video exceeds Telegram's 20 MB bot limit.")

    user = _safe_user(update)
    logging.info("[CONVERT] %s requested video conversion to audio", user)

    os.makedirs("converted", exist_ok=True)
    run_id = uuid.uuid4().hex[:6]
    in_file = f"converted/{run_id}_in.mp4"
    out_file = f"converted/{run_id}_audio.mp3"
    status = await msg.reply_text("Converting video to MP3...")

    try:
        tg_file = await video.get_file()
        await tg_file.download_to_drive(in_file)

        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-y", "-i", in_file, out_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

        with open(out_file, "rb") as f:
            await status.delete()
            await msg.reply_audio(audio=InputFile(f, filename="audio.mp3"))
        logging.info("[CONVERT] Delivered audio conversion to %s", user)
    except Exception as e:
        logging.error("Convert error: %s", sanitize_error(e))
        await _safe_edit_text(status, "Conversion failed.")
    finally:
        for path in (in_file, out_file):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass


async def _process_tiktok_url(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    logging.info("[TIKTOK] %s sent link: %s", _user_tag(user), url)
    msg = await update.message.reply_text("Detecting TikTok link...")
    try:
        r = await asyncio.to_thread(
            requests.get, "https://tikwm.com/api/", params={"url": url}, timeout=30
        )
        res = r.json()
        data = res.get("data")
        if res.get("code") == 0 and data:
            user_data = context.user_data
            if user_data is None:
                logging.error("TikTok session storage is unavailable for this update")
                await msg.edit_text("Unable to prepare the TikTok download. Please try again.")
                return

            if data.get("images"):
                media_group = [
                    InputMediaPhoto(media=img_url) for img_url in data["images"][:10]
                ]
                try:
                    await context.bot.send_media_group(chat_id=user.id, media=media_group)
                    logging.info("[TIKTOK] Delivered photo album to %s", user.id)
                    await update.message.reply_text(
                        "TikTok photo album sent to your private chat.",
                        reply_to_message_id=update.message.message_id,
                    )
                except Exception as e:
                    logging.error("Failed to send TikTok album privately: %s", sanitize_error(e))
                    await msg.edit_text("Open the bot's private chat, send /start, then resend the TikTok link in the group.")
                else:
                    await msg.delete()
                return

            short_id = str(uuid.uuid4())[:8]
            session = {
                "video_url": data.get("play"),
                "audio_url": data.get("music"),
                "title": data.get("title", "TikTok"),
            }
            for field_name, field_value in (
                ("owner_id", getattr(user, "id", None)),
                ("chat_id", getattr(update.effective_chat, "id", None)),
                ("source_message_id", getattr(update.message, "message_id", None)),
            ):
                if field_value is not None:
                    session[field_name] = field_value
            context.user_data[f"tt_{short_id}"] = session

            try:
                await context.bot.send_message(
                    chat_id=user.id,
                    text="Choose a TikTok format. The result is sent only to your private chat:",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("Video", callback_data=f"tt|video|{short_id}"),
                            InlineKeyboardButton("Audio", callback_data=f"tt|audio|{short_id}"),
                        ]
                    ]),
                )
                await update.message.reply_text(
                    "Format options sent to your private chat. Downloads also go to the private chat.",
                    reply_to_message_id=update.message.message_id,
                )
                logging.info("[TIKTOK] Sent format options to %s", user.id)
                await msg.delete()
            except Exception as e:
                logging.info("TikTok private delivery unavailable: %s", sanitize_error(e))
                context.user_data.pop(f"tt_{short_id}", None)
                await msg.edit_text("Open the bot's private chat, send /start, then resend the TikTok link in the group.")
            return

        await msg.edit_text("Failed to download TikTok: invalid response.")
    except Exception as e:
        logging.error("TikTok error: %s", sanitize_error(e))
        await msg.edit_text(f"Failed to download TikTok: {sanitize_error(e)}")


async def download_tiktok_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not context.args:
        return await update.message.reply_text("Usage: /tt <TikTok URL>")
    url = context.args[0].strip()
    if "tiktok.com" not in url.lower():
        return await update.message.reply_text("Invalid TikTok URL.")
    await _process_tiktok_url(update, context, url)
