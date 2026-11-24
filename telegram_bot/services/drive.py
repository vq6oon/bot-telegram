"""Google Drive v3 service with thread-safe token refresh and sanitized logging."""
import logging
import mimetypes
import os
import re
import threading
from pathlib import Path
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from ..config import DRIVE_CLEANUP_THRESHOLD_BYTES, DRIVE_FOLDER_NAME

BASE_DIR = Path(__file__).resolve().parents[2]
TOKEN_FILE = BASE_DIR / "token.json"

_token_lock = threading.Lock()

# Redact tokens, secrets, and local paths in log output
_SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"), r"\1[REDACTED]"),
    (re.compile(r'(?i)("?(?:access_token|refresh_token|client_secret|id_token|api_key)"?\s*[:=]\s*"?)([^"\s,&}]+)'), r"\1[REDACTED]"),
    (re.compile(r"(?i)([?&](?:key|token|access_token|refresh_token)=)([^&\s]+)"), r"\1[REDACTED]"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"<>|]+"), "[LOCAL_PATH]"),
]


class GoogleDriveAuthError(Exception):
    """Raised when Google Drive token is missing, invalid, or expired."""


def sanitize_error(err: Exception) -> str:
    """Strip sensitive tokens and paths from error messages before logging."""
    text = f"{type(err).__name__}: {err}"
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:500]


