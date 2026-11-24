import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from telegram_bot.handlers import drive as drive_handler


class DriveHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_runs_drive_io_in_worker_thread_and_removes_temp_file(self):
        document = type("Document", (), {
            "file_id": "telegram-file",
            "file_name": "report.txt",
            "file_unique_id": "unique",
        })()
        replied_message = type("Message", (), {"document": document})()
        sent_messages = []
        async def reply_text(*args, **kwargs):
            message = type("StatusMessage", (), {})()
            message.edit_text = AsyncMock()
            sent_messages.append(message)
            return message
        message = type("Message", (), {
            "reply_to_message": replied_message,
            "reply_text": reply_text,
        })()
        user = type("User", (), {"id": 42})()
        update = type("Update", (), {"message": message, "effective_user": user})()
        tg_file = type("TelegramFile", (), {"download_to_drive": AsyncMock()})()
        bot = type("Bot", (), {"get_file": AsyncMock(return_value=tg_file)})()
        context = type("Context", (), {"bot": bot})()
        observed = {}
        async def run_in_thread(func, *args):
            observed["func"] = func
            observed["args"] = args
            return "https://drive.google.com/file/d/abc/view"
        with patch.object(drive_handler, "DRIVE_ALLOWED_USER_IDS", frozenset({42})), \
             patch.object(drive_handler.asyncio, "to_thread", side_effect=run_in_thread), \
             patch.object(drive_handler, "get_user_info", return_value="test user"):
            await drive_handler.upload(update, context)
        bot.get_file.assert_awaited_once_with("telegram-file")
        tg_file.download_to_drive.assert_awaited_once()
        upload_path = observed["args"][0]
        self.assertIs(observed["func"], drive_handler.upload_to_drive)
        self.assertEqual(observed["args"][1:], (drive_handler.DRIVE_FOLDER_ID, "report.txt"))
        import os
        self.assertFalse(os.path.exists(upload_path))
        sent_messages[0].edit_text.assert_awaited()


if __name__ == "__main__":
    unittest.main()
