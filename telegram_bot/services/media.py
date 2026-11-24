"""YouTube downloader with Node.js runtime and resilient format fallbacks."""
import logging
import os
import shutil
import uuid
from urllib.parse import urlparse
import requests
import yt_dlp
from .drive import sanitize_error
from ..config import DOWNLOAD_RATELIMIT_BYTES, get_cookie_file


def normalize_media_url(url: str, platform: str) -> str | None:
    candidate = (url or "").strip().strip("<>.,)")
    try:
        host = (urlparse(candidate).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    domains = {
        "youtube": ("youtube.com", "youtu.be"),
        "instagram": ("instagram.com",),
    }
    allowed = domains.get(platform, ())
    if not any(host == d or host.endswith("." + d) for d in allowed):
        return None
    return candidate


def generate_progress_bar(downloaded: int, total: int, length: int = 20):
    if total == 0:
        return "[----------] 0%"
    progress = int(length * downloaded / total)
    bar = "█" * progress + "─" * (length - progress)
    percent = downloaded / total * 100
    return f"[{bar}] {percent:.1f}%"


async def download_file_with_progress(context, url, filename, chat_id):
    msg = await context.bot.send_message(chat_id, text="⬇️ Downloading...")
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 32
            with open(filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            bar = generate_progress_bar(downloaded, total)
                            try:
                                await msg.edit_text(f"📁 Downloading... {bar}")
                            except Exception:
                                pass
        await msg.edit_text("✅ Download complete.")
        return True
    except Exception as e:
        await msg.edit_text(f"❌ Download failed: {sanitize_error(e)}")
        return False


def extract_youtube_info(url: str) -> dict:
    opts = {
        "quiet": True,
        "noplaylist": True,
        "js_runtimes": {"deno": {}, "node": {}},
        "remote_components": ["ejs:github"],
    }
    cookie_file = get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file

    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def download_youtube(
    url: str,
    mode: str = "video",
    resolution: str | None = None,
    music: bool = False,
    on_progress=None,
    outtmpl: str | None = None,
):
    clean_url = normalize_media_url(url, "youtube")
    if not clean_url:
        return None

    os.makedirs("youtube-dump", exist_ok=True)
    template = outtmpl or "youtube-dump/%(id)s_%(title).80s.%(ext)s"

    opts = {
        "quiet": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "outtmpl": template,
        "js_runtimes": {"deno": {}, "node": {}},
        "remote_components": ["ejs:github"],
        "retries": 3,
    }
    cookie_file = get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file

    if DOWNLOAD_RATELIMIT_BYTES > 0:
        opts["ratelimit"] = DOWNLOAD_RATELIMIT_BYTES

    if on_progress:
        def _hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes", 0)
                pct = int(downloaded / total * 100) if total else 0
                on_progress(pct)
        opts["progress_hooks"] = [_hook]

    if mode == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        if resolution and str(resolution).isdigit():
            opts["format"] = f"bv*[height<={resolution}]+ba/b[height<={resolution}]/bv*+ba/b"
        else:
            opts["format"] = "bv*+ba/b"
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{
            "key": "FFmpegVideoConvertor",
            "preferedformat": "mp4",
        }]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            if not info:
                return None

            filename = info.get("filepath") or ydl.prepare_filename(info)
            if mode == "audio":
                filepath = os.path.splitext(filename)[0] + ".mp3"
            elif not filename.endswith(".mp4"):
                mp4_candidate = os.path.splitext(filename)[0] + ".mp4"
                if os.path.isfile(mp4_candidate):
                    filepath = mp4_candidate
                else:
                    filepath = filename
            else:
                filepath = filename

            title = info.get("title", "YouTube")
            if music and info.get("uploader"):
                title = f"{info['uploader']} - {title}"
            return filepath, title

    except Exception as e:
        logging.error("YouTube download failed: %s", sanitize_error(e))
        return None
