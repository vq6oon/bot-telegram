import logging
from pathlib import Path

def configure_logging():
    logging.basicConfig(handlers=[logging.FileHandler(Path(__file__).resolve().parents[1] / "bot-activity.log", encoding="utf-8"), logging.StreamHandler()], format="[%(asctime)s] [%(levelname)s] %(message)s", level=logging.INFO, datefmt="%Y-%m-%d %H:%M:%S")
    for name in ("httpx", "telegram.bot", "apscheduler"):
        logging.getLogger(name).setLevel(logging.WARNING)
