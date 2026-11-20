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

    def test_group_youtube_music_link_routes_to_audio_downloader(self):
        from telegram_bot.handlers import media

        class Message:
            text = "https://music.youtube.com/watch?v=abc123"

            async def reply_text(self, _text, **_kwargs):
                return SimpleNamespace(edit_text=self.edit_text, delete=self.delete)

            async def reply_audio(self, **_kwargs):
                return None

            async def edit_text(self, *_args, **_kwargs):
                return None

            async def delete(self):
                return None

        update = SimpleNamespace(
            message=Message(),
            effective_user=SimpleNamespace(username=None, first_name="Test", id=1),
            effective_chat=SimpleNamespace(id=1),
        )
        with patch.object(media, "download_youtube", return_value=None) as download:
            asyncio.run(media.handle_message(update, SimpleNamespace()))
        download.assert_called_once_with(
            "https://music.youtube.com/watch?v=abc123", mode="audio", music=True
        )

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


if __name__ == "__main__":
    unittest.main()
