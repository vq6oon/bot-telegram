import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class YouTubeMusicCommandTests(unittest.TestCase):
    def test_ytm_command_directly_downloads_audio_from_music_link(self):
        from telegram_bot.handlers import media

        class Message:
            async def reply_text(self, _text, **_kwargs):
                return SimpleNamespace(edit_text=self.edit_text)

            async def edit_text(self, *_args, **_kwargs):
                return None

        update = SimpleNamespace(message=Message())
        context = SimpleNamespace(args=["https://music.youtube.com/watch?v=abc123"])
        with patch.object(media, "download_youtube", return_value=None) as download:
            asyncio.run(media.download_youtube_music_command(update, context))
        download.assert_called_once_with(
            "https://music.youtube.com/watch?v=abc123", mode="audio", music=True
        )

    def test_ytm_command_registered_and_listed_in_menu(self):
        from telegram_bot import app as application
        from telegram_bot.menus.commands import COMMANDS_CAPTION
        from telegram.ext import CommandHandler

        handlers = []
        fake = SimpleNamespace(add_handler=handlers.append)

        class Builder:
            def concurrent_updates(self, *_): return self
            def token(self, *_): return self
            def base_url(self, *_): return self
            def base_file_url(self, *_): return self
            def request(self, *_): return self
            def build(self): return fake

        with patch.object(application, "configure_logging"), \
             patch.object(application, "HTTPXRequest"), \
             patch.object(application, "ApplicationBuilder", return_value=Builder()):
            application.build_application()

        commands = [command for handler in handlers if isinstance(handler, CommandHandler) for command in handler.commands]
        self.assertIn("ytm", commands)
        self.assertIn("/ytm", COMMANDS_CAPTION)


if __name__ == "__main__":
    unittest.main()
