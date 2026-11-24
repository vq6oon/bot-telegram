"""Google Drive service with thread-safe token refresh, HTTP timeouts, and chunked retries."""
import logging
import mimetypes
import os
import random
import re
import ssl
import tempfile
import threading
import time
from pathlib import Path
import httplib2
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from ..config import (
    DRIVE_CLEANUP_THRESHOLD_BYTES,
    DRIVE_FOLDER_NAME,
    DRIVE_HTTP_TIMEOUT_SECONDS,
    DRIVE_UPLOAD_CHUNK_BYTES,
    DRIVE_UPLOAD_MAX_RETRIES,
)

BASE_DIR = Path(__file__).resolve().parents[2]
TOKEN_FILE = BASE_DIR / "token.json"
_token_lock = threading.Lock()
_TRANSIENT_HTTP_STATUS = {408, 429, 500, 502, 503, 504}

_REDACTIONS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"), r"\1[REDACTED]"),
    (re.compile(r'(?i)("?(?:access_token|refresh_token|client_secret|id_token|api_key)"?\s*[:=]\s*"?)([^"\s,&}]+)'), r"\1[REDACTED]"),
    (re.compile(r"(?i)([?&](?:key|token|access_token|refresh_token)=)([^&\s]+)"), r"\1[REDACTED]"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"<>|]+"), "[LOCAL_PATH]"),
    (re.compile(r"/(?:root|home|etc|var|tmp)/[^\s'\"<>|]+"), "[LOCAL_PATH]"),
]


class GoogleDriveAuthError(Exception):
    pass


def sanitize_error(err: Exception) -> str:
    text = f"{type(err).__name__}: {err}"
    for pat, repl in _REDACTIONS:
        text = pat.sub(repl, text)
    return text[:300]


def _escape(query_str: str) -> str:
    return query_str.replace("\\", "\\\\").replace("'", "\\'")


def _format_bytes(num: int) -> str:
    val = float(max(0, num))
    for unit in ["B", "KB", "MB", "GB"]:
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TB"


def _execute_request(req, retries: int = 3):
    """Execute a Drive API request with retries, preserving simple mock compatibility."""
    try:
        return req.execute(num_retries=retries)
    except TypeError as exc:
        if "num_retries" not in str(exc):
            raise
        return req.execute()


def _is_retryable_upload_error(err: Exception) -> bool:
    if isinstance(err, (TimeoutError, OSError, ssl.SSLError, httplib2.HttpLib2Error)):
        return True
    if isinstance(err, HttpError):
        status = getattr(err.resp, "status", None)
        return status in _TRANSIENT_HTTP_STATUS
    return False


def _upload_resumable_with_retries(
    req,
    on_progress=None,
    max_retries: int = DRIVE_UPLOAD_MAX_RETRIES,
):
    """Stream resumable upload chunks with exponential backoff on transient failures."""
    if not hasattr(req, "next_chunk"):
        response = _execute_request(req, retries=3)
        if on_progress:
            on_progress(100)
        return response

    response = None
    attempt = 0
    while response is None:
        try:
            try:
                status, response = req.next_chunk(num_retries=2)
            except TypeError as exc:
                if "num_retries" not in str(exc):
                    raise
                status, response = req.next_chunk()
            attempt = 0
            if status and on_progress:
                on_progress(int(status.progress() * 100))
        except Exception as err:
            if not _is_retryable_upload_error(err) or attempt >= max_retries:
                raise
            attempt += 1
            delay = min(30.0, (2 ** attempt) + random.uniform(0.2, 1.0))
            logging.warning(
                "[DRIVE] Transient upload chunk error (%s); retrying attempt %d/%d in %.1fs",
                sanitize_error(err),
                attempt,
                max_retries,
                delay,
            )
            time.sleep(delay)

    if on_progress:
        on_progress(100)
    return response


def get_drive_service():
    """Build a fresh, thread-isolated Drive v3 client with a socket timeout."""
    token_path = Path(TOKEN_FILE)
    if not token_path.is_file():
        raise GoogleDriveAuthError("token.json not found. Run 'py get_token.py' first.")

    with _token_lock:
        try:
            creds = Credentials.from_authorized_user_file(str(token_path))
        except Exception as e:
            raise GoogleDriveAuthError(f"Corrupt token.json: {sanitize_error(e)}")

        if creds and creds.expired and creds.refresh_token:
            temp = None
            try:
                creds.refresh(Request())
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=token_path.parent,
                    prefix=f".{token_path.name}.",
                    suffix=".tmp",
                    delete=False,
                    encoding="utf-8",
                ) as f:
                    temp = Path(f.name)
                    try:
                        os.chmod(temp, 0o600)
                    except OSError:
                        pass
                    f.write(creds.to_json())
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp, token_path)
            except RefreshError:
                raise GoogleDriveAuthError("Token expired or revoked. Run 'py get_token.py' again.")
            finally:
                if temp and temp.exists():
                    try:
                        temp.unlink()
                    except OSError:
                        pass
        elif not creds or not creds.valid:
            raise GoogleDriveAuthError("Invalid credentials. Run 'py get_token.py'.")

    authed_http = AuthorizedHttp(creds, http=httplib2.Http(timeout=DRIVE_HTTP_TIMEOUT_SECONDS))
    return build("drive", "v3", http=authed_http, cache_discovery=False)


