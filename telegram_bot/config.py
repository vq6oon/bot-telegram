"""Configuration and local env loading."""
import os
from pathlib import Path


def _load_local_env():
    path = Path(__file__).resolve().parents[1] / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _parse_int_env(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_float_env(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_id_whitelist(raw: str, owner_id: int) -> frozenset[int]:
    """Parse comma-separated Telegram user IDs; always include valid OWNER_ID."""
    allowed: set[int] = set()
    if owner_id > 0:
        allowed.add(owner_id)
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        try:
            uid = int(token)
            if uid > 0:
                allowed.add(uid)
        except ValueError:
            continue
    return frozenset(allowed)


_load_local_env()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
COOLDOWN_SECONDS = 30

MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024
DRIVE_FOLDER_NAME = os.environ.get("DRIVE_FOLDER_NAME", "Bot-Uploads").strip() or "Bot-Uploads"
OWNER_ID = _parse_int_env("OWNER_ID", 0)
GITHUB_LINK = os.environ.get("GITHUB_LINK", "")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "").strip()
GROUP_LAPOR_ID = _parse_int_env("GROUP_LAPOR_ID", 0)

# Security & Concurrency settings for Google Drive
DRIVE_ALLOWED_USER_IDS = _parse_id_whitelist(
    os.environ.get("DRIVE_ALLOWED_USER_IDS", ""), OWNER_ID
)
DRIVE_CLEANUP_THRESHOLD_GB = max(1.0, _parse_float_env("DRIVE_CLEANUP_THRESHOLD_GB", 14.0))
DRIVE_CLEANUP_THRESHOLD_BYTES = int(DRIVE_CLEANUP_THRESHOLD_GB * (1024**3))
DRIVE_MAX_CONCURRENT_UPLOADS = max(1, _parse_int_env("DRIVE_MAX_CONCURRENT_UPLOADS", 2))
