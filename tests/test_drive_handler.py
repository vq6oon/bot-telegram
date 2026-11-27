import asyncio
import unittest
from typing import cast
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram import Bot, File as TelegramFile
from telegram_bot.handlers import drive as drive_handler


class DriveHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_accepts_large_file_when_download_limit_is_disabled(self):
        status = SimpleNamespace(edit_text=AsyncMock())
        msg = SimpleNamespace(
            chat_id=-1001,
            message_id=77,
            reply_to_message=SimpleNamespace(
                document=SimpleNamespace(
                    file_id="large-file",
                    file_name="EvolutionX.zip",
                    file_unique_id="large-1",
                    file_size=2964 * 1024 * 1024,
                )
            ),
            reply_text=AsyncMock(return_value=status),
        )
        update = SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=42))
        file_path = "/tmp/bot-api-files/EvolutionX.zip"
        bot = SimpleNamespace(get_file=AsyncMock())
        context = SimpleNamespace(bot=bot)
        tg_file = TelegramFile.de_json(
            {"file_id": "large-file", "file_unique_id": "large-1", "file_path": file_path},
            cast(Bot, bot),
        )
        bot.get_file.return_value = tg_file

        with patch.object(drive_handler, "MAX_TELEGRAM_DOWNLOAD_SIZE", 0):
            with patch.object(drive_handler, "DRIVE_ALLOWED_USER_IDS", frozenset({42})):
                with patch.object(drive_handler, "upload_to_drive", return_value="https://drive.google.com/file/d/large/view") as up:
                    with patch.object(drive_handler, "get_user_info", return_value="test user"):
                        with patch.object(drive_handler.os.path, "isfile", return_value=True):
                            with patch.object(TelegramFile, "download_to_drive", new_callable=AsyncMock) as local_download:
                                await drive_handler.upload(update, context)

        bot.get_file.assert_awaited_once_with("large-file")
        local_download.assert_awaited_once()
        self.assertEqual(up.call_args.args[2], "EvolutionX.zip")
        self.assertEqual(msg.reply_text.await_args_list[0].args[0], "Downloading EvolutionX.zip from Telegram...")

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

    async def test_upload_supports_video_photo_and_topic_caption_fallback(self):
        cases = [
            (
                SimpleNamespace(
                    reply_to_message=SimpleNamespace(
                        video=SimpleNamespace(file_id="vid-1", file_unique_id="u1", mime_type="video/mp4", file_size=1024)
                    ),
                    reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock())),
                ),
                "vid-1",
                "video_u1.mp4",
            ),
            (
                SimpleNamespace(
                    reply_to_message=SimpleNamespace(
                        photo=[
                            SimpleNamespace(file_id="p-sm", file_unique_id="s1", file_size=100),
                            SimpleNamespace(file_id="p-lg", file_unique_id="l1", file_size=500),
                        ]
                    ),
                    reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock())),
                ),
                "p-lg",
                "photo_l1.jpg",
            ),
            (
                SimpleNamespace(
                    reply_to_message=SimpleNamespace(forum_topic_created=SimpleNamespace(name="Topic")),
                    audio=SimpleNamespace(file_id="aud-1", file_unique_id="a1", file_name="song.mp3", file_size=2048),
                    reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock())),
                ),
                "aud-1",
                "song.mp3",
            ),
        ]

        for message, expected_id, expected_name in cases:
            update = SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=42))
            tg_file = SimpleNamespace(download_to_drive=AsyncMock())
            bot = SimpleNamespace(get_file=AsyncMock(return_value=tg_file))
            context = SimpleNamespace(bot=bot)
            with patch.object(drive_handler, "DRIVE_ALLOWED_USER_IDS", frozenset({42})), \
                 patch.object(drive_handler, "upload_to_drive", return_value="https://drive.google.com/file/d/x/view") as up, \
                 patch.object(drive_handler, "get_user_info", return_value="test user"):
                await drive_handler.upload(update, context)
            bot.get_file.assert_awaited_once_with(expected_id)
            self.assertEqual(up.call_args[0][2], expected_name)

    async def test_upload_supports_external_reply_and_logs_warning_when_media_missing(self):
        ext_msg = SimpleNamespace(
            reply_to_message=None,
            external_reply=SimpleNamespace(
                document=SimpleNamespace(file_id="ext-1", file_name="Clairo.jpg", file_unique_id="e1", file_size=2048)
            ),
            reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock())),
        )
        ext_update = SimpleNamespace(effective_message=ext_msg, effective_user=SimpleNamespace(id=42))
        tg_file = SimpleNamespace(download_to_drive=AsyncMock())
        bot = SimpleNamespace(get_file=AsyncMock(return_value=tg_file))
        context = SimpleNamespace(bot=bot)
        with patch.object(drive_handler, "DRIVE_ALLOWED_USER_IDS", frozenset({42})), \
             patch.object(drive_handler, "upload_to_drive", return_value="https://drive.google.com/file/d/ext/view") as up, \
             patch.object(drive_handler, "get_user_info", return_value="test user"):
            await drive_handler.upload(ext_update, context)
        bot.get_file.assert_awaited_once_with("ext-1")
        self.assertEqual(up.call_args[0][2], "Clairo.jpg")

        miss_msg = SimpleNamespace(
            chat_id=-1001,
            reply_to_message=SimpleNamespace(story=SimpleNamespace(id=9)),
            external_reply=None,
            caption=None,
            reply_text=AsyncMock(),
        )
        miss_update = SimpleNamespace(effective_message=miss_msg, effective_user=SimpleNamespace(id=42))
        with patch.object(drive_handler, "DRIVE_ALLOWED_USER_IDS", frozenset({42})), \
             patch.object(drive_handler, "get_user_info", return_value="test user"), \
             self.assertLogs(level="WARNING") as logs:
            await drive_handler.upload(miss_update, context)
        miss_msg.reply_text.assert_awaited_once()
        self.assertTrue(any("[UPLOAD]" in line and "reply=[story]" in line for line in logs.output))

    async def test_upload_sends_fresh_message_and_deletes_stale_status_when_supported(self):
        status_msg = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
        msg = SimpleNamespace(
            chat_id=-1001,
            message_id=77,
            reply_to_message=SimpleNamespace(
                document=SimpleNamespace(file_id="f-1", file_name="note.txt", file_unique_id="u1", file_size=50)
            ),
            reply_text=AsyncMock(return_value=status_msg),
        )
        update = SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=42))
        tg_file = SimpleNamespace(download_to_drive=AsyncMock())
        bot = SimpleNamespace(get_file=AsyncMock(return_value=tg_file), send_message=AsyncMock())
        context = SimpleNamespace(bot=bot)

        with patch.object(drive_handler, "DRIVE_ALLOWED_USER_IDS", frozenset({42})), \
             patch.object(drive_handler, "upload_to_drive", return_value="https://drive.google.com/file/d/id1/view"), \
             patch.object(drive_handler, "get_user_info", return_value="test user"):
            await drive_handler.upload(update, context)

        bot.send_message.assert_awaited_once()
        kwargs = bot.send_message.call_args.kwargs
        self.assertEqual(kwargs["chat_id"], -1001)
        self.assertEqual(kwargs["reply_to_message_id"], 77)
        self.assertIn("Uploaded: note.txt", kwargs["text"])
        self.assertIn("https://drive.google.com/file/d/id1/view", kwargs["text"])
        status_msg.delete.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
