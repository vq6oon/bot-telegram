"""Configuration loader for environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def _load_env():
    env_file = BASE_DIR / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip("\"'"))


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "").strip())
    except ValueError:
        return default


def _whitelist(raw: str, owner_id: int) -> frozenset[int]:
    ids = {owner_id} if owner_id > 0 else set()
    for item in raw.split(","):
        try:
            val = int(item.strip())
            if val > 0:
                ids.add(val)
        except ValueError:
            continue
    return frozenset(ids)


_load_env()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
COOLDOWN_SECONDS = 30
OWNER_ID = _int_env("OWNER_ID", 0)
GITHUB_LINK = os.environ.get("GITHUB_LINK", "")

# Telegram limits
MAX_TELEGRAM_DOWNLOAD_SIZE = 20 * 1024 * 1024  # 20 MB getFile limit
MAX_TELEGRAM_BOT_DOWNLOAD_SIZE = 20 * 1024 * 1024
MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024       # 50 MB bot send limit

# Google Drive
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "").strip()
DRIVE_FOLDER_NAME = os.environ.get("DRIVE_FOLDER_NAME", "Bot-Uploads").strip() or "Bot-Uploads"
DRIVE_ALLOWED_USER_IDS = _whitelist(os.environ.get("DRIVE_ALLOWED_USER_IDS", ""), OWNER_ID)
DRIVE_CLEANUP_THRESHOLD_GB = max(1.0, float(os.environ.get("DRIVE_CLEANUP_THRESHOLD_GB", "14.0") or 14.0))
DRIVE_CLEANUP_THRESHOLD_BYTES = int(DRIVE_CLEANUP_THRESHOLD_GB * (1024**3))
DRIVE_MAX_CONCURRENT_UPLOADS = max(1, _int_env("DRIVE_MAX_CONCURRENT_UPLOADS", 2))
DRIVE_UPLOAD_CHUNK_BYTES = max(1, _int_env("DRIVE_UPLOAD_CHUNK_SIZE_MB", 8)) * 1024 * 1024
DRIVE_HTTP_TIMEOUT_SECONDS = max(30, _int_env("DRIVE_HTTP_TIMEOUT_SECONDS", 180))
DRIVE_UPLOAD_MAX_RETRIES = max(1, _int_env("DRIVE_UPLOAD_MAX_RETRIES", 5))

# Media downloads
MAX_CONCURRENT_DOWNLOADS = max(1, _int_env("MAX_CONCURRENT_DOWNLOADS", 3))
DOWNLOAD_RATELIMIT_BYTES = _int_env("DOWNLOAD_RATELIMIT_KBPS", 0) * 1024

# Anime downloads (ani-cli)
ANI_CLI_BIN = os.environ.get("ANI_CLI_BIN", "ani-cli").strip() or "ani-cli"
ANI_CLI_TIMEOUT_SECONDS = max(30, _int_env("ANI_CLI_TIMEOUT_SECONDS", 600))
ANI_CLI_SEARCH_TIMEOUT_SECONDS = max(10, _int_env("ANI_CLI_SEARCH_TIMEOUT_SECONDS", 30))
ANIME_MAX_EPISODE = max(1, _int_env("ANIME_MAX_EPISODE", 5000))

# YouTube cookies for yt-dlp
_custom_cookies = os.environ.get("YTDLP_COOKIES_FILE", "").strip() or os.environ.get("COOKIE_FILE_PATH", "").strip()
YTDLP_COOKIES_FILE = Path(_custom_cookies) if _custom_cookies else (BASE_DIR / "cookies.txt")


def get_cookie_file() -> str | None:
    env_cookie = os.environ.get("YTDLP_COOKIES_FILE", "").strip() or os.environ.get("COOKIE_FILE_PATH", "").strip()
    candidate = Path(env_cookie) if env_cookie else YTDLP_COOKIES_FILE
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    try:
        if candidate.is_file() and candidate.stat().st_size > 0:
            return str(candidate.resolve())
    except OSError:
        pass
    cwd_cookie = Path.cwd() / "cookies.txt"
    if cwd_cookie.is_file() and cwd_cookie.stat().st_size > 0:
        return str(cwd_cookie.resolve())
    return None

