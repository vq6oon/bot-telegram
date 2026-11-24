"""Media download services with JS runtimes, scoped cookies, and resilient yt-dlp formats."""
import logging
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
import requests
import yt_dlp
from ..config import DOWNLOAD_RATELIMIT_BYTES, YTDLP_COOKIES_FILE, get_cookie_file
from .drive import sanitize_error


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
    if not any(host == domain or host.endswith("." + domain) for domain in allowed):
        return None
    return candidate


def resolve_cookies_file() -> Path | None:
    cookie_str = get_cookie_file()
    if cookie_str:
        p = Path(cookie_str)
        if p.is_file() and p.stat().st_size > 0:
            return p

    candidate = Path(YTDLP_COOKIES_FILE)
    if not candidate.is_absolute():
        candidate = Path(__file__).resolve().parents[2] / candidate
    try:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    except OSError:
        return None
    return None


@contextmanager
def scoped_cookie_file():
    master = resolve_cookies_file()
    if not master:
        yield None
        return

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="ytdlp-cookies-", suffix=".txt", delete=False) as tmp:
            temp_path = tmp.name
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        shutil.copyfile(master, temp_path)
        yield temp_path
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def build_ydl_base_opts(
    *,
    ratelimit_bytes: int | None = None,
    progress_hook: Callable[[dict], None] | None = None,
    cookiefile: str | None = None,
) -> dict:
    js_runtimes = {}
    deno_path = shutil.which("deno")
    js_runtimes["deno"] = {"path": deno_path} if deno_path else {}
    node_path = shutil.which("node")
    js_runtimes["node"] = {"path": node_path} if node_path else {}

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "js_runtimes": js_runtimes,
        "remote_components": ["ejs:github"],
        "http_chunk_size": 10 * 1024 * 1024,
        "retries": 5,
        "fragment_retries": 5,
    }
    if cookiefile:
        opts["cookiefile"] = cookiefile
    if ratelimit_bytes and ratelimit_bytes > 0:
        opts["ratelimit"] = int(ratelimit_bytes)
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    return opts


def extract_youtube_info(url: str) -> dict:
    clean_url = normalize_media_url(url, "youtube")
    if not clean_url:
        return {}
    with scoped_cookie_file() as cookiefile:
        opts = build_ydl_base_opts(cookiefile=cookiefile)
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(clean_url, download=False) or {}


extract_youtube_metadata = extract_youtube_info


def generate_progress_bar(downloaded: int, total: int, length: int = 20) -> str:
    if total == 0:
        return "[----------] 0%"
    progress = int(length * downloaded / total)
    bar = "█" * progress + "─" * (length - progress)
    percent = downloaded / total * 100
    return f"[{bar}] {percent:.1f}%"


async def download_file_with_progress(context, url, filename, chat_id) -> bool:
    msg = await context.bot.send_message(chat_id, text="Downloading...")
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
                                await msg.edit_text(f"Downloading... {bar}")
                            except Exception:
                                pass
        await msg.edit_text("Download complete.")
        return True
    except Exception as e:
        logging.error("Direct download failed: %s", sanitize_error(e))
        await msg.edit_text("Download failed.")
        return False


_INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def format_youtube_filename(
    title: str,
    mode: str = "video",
    resolution: str | None = None,
    ext: str | None = None,
) -> str:
    """Build a display filename such as 'Video Title (1080p).mp4'."""
    default_ext = "mp3" if mode == "audio" else "mp4"
    clean_ext = (ext or default_ext).lstrip(".") or default_ext

    cleaned = _INVALID_FILENAME_RE.sub(" ", str(title or ""))
    cleaned = " ".join(cleaned.split()).strip(" .")
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip(" .")
    if not cleaned:
        cleaned = "YouTube Audio" if mode == "audio" else "YouTube Video"

    if mode != "audio":
        raw_res = str(resolution or "").strip()
        if raw_res:
            res_label = f"{raw_res}p" if raw_res.isdigit() else raw_res
        else:
            res_label = "best"
        return f"{cleaned} ({res_label}).{clean_ext}"

    return f"{cleaned}.{clean_ext}"


YOUTUBE_RESOLUTION_TIERS = (360, 480, 720, 1080)
_TIER_LONG_EDGE = (
    (1080, 1900),
    (720, 1260),
    (480, 840),
    (360, 620),
)