def _escape_drive_query(value: str) -> str:
    """Escape backslashes and single quotes for Drive query filters."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _format_bytes(num_bytes: int) -> str:
    value = float(max(0, num_bytes))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} PB"


def get_drive_service():
    """Return authenticated Drive v3 client with thread-safe refresh."""
    token_path = TOKEN_FILE if TOKEN_FILE.exists() else Path("token.json")
    if not token_path.exists():
        raise GoogleDriveAuthError(
            "Google Drive token.json not found on server. Run 'python get_token.py' first."
        )

    with _token_lock:
        try:
            creds = Credentials.from_authorized_user_file(str(token_path))
        except Exception as e:
            logging.error("Failed to read Google Drive token: %s", sanitize_error(e))
            raise GoogleDriveAuthError(
                "Invalid or corrupt token.json. Run 'python get_token.py' again."
            ) from e

        if creds and creds.expired and creds.refresh_token:
            temp_file = token_path.with_suffix(".tmp")
            try:
                logging.info("Refreshing expired Google Drive access token...")
                creds.refresh(Request())

                with open(temp_file, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                os.replace(temp_file, token_path)
                try:
                    os.chmod(token_path, 0o600)
                except OSError:
                    pass
                logging.info("Google Drive token refreshed and saved.")
            except RefreshError as e:
                logging.error("Google Drive refresh token expired or revoked: %s", sanitize_error(e))
                raise GoogleDriveAuthError(
                    "Google Drive token expired or revoked. Run 'python get_token.py' again."
                ) from e
            except Exception as e:
                if temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError:
                        pass
                logging.error("Failed to refresh Google Drive token: %s", sanitize_error(e))
                raise
        elif not creds or not creds.valid:
            raise GoogleDriveAuthError(
                "Google Drive credentials invalid without a refresh token. Run 'python get_token.py' again."
            )

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_or_create_folder(service, folder_name: str) -> str:
    safe_folder_name = _escape_drive_query(folder_name)
    query = (
        f"name='{safe_folder_name}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    results = service.files().list(
        q=query, spaces="drive", fields="files(id, name)", pageSize=1
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    folder = service.files().create(
        body={"name": folder_name, "mimeType": "application/vnd.google-apps.folder"},
        fields="id",
    ).execute()
    return folder.get("id")


def auto_cleanup_drive(
    threshold_bytes: int = DRIVE_CLEANUP_THRESHOLD_BYTES,
    service=None,
    folder_id: str | None = None,
):
    """Delete oldest files in target folder when storage exceeds threshold."""
    drive_service = service or get_drive_service()
    quota = drive_service.about().get(fields="storageQuota").execute().get("storageQuota", {})
    usage = int(quota.get("usage", 0))
    if usage < threshold_bytes:
        return

    target_folder = folder_id if folder_id else get_or_create_folder(drive_service, DRIVE_FOLDER_NAME)
    page_token = None

    while usage >= threshold_bytes:
        response = drive_service.files().list(
            q=f"'{target_folder}' in parents and trashed=false",
            orderBy="createdTime",
            fields="nextPageToken, files(id, name, size)",
            pageSize=100,
            pageToken=page_token,
        ).execute()
        files = response.get("files", [])
        if not files:
            break

        for item in files:
            try:
                drive_service.files().delete(fileId=item["id"]).execute()
                file_size = int(item.get("size", 0))
                usage = max(0, usage - file_size)
                logging.info("Auto-cleanup deleted old file: %s", item.get("name", "unknown"))
                if usage < threshold_bytes:
                    return
            except Exception as e:
                logging.error("Auto-cleanup failed to delete file: %s", sanitize_error(e))

        page_token = response.get("nextPageToken")
        if not page_token:
            break


def upload_to_drive(file_path: str, folder_id: str | None = None, custom_name: str | None = None) -> str:
    """Upload file to Drive. Runs synchronously inside asyncio.to_thread."""
    service = get_drive_service()
    target_folder_id = folder_id if folder_id else get_or_create_folder(service, DRIVE_FOLDER_NAME)
    auto_cleanup_drive(
        threshold_bytes=DRIVE_CLEANUP_THRESHOLD_BYTES,
        service=service,
        folder_id=target_folder_id,
    )

    file_name = custom_name if custom_name else os.path.basename(file_path)
    safe_file_name = _escape_drive_query(file_name)

    query = f"'{target_folder_id}' in parents and name='{safe_file_name}' and trashed=false"
    results = service.files().list(
        q=query, spaces="drive", fields="files(id, name)", pageSize=1
    ).execute()
    files = results.get("files", [])

    if files:
        logging.info("File already exists in Drive, reusing ID: %s", file_name)
        file_id = files[0]["id"]
    else:
        mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        file_metadata = {"name": file_name, "parents": [target_folder_id]}
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
        uploaded_file = service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()
        file_id = uploaded_file.get("id")
        service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"}
        ).execute()
        logging.info("Uploaded to Drive: %s (%s)", file_name, mime_type)

    return f"https://drive.google.com/file/d/{file_id}/view"


def get_drive_usage() -> str:
    """Return human-readable storage quota."""
    service = get_drive_service()
    quota = service.about().get(fields="storageQuota").execute().get("storageQuota", {})
    limit = int(quota.get("limit", 0))
    usage = int(quota.get("usage", 0))
    if limit <= 0:
        return f"Used {_format_bytes(usage)} (Unlimited)"
    free = max(0, limit - usage)
    return f"{_format_bytes(free)} / {_format_bytes(limit)}"


def list_drive_files_sync(folder_id: str | None = None) -> dict:
    """Fetch recent 20 files in target folder with quota info."""
    service = get_drive_service()
    target_folder = folder_id if folder_id else get_or_create_folder(service, DRIVE_FOLDER_NAME)

    quota = service.about().get(fields="storageQuota").execute().get("storageQuota", {})
    limit = int(quota.get("limit", 0))
    usage = int(quota.get("usage", 0))
    free = max(0, limit - usage) if limit > 0 else 0

    results = service.files().list(
        q=f"'{target_folder}' in parents and trashed=false",
        fields="files(id, name, size, createdTime)",
        orderBy="createdTime desc",
        pageSize=20,
    ).execute()

    return {
        "files": results.get("files", []),
        "usage_fmt": _format_bytes(usage),
        "free_fmt": _format_bytes(free) if limit > 0 else "Unlimited",
        "limit_fmt": _format_bytes(limit) if limit > 0 else "Unlimited",
    }


def clear_drive_files_sync(folder_id: str | None = None) -> tuple[int, int]:
    """Delete all files in target folder with pagination."""
    service = get_drive_service()
    target_folder = folder_id if folder_id else get_or_create_folder(service, DRIVE_FOLDER_NAME)

    deleted_count = 0
    total_count = 0
    page_token = None

    while True:
        response = service.files().list(
            q=f"'{target_folder}' in parents and trashed=false",
            fields="nextPageToken, files(id, name)",
            pageSize=100,
            pageToken=page_token,
        ).execute()
        files = response.get("files", [])
        total_count += len(files)

        for item in files:
            try:
                service.files().delete(fileId=item["id"]).execute()
                deleted_count += 1
                logging.info("Deleted Drive file: %s", item.get("name", "unknown"))
            except Exception as e:
                logging.warning(
                    "Failed to delete Drive file %s: %s",
                    item.get("name", "unknown"),
                    sanitize_error(e),
                )

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return deleted_count, total_count
