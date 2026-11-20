"""Process-local cooldown and startup state."""
from datetime import datetime

user_cooldowns = {}
BOT_START = datetime.now()
START_IMAGE_FILE_ID = None
