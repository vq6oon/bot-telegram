import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram_bot.services import media as media_service


class MediaCommandTests(unittest.TestCase):
    def test_youtube_music_url_is_accepted_as_youtube(self):
        self.assertEqual(
            media_service.normalize_media_url("https://music.youtube.com/watch?v=abc123", "youtube"),
            "https://music.youtube.com/watch?v=abc123",
        )

    def test_youtube_short_link_is_accepted(self):
        self.assertEqual(
            media_service.normalize_media_url("https://youtu.be/abc123", "youtube"),
            "https://youtu.be/abc123",
        )

    def test_wrong_platform_url_is_rejected(self):
        self.assertIsNone(media_service.normalize_media_url("https://instagram.com/p/abc", "youtube"))

    def test_audio_download_uses_safe_filename_and_returns_mp3(self):
        class FakeYDL:
            last_options = None

            def __init__(self, options):
                self.options = options
                FakeYDL.last_options = options

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def extract_info(self, url, download=True):
                return {"id": "abc123", "title": "Title/unsafe", "uploader": "Artist/Name"}

            def prepare_filename(self, info):
                return "youtube-dump/abc123_fixture.webm"

        with patch.object(media_service.yt_dlp, "YoutubeDL", FakeYDL):
            result = media_service.download_youtube("https://music.youtube.com/watch?v=abc123", mode="audio", music=True)

        self.assertIsNotNone(result)
        filepath, title = result
        self.assertTrue(filepath.endswith(".mp3"))
        self.assertEqual(os.path.basename(filepath), "abc123_fixture.mp3")
        self.assertEqual(title, "Artist/Name - Title/unsafe")
        self.assertEqual(FakeYDL.last_options["outtmpl"], "youtube-dump/%(id)s_%(title).80s.%(ext)s")
        self.assertTrue(FakeYDL.last_options["restrictfilenames"])

    def test_plain_text_link_autodetect_removed_and_tt_command_requires_command(self):
        from telegram_bot.handlers import media

        self.assertFalse(hasattr(media, "handle_message"))

        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        with patch.object(media, "_process_tiktok_url", new=AsyncMock()) as tt_mock:
            asyncio.run(media.download_tiktok_command(update, SimpleNamespace(args=[])))
            tt_mock.assert_not_awaited()
            asyncio.run(media.download_tiktok_command(update, SimpleNamespace(args=["https://www.tiktok.com/@u/video/1"])))
            tt_mock.assert_awaited_once()

    def test_yt_command_validates_url_and_opens_format_picker(self):
        from telegram_bot.handlers import media

        update = SimpleNamespace(message=SimpleNamespace(reply_text=AsyncMock()))
        context = SimpleNamespace(args=["https://music.youtube.com/watch?v=abc123"])
        picker = AsyncMock()
        with patch.object(media, "offer_youtube_format", new=picker):
            asyncio.run(media.download_youtube_command(update, context))
        picker.assert_awaited_once_with(update, "https://music.youtube.com/watch?v=abc123", context)

    def test_short_media_commands_are_registered(self):
        from telegram_bot import app as application
        from telegram.ext import CommandHandler

        handlers = []
        fake = SimpleNamespace(add_handler=handlers.append)

        class Builder:
            def concurrent_updates(self, *_): return self
            def token(self, *_): return self
            def request(self, *_): return self
            def build(self): return fake

        with patch.object(application, "configure_logging"), \
             patch.object(application, "HTTPXRequest"), \
             patch.object(application, "ApplicationBuilder", return_value=Builder()):
            application.build_application()

        commands = [command for handler in handlers if isinstance(handler, CommandHandler) for command in handler.commands]
        self.assertIn("yt", commands)
        self.assertIn("ig", commands)

    def test_format_youtube_filename_matches_title_resolution_template(self):
        self.assertEqual(
            media_service.format_youtube_filename("Roblox: Potato/Phone?", mode="video", resolution="1080"),
            "Roblox Potato Phone (1080p).mp4",
        )
        self.assertEqual(
            media_service.format_youtube_filename("Clip Name", mode="video", resolution=None),
            "Clip Name (best).mp4",
        )
        self.assertEqual(
            media_service.format_youtube_filename("Artist - Track", mode="audio"),
            "Artist - Track.mp3",
        )

    def test_yt_callback_uses_formatted_filename_for_telegram_and_drive(self):
        import tempfile
        from telegram_bot.handlers import media

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"video-bytes")
            temp_path = tmp.name

        try:
            query = SimpleNamespace(
                data="yt|video|1080|tok1",
                from_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
                message=SimpleNamespace(chat_id=99),
                answer=AsyncMock(),
                edit_message_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())),
            )
            update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
            bot = SimpleNamespace(send_document=AsyncMock(), send_message=AsyncMock())
            context = SimpleNamespace(
                bot=bot,
                bot_data={
                    "yt_tok1": {
                        "url": "https://youtu.be/abc123",
                        "owner_id": 42,
                        "title": "Cool: Video?",
                        "video_id": "abc123",
                    }
                },
            )
            with patch.object(media, "find_cached_youtube_file", return_value=None), \
                 patch.object(media, "download_youtube", return_value=(temp_path, "Cool: Video?")), \
                 patch.object(media, "MAX_TELEGRAM_FILE_SIZE", 1024 * 1024):
                asyncio.run(media.yt_callback_handler(update, context))

            sent_doc = bot.send_document.call_args.kwargs["document"]
            self.assertEqual(sent_doc.filename, "Cool Video (1080p).mp4")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"big-video-bytes")
            temp_path = tmp.name

        try:
            status_msg = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
            query = SimpleNamespace(
                data="yt|video|720|tok2",
                from_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
                message=SimpleNamespace(chat_id=99),
                answer=AsyncMock(),
                edit_message_text=AsyncMock(return_value=status_msg),
            )
            update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
            bot = SimpleNamespace(send_message=AsyncMock())
            context = SimpleNamespace(
                bot=bot,
                bot_data={
                    "yt_tok2": {
                        "url": "https://youtu.be/abc123",
                        "owner_id": 42,
                        "title": "Big/Clip",
                        "video_id": "abc123",
                        "source_message_id": 55,
                    }
                },
            )
            with patch.object(media, "find_cached_youtube_file", return_value=None), \
                 patch.object(media, "download_youtube", return_value=(temp_path, "Big/Clip")), \
                 patch.object(media, "MAX_TELEGRAM_FILE_SIZE", 1), \
                 patch.object(media, "upload_to_drive", return_value="https://drive.google.com/file/d/x/view") as up:
                asyncio.run(media.yt_callback_handler(update, context))

            self.assertEqual(up.call_args[0][2], "Big Clip (720p).mp4")
            bot.send_message.assert_awaited_once()
            sent_kwargs = bot.send_message.call_args.kwargs
            self.assertEqual(sent_kwargs["chat_id"], 99)
            self.assertEqual(sent_kwargs["reply_to_message_id"], 55)
            self.assertIn("Done (@tester): Big Clip (720p).mp4", sent_kwargs["text"])
            self.assertIn("Saved to Google Drive:\nhttps://drive.google.com/file/d/x/view", sent_kwargs["text"])
            status_msg.delete.assert_awaited_once()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_extract_available_resolutions_filters_unavailable_tiers(self):
        self.assertEqual(
            media_service.extract_available_resolutions({
                "formats": [
                    {"vcodec": "none", "height": None},
                    {"ext": "mhtml", "protocol": "mhtml", "width": 160, "height": 90},
                    {"vcodec": "avc1", "width": 640, "height": 360},
                    {"vcodec": "avc1", "width": 854, "height": 480},
                ]
            }),
            [360, 480],
        )
        self.assertEqual(
            media_service.extract_available_resolutions({
                "formats": [
                    {"vcodec": "avc1", "width": 640, "height": 360},
                    {"vcodec": "avc1", "width": 854, "height": 480},
                    {"vcodec": "avc1", "width": 1280, "height": 720},
                ]
            }),
            [360, 720],
        )
        self.assertEqual(
            media_service.extract_available_resolutions({
                "formats": [{"vcodec": "avc1", "width": 1080, "height": 1920}]
            }),
            [1080],
        )
        self.assertEqual(
            media_service.extract_available_resolutions({
                "formats": [{"vcodec": "avc1", "width": 426, "height": 240}]
            }),
            [240],
        )

    def test_offer_youtube_format_only_lists_available_resolutions(self):
        from telegram_bot.handlers import media

        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42, username="tester", first_name="Tester"))
        context = SimpleNamespace(bot_data={})
        fake_info = {
            "id": "vid720",
            "title": "720p Only Video",
            "formats": [
                {"vcodec": "avc1", "width": 640, "height": 360},
                {"vcodec": "avc1", "width": 1280, "height": 720},
            ],
        }
        with patch.object(media, "extract_youtube_info", return_value=fake_info):
            asyncio.run(media.offer_youtube_format(update, "https://youtu.be/vid720", context))

        markup = message.reply_text.call_args.kwargs["reply_markup"]
        labels = [btn.text for btn in markup.inline_keyboard[0]]
        self.assertEqual(labels, ["360p", "720p"])

    def test_yt_callback_uses_probed_resolution_on_fallback(self):
        import tempfile
        from telegram_bot.handlers import media

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(b"fallback-bytes")
            temp_path = tmp.name

        try:
            query = SimpleNamespace(
                data="yt|video|720|tok3",
                from_user=SimpleNamespace(id=42, username="tester", first_name="Tester"),
                message=SimpleNamespace(chat_id=99),
                answer=AsyncMock(),
                edit_message_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())),
            )
            update = SimpleNamespace(callback_query=query, effective_user=query.from_user)
            context = SimpleNamespace(
                bot=SimpleNamespace(send_message=AsyncMock()),
                bot_data={
                    "yt_tok3": {
                        "url": "https://youtu.be/abc123",
                        "owner_id": 42,
                        "title": "Fallback Clip",
                        "video_id": "abc123",
                        "max_height": 720,
                    }
                },
            )
            with patch.object(media, "find_cached_youtube_file", return_value=None), \
                 patch.object(media, "download_youtube", return_value=(temp_path, "Fallback Clip")), \
                 patch.object(media, "probe_video_resolution", return_value=480), \
                 patch.object(media, "MAX_TELEGRAM_FILE_SIZE", 1), \
                 patch.object(media, "upload_to_drive", return_value="https://drive.google.com/file/d/x/view") as up:
                asyncio.run(media.yt_callback_handler(update, context))

            self.assertEqual(up.call_args[0][2], "Fallback Clip (480p).mp4")
            self.assertEqual(up.call_args[0][4]["yt_res"], "480")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
