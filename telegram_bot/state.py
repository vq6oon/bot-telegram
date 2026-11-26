"""Process-local cooldown and startup state."""
from datetime import datetime

user_cooldowns = {}
BOT_START = datetime.now()
