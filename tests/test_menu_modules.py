import unittest
from telegram_bot.menus.welcome import WELCOME_CAPTION
from telegram_bot.menus.commands import COMMANDS_CAPTION

class MenuContentTests(unittest.TestCase):
    def test_welcome_lists_supported_platform_features(self):
        for item in ("Instagram", "Reels", "TikTok", "Photo", "Audio", "Video", "YouTube Video", "1080P", "720P", "360P", "Subtitle", "YouTube Music (MP3)"):
            with self.subTest(item=item): self.assertIn(item, WELCOME_CAPTION)

    def test_command_menu_does_not_advertise_unregistered_commands(self):
        self.assertNotIn("/rename", COMMANDS_CAPTION)
        for command in ("/start", "/github", "/rules", "/upload", "/lapor", "/id", "/list", "/checkdrive", "/shorten", "/convert"):
            with self.subTest(command=command): self.assertIn(command, COMMANDS_CAPTION)
