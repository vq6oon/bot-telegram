import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from telegram_bot.services import drive


class Request:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class FakeFiles:
    def __init__(self, files):
        self.items = list(files)
        self.deleted = []
        self.updated = []
        self.list_calls = 0

    def list(self, **kwargs):
        self.list_calls += 1
        limit = kwargs.get("pageSize", 100)
        page_token = kwargs.get("pageToken")
        offset = int(page_token or 0)
        page = self.items[offset:offset + limit]
        next_token = offset + limit if offset + limit < len(self.items) else None
        return Request(lambda: {
            "files": [dict(item) for item in page],
            **({"nextPageToken": str(next_token)} if next_token is not None else {}),
        })

    def delete(self, fileId):
        def execute():
            self.deleted.append(fileId)
            self.items = [item for item in self.items if item["id"] != fileId]
            return {}
        return Request(execute)

    def update(self, **kwargs):
        def execute():
            self.updated.append(kwargs)
            return {"id": kwargs["fileId"]}
        return Request(execute)

    def create(self, **kwargs):
        return Request(lambda: {"id": "new-file-id"})


class FakePermissions:
    def create(self, **kwargs):
        return Request(lambda: {})


class FakeService:
    def __init__(self, files, usage=0):
        self.file_api = FakeFiles(files)
        self.usage = usage

    def files(self):
        return self.file_api

    def about(self):
        return SimpleAbout(self.usage)

    def permissions(self):
        return FakePermissions()


class SimpleAbout:
    def __init__(self, usage):
        self.usage = usage

    def get(self, **kwargs):
        return Request(lambda: {"storageQuota": {"usage": str(self.usage)}})


class DriveServiceTests(unittest.TestCase):
    def test_clear_drive_deletes_all_files_over_100(self):
        items = [{"id": f"file-{i}", "name": f"file-{i}"} for i in range(150)]
        service = FakeService(items)
        with patch.object(drive, "get_drive_service", return_value=service), \
             patch.object(drive, "get_or_create_folder", return_value="folder"):
            deleted, total = drive.clear_drive_files_sync("folder")
        self.assertEqual((deleted, total), (150, 150))
        self.assertEqual(len(service.file_api.items), 0)
        self.assertEqual(len(service.file_api.deleted), 150)
        self.assertEqual(service.file_api.list_calls, 3)

    def test_auto_cleanup_deletes_until_threshold(self):
        items = [{"id": f"file-{i}", "name": f"file-{i}", "size": "1"} for i in range(150)]
        service = FakeService(items, usage=150)
        with patch.object(drive, "get_or_create_folder", return_value="folder"):
            drive.auto_cleanup_drive(threshold_bytes=50, service=service, folder_id="folder")
        self.assertEqual(len(service.file_api.deleted), 101)
        self.assertEqual(len(service.file_api.items), 49)
        self.assertEqual(service.file_api.list_calls, 2)

    def test_upload_updates_matching_file_content(self):
        service = FakeService([{"id": "existing-id", "name": "same.bin"}])
        media = object()
        with tempfile.NamedTemporaryFile() as source, \
             patch.object(drive, "get_drive_service", return_value=service), \
             patch.object(drive, "auto_cleanup_drive"), \
             patch.object(drive, "get_or_create_folder", return_value="folder"), \
             patch.object(drive, "MediaFileUpload", return_value=media):
            link = drive.upload_to_drive(source.name, "folder", "same.bin")
        self.assertEqual(link, "https://drive.google.com/file/d/existing-id/view")
        self.assertEqual(len(service.file_api.updated), 1)
        self.assertEqual(service.file_api.updated[0]["fileId"], "existing-id")
        self.assertIs(service.file_api.updated[0]["media_body"], media)

    def test_missing_token_does_not_fall_back_to_cwd(self):
        with tempfile.TemporaryDirectory() as current_dir, tempfile.TemporaryDirectory() as base_dir:
            Path(current_dir, "token.json").write_text('{"token":"decoy"}', encoding="utf-8")
            base_token = Path(base_dir, "token.json")
            with patch.object(drive, "TOKEN_FILE", base_token), \
                 patch.object(drive.Credentials, "from_authorized_user_file") as load_credentials:
                original_cwd = os.getcwd()
                try:
                    os.chdir(current_dir)
                    with self.assertRaises(drive.GoogleDriveAuthError):
                        drive.get_drive_service()
                finally:
                    os.chdir(original_cwd)
            load_credentials.assert_not_called()

    def test_expired_token_refresh_writes_atomic_private_token(self):
        with tempfile.TemporaryDirectory() as token_dir:
            token_path = Path(token_dir, "token.json")
            token_path.write_text("old-token", encoding="utf-8")
            creds = Mock()
            creds.expired = True
            creds.refresh_token = "refresh"
            creds.valid = True
            creds.to_json.return_value = '{"token":"new-token"}'
            with patch.object(drive, "TOKEN_FILE", token_path), \
                 patch.object(drive.Credentials, "from_authorized_user_file", return_value=creds), \
                 patch.object(drive, "build", return_value="service"):
                self.assertEqual(drive.get_drive_service(), "service")
            self.assertEqual(json.loads(token_path.read_text(encoding="utf-8")), {"token": "new-token"})
            self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)
            self.assertEqual(list(Path(token_dir).glob("*.tmp")), [])

    def test_missing_upload_path_fails_before_drive_api_access(self):
        with patch.object(drive, "get_drive_service") as get_service:
            with self.assertRaises(FileNotFoundError):
                drive.upload_to_drive("/path/that/does/not/exist.bin")
        get_service.assert_not_called()

    def test_failed_refresh_preserves_original_token(self):
        with tempfile.TemporaryDirectory() as token_dir:
            token_path = Path(token_dir, "token.json")
            token_path.write_text("old-token", encoding="utf-8")
            creds = Mock()
            creds.expired = True
            creds.refresh_token = "refresh"
            creds.refresh.side_effect = OSError("offline")
            with patch.object(drive, "TOKEN_FILE", token_path), \
                 patch.object(drive.Credentials, "from_authorized_user_file", return_value=creds):
                with self.assertRaises(OSError):
                    drive.get_drive_service()
            self.assertEqual(token_path.read_text(encoding="utf-8"), "old-token")
            self.assertEqual(list(Path(token_dir).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
