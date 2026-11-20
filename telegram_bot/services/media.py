import logging
import os
import requests
import yt_dlp
from urllib.parse import urlparse


def normalize_media_url(url: str, platform: str):
    """Return URL when its host matches supported platform, else None."""
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
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
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
    msg = await context.bot.send_message(chat_id, text="⬇️ Sedang mengunduh...")
    try:
        with requests.get(url, stream=True) as r:
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
                                await msg.edit_text(f"📁 Mengunduh...{bar}")
                            except:
                                pass
        await msg.edit_text("✅ Unduhan selesai.")
        return True
    except Exception as e:
        await msg.edit_text(f"❌ Gagal mengunduh: {e}")
        return False

def download_youtube(url: str, mode: str = "video", resolution: str = None, music: bool = False):
    try:
        normalized_url = normalize_media_url(url, "youtube")
        if not normalized_url:
            return None
        url = normalized_url
        out_dir = "youtube-dump"
        os.makedirs(out_dir, exist_ok=True)
        safe_template = f"{out_dir}/%(id)s_%(title).80s.%(ext)s"
        if mode == "audio":
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": safe_template,
                "restrictfilenames": True,
                "quiet": True,
                "noplaylist": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
        else:
            res_filter = f"[height={resolution}]" if resolution else ""
            ydl_opts = {
                "format": f"bestvideo{res_filter}+bestaudio/best",
                "outtmpl": safe_template,
                "restrictfilenames": True,
                "merge_output_format": "mp4",
                "quiet": True,
                "noplaylist": True,
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = info.get("filepath") or ydl.prepare_filename(info)
            if mode == "audio":
                filepath = os.path.splitext(filepath)[0] + ".mp3"
            elif not filepath.endswith(".mp4"):
                filepath = os.path.splitext(filepath)[0] + ".mp4"
            title = f"{info.get('uploader', '')} - {info.get('title', '')}" if music else info.get("title", "YouTube")
            return filepath, title
    except Exception as e:
        logging.error(f"YouTube download error: {e}")
        return None
