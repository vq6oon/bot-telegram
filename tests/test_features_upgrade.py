"""Tests for new concurrency, button locks, and 20MB limit checks."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram_bot.handlers import drive as drive_handler
from telegram_bot.handlers import media as media_handler
from telegram_bot.services import job_tracker
from telegram_bot.services import media as media_service


class FeatureUpgradeTests(unittest.IsolatedAsyncioTestCase):
    def test_job_tracker_lifecycle(self):
        job_tracker.add_job("job1", "@tester", "Test Video")
        status = job_tracker.format_active_jobs()
        self.assertIn("Test Video", status)
        self.assertIn("@tester", status)
        self.assertIn("Queued", status)

        job_tracker.update_job("job1", stage="Downloading", progress=55)
        status = job_tracker.format_active_jobs()
        self.assertIn("Downloading", status)
        self.assertIn("55%", status)

        job_tracker.remove_job("job1")
        status = job_tracker.format_active_jobs()
        self.assertEqual(status, "No active downloads.")

    async def test_yt_callback_rejects_unauthorized_user(self):
        query = SimpleNamespace(
            data="yt|video|720|testtok",
            from_user=SimpleNamespace(id=999, username="intruder"),
            message=SimpleNamespace(chat_id=123),
            answer=AsyncMock(),
            edit_message_text=AsyncMock(),
        )
        update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
        context = SimpleNamespace(
            bot_data={
                "yt_testtok": {
                    "url": "https://youtu.be/abc",
                    "owner_id": 42,
                    "title": "Private Video",
                }
            }
        )

        with patch.object(media_handler, "download_youtube") as mock_dl:
            await media_handler.yt_callback_handler(update, context)
            mock_dl.assert_not_called()

        query.answer.assert_awaited_once_with(
            "This button belongs to the user who requested the link.", show_alert=True
        )

    async def test_upload_command_rejects_file_over_20mb_before_download(self):
        doc = SimpleNamespace(
            file_id="big-file",
            file_name="heavy.mp4",
            file_unique_id="heavy_1",
            file_size=25 * 1024 * 1024,
        )
        replied = SimpleNamespace(document=doc)
        message = SimpleNamespace(
            reply_to_message=replied,
            reply_text=AsyncMock(),
        )
        user = SimpleNamespace(id=42)
        update = SimpleNamespace(message=message, effective_user=user)
        bot = SimpleNamespace(get_file=AsyncMock())
        context = SimpleNamespace(bot=bot)

        with patch.object(drive_handler, "DRIVE_ALLOWED_USER_IDS", frozenset({42})):
            await drive_handler.upload(update, context)

        bot.get_file.assert_not_called()
        message.reply_text.assert_awaited_once()
        sent_text = message.reply_text.call_args[0][0]
        self.assertIn("20 MB", sent_text)


if __name__ == "__main__":
    unittest.main()
