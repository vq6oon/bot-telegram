"""YouTube subtitle helpers."""
import logging
import os
import yt_dlp
from ..config import get_cookie_file


def flag_for_lang(language):
    flags = {"id": "🇮🇩", "en": "🇬🇧", "es": "🇪🇸"}
    return flags.get(language, "🌐")


def download_subtitle(url, lang="id"):
    try:
        os.makedirs("subs", exist_ok=True)
        options = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "srt/best",
            "outtmpl": "subs/%(title).50s.%(ext)s",
            "quiet": True,
            "js_runtimes": {"deno": {}, "node": {}},
            "remote_components": ["ejs:github"],
        }
        cookie_file = get_cookie_file()
        if cookie_file:
            options["cookiefile"] = cookie_file

        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            filepath = downloader.prepare_filename(info)
            base = os.path.splitext(filepath)[0]
            for suffix in ("." + lang + ".srt", "." + lang + ".vtt", ".srt", ".vtt"):
                candidate = base + suffix
                if os.path.exists(candidate):
                    return candidate, info.get("title", "YouTube")
        return None
    except Exception as error:
        logging.error("Subtitle download failed: %s", error)
        return None

