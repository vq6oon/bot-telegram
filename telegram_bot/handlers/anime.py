"""Telegram handlers for /anime search, owner-locked inline selection, and Drive/Telegram delivery."""
import asyncio
import html
import logging
import os
import shutil
import time
import uuid
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes

from ..config import ANIME_MAX_EPISODE, MAX_TELEGRAM_FILE_SIZE
from ..services.anime import (
    AnimeCliUnavailableError,
    AnimeNotFoundError,
    VALID_QUALITIES,
    download_anime,
    is_ani_cli_available,
    parse_anime_command_args,
    search_anime,
)
from ..services.drive import sanitize_error
from ..services.job_tracker import (
    add_job,
    get_download_semaphore,
    remove_job,
    snapshot,
    update_job,
)
from .media import _safe_edit_text, _safe_user, _upload_and_notify_drive, _user_tag


def _render_options_message(session: dict, token: str) -> tuple[str, InlineKeyboardMarkup]:
    title = html.escape(session["title"])
    audio_label = "Dub" if session["dub"] else "Sub"
    q = session["quality"]
    qual_label = "Best" if q == "best" else f"{q}p"
    ep = session["episode"]
    owner_tag = html.escape(session["owner_tag"])

    active_count = len(snapshot())
    stack_note = (
        f"\n\nActive downloads: <b>{active_count}</b> (use <code>/status</code> to inspect)"
        if active_count
        else ""
    )

    text = (
        f"<b>{title}</b>\n"
        f"Audio: <b>{audio_label}</b> | Quality: <b>{qual_label}</b> | Episode: <b>{ep}</b>\n"
        f"Controls locked to {owner_tag}.{stack_note}"
    )

    sub_text = "[Sub]" if not session["dub"] else "Sub"
    dub_text = "[Dub]" if session["dub"] else "Dub"

    qual_row = []
    for item in VALID_QUALITIES:
        label = "Best" if item == "best" else f"{item}p"
        btn_text = f"[{label}]" if q == item else label
        qual_row.append(InlineKeyboardButton(btn_text, callback_data=f"anime|qual|{item}|{token}"))

    keyboard = [
        [
            InlineKeyboardButton(sub_text, callback_data=f"anime|audio|sub|{token}"),
            InlineKeyboardButton(dub_text, callback_data=f"anime|audio|dub|{token}"),
        ],
        qual_row,
        [
            InlineKeyboardButton("-10", callback_data=f"anime|step|-10|{token}"),
            InlineKeyboardButton("-1", callback_data=f"anime|step|-1|{token}"),
            InlineKeyboardButton(f"Ep {ep}", callback_data=f"anime|noop||{token}"),
            InlineKeyboardButton("+1", callback_data=f"anime|step|+1|{token}"),
            InlineKeyboardButton("+10", callback_data=f"anime|step|+10|{token}"),
        ],
        [
            InlineKeyboardButton(f"Download Ep {ep}", callback_data=f"anime|go||{token}"),
            InlineKeyboardButton("Cancel", callback_data=f"anime|cancel||{token}"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def download_anime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    query, episode, err = parse_anime_command_args(list(context.args or []))
    if err:
        return await update.message.reply_text(err)

    if not is_ani_cli_available():
        return await update.message.reply_text(
            "Anime downloader (ani-cli) is not installed on this server."
        )

    user = update.effective_user
    owner_tag = _user_tag(user)
    logging.info("[ANIME] %s searched: '%s' (ep: %s)", owner_tag, query, episode or 1)
    status = await update.message.reply_text(f"Searching anime: {query}...")

    try:
        results = await asyncio.to_thread(search_anime, query, 5)
    except AnimeNotFoundError:
        return await _safe_edit_text(status, f"No anime found for '{query}'.")
    except AnimeCliUnavailableError:
        return await _safe_edit_text(
            status, "Anime downloader (ani-cli) is not installed on this server."
        )
    except Exception as exc:
        logging.error("[ANIME] Search error: %s", sanitize_error(exc))
        results = []

    token = uuid.uuid4().hex[:10]
    session = {
        "query": query,
        "results": results,
        "owner_id": user.id,
        "owner_tag": owner_tag,
        "index": 1,
        "title": results[0] if results else query,
        "dub": False,
        "quality": "720",
        "episode": episode or 1,
        "reply_to_message_id": update.message.message_id,
        "created_at": time.time(),
    }
    context.bot_data[f"anime_{token}"] = session

    # Fallback directly to options (-S 1) if search capture returned empty
    if not results:
        text, markup = _render_options_message(session, token)
        return await _safe_edit_text(
            status,
            f"Search list unavailable; defaulting to top match (#1).\n\n{text}",
            parse_mode="HTML",
            reply_markup=markup,
        )

    lines = [f"<b>Search results for {html.escape(query)}</b> (locked to {html.escape(owner_tag)}):", ""]
    pick_buttons = []
    for idx, title in enumerate(results, start=1):
        lines.append(f"{idx}. {html.escape(title)}")
        pick_buttons.append(InlineKeyboardButton(str(idx), callback_data=f"anime|pick|{idx}|{token}"))

    keyboard = [
        pick_buttons,
        [InlineKeyboardButton("Cancel", callback_data=f"anime|cancel||{token}")],
    ]
    await _safe_edit_text(
        status,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def anime_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    parts = (query.data or "").split("|")
    if len(parts) != 4:
        return await query.answer("Invalid request.", show_alert=True)

    _, action, value, token = parts
    session = context.bot_data.get(f"anime_{token}")
    if not session:
        return await query.answer("Session expired. Please run /anime again.", show_alert=True)

    caller = query.from_user or update.effective_user
    caller_id = caller.id if caller else None
    if session.get("owner_id") and caller_id and caller_id != session["owner_id"]:
        logging.warning("[ANIME] Unauthorized button click by %s (owner: %s)", _safe_user(update), session["owner_id"])
        return await query.answer(
            "This button belongs to the user who requested the anime.",
            show_alert=True,
        )

    if action == "noop":
        return await query.answer(f"Selected episode: {session['episode']}")

    await query.answer()

    if action == "cancel":
        context.bot_data.pop(f"anime_{token}", None)
        return await query.edit_message_text("Cancelled.")

    if action == "pick":
        if not value.isdigit():
            return
        idx = int(value)
        results = session.get("results") or []
        if 1 <= idx <= len(results):
            session["index"] = idx
            session["title"] = results[idx - 1]
        text, markup = _render_options_message(session, token)
        return await _safe_edit_text(query.message, text, parse_mode="HTML", reply_markup=markup)

    if action == "audio":
        session["dub"] = value == "dub"
        text, markup = _render_options_message(session, token)
        return await _safe_edit_text(query.message, text, parse_mode="HTML", reply_markup=markup)

    if action == "qual":
        if value in VALID_QUALITIES:
            session["quality"] = value
        text, markup = _render_options_message(session, token)
        return await _safe_edit_text(query.message, text, parse_mode="HTML", reply_markup=markup)

    if action == "step":
        try:
            delta = int(value)
        except ValueError:
            return
        session["episode"] = max(1, min(ANIME_MAX_EPISODE, session["episode"] + delta))
        text, markup = _render_options_message(session, token)
        return await _safe_edit_text(query.message, text, parse_mode="HTML", reply_markup=markup)

    if action != "go":
        return

    # Consume session once download starts
    context.bot_data.pop(f"anime_{token}", None)

    title = session["title"]
    search_query = session["query"]
    index = session["index"]
    episode = session["episode"]
    quality = session["quality"]
    dub = session["dub"]
    user_tag = session["owner_tag"]
    reply_to_id = session.get("reply_to_message_id")
    chat_id = query.message.chat_id

    job_id = token[:4]
    job_label = f"{title} - Ep {episode}"
    add_job(job_id, user_tag, job_label)
    status = await query.edit_message_text(f"Queued: {job_label}...")
    logging.info(
        "[ANIME] %s queued '%s' (index=%s, ep=%s, q=%s, dub=%s)",
        user_tag,
        title,
        index,
        episode,
        quality,
        dub,
    )

    job_dir = None
    try:
        async with get_download_semaphore():
            update_job(job_id, stage="Downloading", progress=0)
            await _safe_edit_text(status, f"Downloading: {job_label}...")
            result = await asyncio.to_thread(
                download_anime,
                search_query,
                index,
                episode,
                quality,
                dub,
                title,
                job_id,
            )

        if not result:
            return await _safe_edit_text(
                status, f"Failed to download {job_label}. Episode or quality may be unavailable."
            )

        filepath, clean_name, job_dir = result
        size = os.path.getsize(filepath)
        if size > MAX_TELEGRAM_FILE_SIZE:
            await _upload_and_notify_drive(
                filepath,
                status,
                job_label,
                "ANIME",
                chat_id,
                job_id=job_id,
                custom_name=clean_name,
                bot=context.bot,
                chat_id=chat_id,
                requester_tag=user_tag,
                reply_to_message_id=reply_to_id,
            )
        else:
            try:
                with open(filepath, "rb") as media_file:
                    await status.delete()
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=InputFile(media_file, filename=clean_name),
                        caption=job_label,
                    )
                logging.info("[ANIME] Sent %s to chat %s", clean_name, chat_id)
            except (BadRequest, TimedOut) as tg_err:
                logging.warning(
                    "[ANIME] Telegram send failed (%s); routing to Google Drive.",
                    sanitize_error(tg_err),
                )
                fallback = await context.bot.send_message(
                    chat_id=chat_id,
                    text="Telegram upload limit reached. Routing to Google Drive...",
                )
                await _upload_and_notify_drive(
                    filepath,
                    fallback,
                    job_label,
                    "ANIME",
                    chat_id,
                    job_id=job_id,
                    custom_name=clean_name,
                    bot=context.bot,
                    chat_id=chat_id,
                    requester_tag=user_tag,
                    reply_to_message_id=reply_to_id,
                )
    except AnimeCliUnavailableError:
        await _safe_edit_text(status, "Anime downloader (ani-cli) is not installed on this server.")
    except Exception as exc:
        logging.error("[ANIME] Processing error: %s", sanitize_error(exc))
        await _safe_edit_text(status, "Failed to process anime download.")
    finally:
        remove_job(job_id)
        if job_dir and os.path.exists(job_dir):
            shutil.rmtree(job_dir, ignore_errors=True)
