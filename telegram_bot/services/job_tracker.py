"""Track active downloads and enforce download and Drive upload concurrency limits."""
import asyncio
import html
import threading
import time
from ..config import DRIVE_MAX_CONCURRENT_UPLOADS, MAX_CONCURRENT_DOWNLOADS

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_download_semaphores: dict[int, asyncio.Semaphore] = {}
_drive_upload_semaphores: dict[int, asyncio.Semaphore] = {}


def _get_loop_key() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


def _get_loop_semaphore(pool: dict[int, asyncio.Semaphore], limit: int) -> asyncio.Semaphore:
    key = _get_loop_key()
    with _lock:
        sem = pool.get(key)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            pool[key] = sem
        return sem


def get_download_semaphore() -> asyncio.Semaphore:
    """Return a per-event-loop semaphore capping concurrent media downloads."""
    return _get_loop_semaphore(_download_semaphores, MAX_CONCURRENT_DOWNLOADS)


def get_drive_upload_semaphore() -> asyncio.Semaphore:
    """Return a per-event-loop semaphore capping concurrent Google Drive uploads."""
    return _get_loop_semaphore(_drive_upload_semaphores, DRIVE_MAX_CONCURRENT_UPLOADS)


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
            lines.append(f"- [{jid}] {title} - {user} | {stage} ({pct}%)")
        return "\n".join(lines)
