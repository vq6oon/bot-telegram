"""Track active downloads and limit concurrency."""
import asyncio
import html
import threading
import time
from ..config import MAX_CONCURRENT_DOWNLOADS

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_semaphore: asyncio.Semaphore | None = None


def get_download_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    return _semaphore


def add_job(job_id: str, user_name: str, title: str):
    with _lock:
        _jobs[job_id] = {
            "user": user_name,
            "title": title,
            "stage": "Queued",
            "progress": 0,
            "started": time.time(),
        }


def update_job(job_id: str, stage: str | None = None, progress: int | None = None):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if stage:
            job["stage"] = stage
        if progress is not None:
            job["progress"] = max(0, min(100, int(progress)))


def remove_job(job_id: str):
    with _lock:
        _jobs.pop(job_id, None)


def snapshot() -> dict[str, dict]:
    with _lock:
        return dict(_jobs)


def format_active_jobs() -> str:
    with _lock:
        if not _jobs:
            return "No active downloads."
        lines = [f"Active Downloads ({len(_jobs)}):"]
        for jid, info in _jobs.items():
            user = html.escape(info["user"])
            title = html.escape(info["title"][:45])
            stage = info["stage"]
            pct = info["progress"]
            lines.append(f"• [{jid}] {title} — {user} | {stage} ({pct}%)")
        return "\n".join(lines)
