import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram_bot.handlers.general import contributor
from telegram_bot.menus.commands import COMMANDS_CAPTION
from telegram_bot.menus.contributors import CONTRIBUTORS, CONTRIBUTORS_CAPTION


class ContributorCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_contributor_replies_with_contributor_list(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(message=message)

        await contributor(update, None)

        message.reply_text.assert_awaited_once_with(CONTRIBUTORS_CAPTION)

    def test_contributor_list_uses_menu_style(self):
        self.assertIn("› Contributors", CONTRIBUTORS_CAPTION)
        self.assertIn("Kamui-Bot · v3.0.0", CONTRIBUTORS_CAPTION)
        self.assertIn("@vq6oon", CONTRIBUTORS_CAPTION)
        for name, role in CONTRIBUTORS:
            with self.subTest(name=name):
                self.assertIn(f"{name} · {role}", CONTRIBUTORS_CAPTION)

    def test_menu_advertises_contributor_command(self):
        self.assertIn("/contributor · ", COMMANDS_CAPTION)
