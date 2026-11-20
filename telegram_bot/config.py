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

_load_local_env()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
COOLDOWN_SECONDS = 30

MAX_TELEGRAM_FILE_SIZE = 50 * 1024 * 1024
DRIVE_FOLDER_NAME = os.environ.get("DRIVE_FOLDER_NAME", "Bot-Uploads")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
GITHUB_LINK = os.environ.get("GITHUB_LINK", "")
DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID", "")
GROUP_LAPOR_ID = int(os.environ.get("GROUP_LAPOR_ID", "0"))