def _format_effective_height(fmt: dict) -> int | None:
    if not isinstance(fmt, dict):
        return None
    if fmt.get("vcodec") == "none" or fmt.get("ext") == "mhtml" or fmt.get("protocol") == "mhtml":
        return None
    height = fmt.get("height")
    width = fmt.get("width")
    if not isinstance(height, (int, float)) or height <= 0:
        return None
    h = int(height)
    if isinstance(width, (int, float)) and width > 0:
        w = int(width)
        short_edge = min(w, h)
        long_edge = max(w, h)
        for tier, min_long in _TIER_LONG_EDGE:
            if short_edge >= tier or (long_edge >= min_long and short_edge > tier // 2):
                return max(short_edge, tier) if short_edge >= tier else tier
        return short_edge
    return h


def extract_available_resolutions(info: dict | None) -> list[int]:
    """Return sorted YouTube video resolution tiers available in yt-dlp metadata."""
    if not isinstance(info, dict):
        return []

    formats = info.get("formats") or []
    heights = {h for fmt in formats if (h := _format_effective_height(fmt)) is not None}
    if not heights:
        top = _format_effective_height(info)
        if top:
            heights = {top}
    if not heights:
        return []

    max_height = max(heights)
    available = [tier for tier in YOUTUBE_RESOLUTION_TIERS if tier in heights]
    if available:
        if max_height >= 720 and 480 in available and len(available) > 2:
            return [t for t in available if t != 480]
        return available

    if max_height < YOUTUBE_RESOLUTION_TIERS[0]:
        return [max_height]
    return [tier for tier in YOUTUBE_RESOLUTION_TIERS if tier <= max_height] or [max_height]


def probe_video_resolution(filepath: str) -> int | None:
    """Inspect downloaded video stream resolution via ffprobe, returning None on error."""
    if not filepath or not os.path.isfile(filepath):
        return None
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return None
    try:
        proc = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                filepath,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        lines = (proc.stdout or "").strip().splitlines()
        line = lines[0] if lines else ""
        if "x" not in line:
            return None
        w_str, h_str = line.split("x", 1)
        return _format_effective_height({"width": int(w_str), "height": int(h_str)})
    except Exception:
        return None


def _build_video_format_selector(resolution: str | None) -> tuple[str, list[str]]:
    if resolution and str(resolution).isdigit():
        res = int(resolution)
        fmt = f"bv*[height<={res}]+ba/b[height<={res}]/bv*+ba/b"
        sort_order = [f"res:{res}", "ext:mp4:m4a", "vcodec:h264"]
        return fmt, sort_order
    return "bv*+ba/b", ["ext:mp4:m4a", "vcodec:h264"]


def download_youtube(
    url: str,
    mode: str = "video",
    resolution: str | None = None,
    music: bool = False,
    on_progress: Callable[[int], None] | None = None,
    progress_callback: Callable[[str, float, float], None] | None = None,
    outtmpl: str | None = None,
    ratelimit_bytes: int | None = None,
):
    clean_url = normalize_media_url(url, "youtube")
    if not clean_url:
        return None

    os.makedirs("youtube-dump", exist_ok=True)
    quality_tag = f"_{resolution}p" if resolution else ""
    template = outtmpl or f"youtube-dump/%(id)s{quality_tag}_%(title).80s.%(ext)s"

    def _hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100.0) if total > 0 else 0.0
            speed = float(d.get("speed") or 0.0)
            if on_progress:
                try:
                    on_progress(int(pct))
                except Exception:
                    pass
            if progress_callback:
                try:
                    progress_callback("Downloading", pct, speed)
                except Exception:
                    pass
        elif status == "finished":
            if on_progress:
                try:
                    on_progress(100)
                except Exception:
                    pass
            if progress_callback:
                try:
                    progress_callback("Merging", 100.0, 0.0)
                except Exception:
                    pass

    ratelimit = ratelimit_bytes if ratelimit_bytes is not None else DOWNLOAD_RATELIMIT_BYTES

    try:
        with scoped_cookie_file() as cookiefile:
            opts = build_ydl_base_opts(
                ratelimit_bytes=ratelimit,
                progress_hook=_hook if (on_progress or progress_callback) else None,
                cookiefile=cookiefile,
            )
            opts["outtmpl"] = template

            if mode == "audio":
                opts.update({
                    "format": "bestaudio/best",
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                })
            else:
                fmt, sort_order = _build_video_format_selector(resolution)
                opts.update({
                    "format": fmt,
                    "format_sort": sort_order,
                    "merge_output_format": "mp4",
                })

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(clean_url, download=True)
                if not info:
                    return None

                filepath = None
                requested = info.get("requested_downloads") or []
                if requested and isinstance(requested[0], dict):
                    filepath = requested[0].get("filepath")
                if not filepath:
                    filepath = info.get("filepath") or ydl.prepare_filename(info)

                if mode == "audio":
                    filepath = os.path.splitext(filepath)[0] + ".mp3"
                elif not filepath.endswith(".mp4"):
                    mp4_candidate = os.path.splitext(filepath)[0] + ".mp4"
                    if os.path.isfile(mp4_candidate):
                        filepath = mp4_candidate

                if not filepath:
                    logging.error("YouTube download completed but output path empty")
                    return None

                raw_title = info.get("title") or "YouTube"
                uploader = info.get("uploader") or ""
                title = f"{uploader} - {raw_title}" if (music and uploader) else raw_title
                return filepath, title

    except Exception as e:
        logging.error("YouTube download error: %s", sanitize_error(e))
        return None
