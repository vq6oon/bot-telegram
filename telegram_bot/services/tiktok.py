"""TikTok download and per-user callback isolation."""
import logging
import os
import tempfile
import requests

def is_tiktok_owner(data, user_id):
    return data.get("owner_id") == user_id

def download_tiktok_file(url, extension):
    fd, filepath = tempfile.mkstemp(prefix="telegram-tiktok-", suffix=extension)
    try:
        with os.fdopen(fd, "wb") as output:
            with requests.get(url, stream=True, timeout=(10, 120)) as response:
                response.raise_for_status()
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        output.write(chunk)
        return filepath
    except Exception:
        try: os.remove(filepath)
        except FileNotFoundError: pass
        raise
