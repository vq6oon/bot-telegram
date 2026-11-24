"""Tests for new concurrency, button locks, and 20MB limit checks."""
import asyncio
import os
import unittest
from pathlib import Path
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

    def test_get_cookie_file_handles_missing_and_existing(self):
        import tempfile
        from telegram_bot import config

        with patch.dict(os.environ, {"YTDLP_COOKIES_FILE": "non_existent_file.txt", "COOKIE_FILE_PATH": ""}):
            with patch.object(config.Path, "is_file", return_value=False):
                self.assertIsNone(config.get_cookie_file())

        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("# Netscape HTTP Cookie File\n.youtube.com TRUE / FALSE 1700000000 SID abc\n")
            temp_path = tf.name

        try:
            with patch.dict(os.environ, {"YTDLP_COOKIES_FILE": temp_path, "COOKIE_FILE_PATH": ""}):
                self.assertEqual(config.get_cookie_file(), str(Path(temp_path).resolve()))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_scoped_cookie_file_isolates_and_cleans_up(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", delete=False) as tf:
            tf.write("# Netscape HTTP Cookie File\n.youtube.com TRUE / FALSE 1700000000 SID abc\n")
            master_path = tf.name

        try:
            with patch.object(media_service, "resolve_cookies_file", return_value=Path(master_path)):
                with media_service.scoped_cookie_file() as tmp_cookie:
                    self.assertIsNotNone(tmp_cookie)
                    self.assertTrue(os.path.isfile(tmp_cookie))
                    self.assertNotEqual(tmp_cookie, master_path)
                    with open(tmp_cookie, "r", encoding="utf-8") as f:
                        self.assertIn("SID abc", f.read())

                self.assertFalse(os.path.exists(tmp_cookie))
                self.assertTrue(os.path.isfile(master_path))
        finally:
            if os.path.exists(master_path):
                os.remove(master_path)

    def test_yt_dlp_options_include_cookiefile_and_runtimes(self):
        from contextlib import contextmanager
        captured_opts = {}

        class DummyYDL:
            def __init__(self, opts):
                captured_opts.update(opts)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def extract_info(self, url, download=True):
                return {"id": "dummy123", "title": "Test Title"}

            def prepare_filename(self, info):
                return "youtube-dump/dummy123_Test_Title.mp4"

        @contextmanager
        def _mock_scoped():
            yield "/tmp/test_cookies.txt"

        with patch.object(media_service, "scoped_cookie_file", _mock_scoped):
            with patch.object(media_service.yt_dlp, "YoutubeDL", DummyYDL):
                media_service.extract_youtube_info("https://youtu.be/dummy123")
                self.assertEqual(captured_opts.get("cookiefile"), "/tmp/test_cookies.txt")
                self.assertIn("deno", captured_opts.get("js_runtimes", {}))
                self.assertIn("node", captured_opts.get("js_runtimes", {}))

                captured_opts.clear()
                media_service.download_youtube("https://youtu.be/dummy123")
                self.assertEqual(captured_opts.get("cookiefile"), "/tmp/test_cookies.txt")

    async def test_offer_youtube_format_handles_cookie_block(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        user = SimpleNamespace(id=42, username="tester", first_name="Tester")
        update = SimpleNamespace(message=message, effective_user=user)
        context = SimpleNamespace(bot_data={})

        with patch.object(
            media_handler,
            "extract_youtube_info",
            side_effect=RuntimeError("Sign in to confirm you're not a bot"),
        ):
            await media_handler.offer_youtube_format(update, "https://youtu.be/dummy", context)

        message.reply_text.assert_awaited_once()
        reply_call = message.reply_text.call_args[0][0]
        self.assertIn("requires valid authentication cookies", reply_call)
        self.assertIn("cookies.txt", reply_call)


if __name__ == "__main__":
    unittest.main()