def get_or_create_folder(service, folder_name: str) -> str:
    safe = _escape(folder_name)
    query = f"name='{safe}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = _execute_request(
        service.files().list(q=query, spaces="drive", fields="files(id)", pageSize=1)
    )
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    body = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    folder = _execute_request(service.files().create(body=body, fields="id"))
    return folder["id"]


def auto_cleanup_drive(
    threshold_bytes: int = DRIVE_CLEANUP_THRESHOLD_BYTES,
    service=None,
    folder_id: str | None = None,
):
    svc = service or get_drive_service()
    quota = _execute_request(svc.about().get(fields="storageQuota")).get("storageQuota", {})
    usage = int(quota.get("usage", 0))
    if usage < threshold_bytes:
        return

    folder = folder_id or get_or_create_folder(svc, DRIVE_FOLDER_NAME)
    while usage >= threshold_bytes:
        res = _execute_request(
            svc.files().list(
                q=f"'{folder}' in parents and trashed=false",
                orderBy="createdTime",
                fields="nextPageToken, files(id, size)",
                pageSize=100,
            )
        )
        files = res.get("files", [])
        if not files:
            break

        deleted_any = False
        for f in files:
            try:
                _execute_request(svc.files().delete(fileId=f["id"]))
                deleted_any = True
                usage -= int(f.get("size", 0))
                logging.info("[DRIVE] Auto-cleaned file id: %s", f["id"])
                if usage < threshold_bytes:
                    return
            except Exception as e:
                logging.error("Failed to delete old file: %s", sanitize_error(e))

        if not deleted_any:
            break


def upload_to_drive(
    file_path: str,
    folder_id: str | None = None,
    custom_name: str | None = None,
    on_progress=None,
) -> str:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path.name}")

    svc = get_drive_service()
    folder = folder_id or get_or_create_folder(svc, DRIVE_FOLDER_NAME)
    name = custom_name or path.name
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    media = MediaFileUpload(str(path), mimetype=mime, chunksize=DRIVE_UPLOAD_CHUNK_BYTES, resumable=True)

    res = _execute_request(
        svc.files().list(
            q=f"'{folder}' in parents and name='{_escape(name)}' and trashed=false",
            fields="files(id)",
            pageSize=1,
        )
    )
    existing = res.get("files", [])

    if existing:
        file_id = existing[0]["id"]
        req = svc.files().update(fileId=file_id, body={"name": name}, media_body=media, fields="id")
    else:
        req = svc.files().create(body={"name": name, "parents": [folder]}, media_body=media, fields="id")

    response = _upload_resumable_with_retries(req, on_progress=on_progress)

    file_id = response.get("id")
    logging.info("[DRIVE] Uploaded '%s' (id: %s) to Google Drive", name, file_id)
    try:
        _execute_request(
            svc.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"})
        )
    except Exception as e:
        logging.warning("Failed to set public sharing for %s: %s", name, sanitize_error(e))

    auto_cleanup_drive(threshold_bytes=DRIVE_CLEANUP_THRESHOLD_BYTES, service=svc, folder_id=folder)
    return f"https://drive.google.com/file/d/{file_id}/view"


def get_drive_usage() -> str:
    svc = get_drive_service()
    quota = _execute_request(svc.about().get(fields="storageQuota")).get("storageQuota", {})
    usage = int(quota.get("usage", 0))
    limit = int(quota.get("limit", 0))
    if limit <= 0:
        return f"{_format_bytes(usage)} used (unlimited)"
    free = max(0, limit - usage)
    return f"{_format_bytes(free)} free of {_format_bytes(limit)}"


def list_drive_files_sync(folder_id: str | None = None) -> dict:
    svc = get_drive_service()
    folder = folder_id or get_or_create_folder(svc, DRIVE_FOLDER_NAME)
    quota = _execute_request(svc.about().get(fields="storageQuota")).get("storageQuota", {})
    usage = int(quota.get("usage", 0))
    limit = int(quota.get("limit", 0))
    free = max(0, limit - usage) if limit > 0 else 0

    res = _execute_request(
        svc.files().list(
            q=f"'{folder}' in parents and trashed=false",
            fields="files(id, name, size, createdTime)",
            orderBy="createdTime desc",
            pageSize=20,
        )
    )
    return {
        "files": res.get("files", []),
        "usage_fmt": _format_bytes(usage),
        "free_fmt": _format_bytes(free) if limit > 0 else "Unlimited",
        "limit_fmt": _format_bytes(limit) if limit > 0 else "Unlimited",
    }


def clear_drive_files_sync(folder_id: str | None = None) -> tuple[int, int]:
    svc = get_drive_service()
    folder = folder_id or get_or_create_folder(svc, DRIVE_FOLDER_NAME)
    deleted = 0
    total = 0

    while True:
        res = _execute_request(
            svc.files().list(
                q=f"'{folder}' in parents and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageSize=100,
            )
        )
        files = res.get("files", [])
        if not files:
            break

        total += len(files)
        deleted_any = False
        for item in files:
            try:
                _execute_request(svc.files().delete(fileId=item["id"]))
                deleted += 1
                deleted_any = True
            except Exception:
                pass

        if not deleted_any:
            break

    return deleted, total
