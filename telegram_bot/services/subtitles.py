"""YouTube subtitle helpers with cookies and JS runtime support."""
import logging
import os
import uuid
import yt_dlp
from .drive import sanitize_error
from .media import build_ydl_base_opts, scoped_cookie_file


def flag_for_lang(language: str) -> str:
    flags = {"id": "🇮🇩", "en": "🇬🇧", "es": "🇪🇸"}
    return flags.get(language, "🌐")


def download_subtitle(url: str, lang: str = "id"):
    try:
        os.makedirs("subs", exist_ok=True)
        prefix = uuid.uuid4().hex[:8]
        with scoped_cookie_file() as cookiefile:
            options = build_ydl_base_opts(cookiefile=cookiefile)
            options.update({
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [lang],
                "subtitlesformat": "srt/best",
                "outtmpl": f"subs/{prefix}_%(title).50s.%(ext)s",
            })
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(url, download=True)
                filepath = downloader.prepare_filename(info)
                base = os.path.splitext(filepath)[0]
                for suffix in (f".{lang}.srt", f".{lang}.vtt", ".srt", ".vtt"):
                    candidate = base + suffix
                    if os.path.exists(candidate):
                        return candidate, info.get("title", "YouTube")
        return None
    except Exception as error:
        logging.error("Subtitle download failed: %s", sanitize_error(error))
        return None
