"""Configuration loader for environment variables."""
import os
from pathlib import Path


def _load_env():
    env_file = Path(__file__).resolve().parents[1] / ".env"
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
GROUP_LAPOR_ID = _int_env("GROUP_LAPOR_ID", 0)

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

# Media downloads
MAX_CONCURRENT_DOWNLOADS = max(1, _int_env("MAX_CONCURRENT_DOWNLOADS", 3))
DOWNLOAD_RATELIMIT_BYTES = _int_env("DOWNLOAD_RATELIMIT_KBPS", 0) * 1024


def get_cookie_file() -> str | None:
    custom = os.environ.get("COOKIE_FILE_PATH", "").strip()
    if custom:
        p = Path(custom)
        if p.is_file() and p.stat().st_size > 0:
            return str(p.resolve())
    root_cookie = Path(__file__).resolve().parents[1] / "cookies.txt"
    if root_cookie.is_file() and root_cookie.stat().st_size > 0:
        return str(root_cookie.resolve())
    cwd_cookie = Path.cwd() / "cookies.txt"
    if cwd_cookie.is_file() and cwd_cookie.stat().st_size > 0:
        return str(cwd_cookie.resolve())
    return None

