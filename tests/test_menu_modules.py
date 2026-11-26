import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram_bot.handlers import general
from telegram_bot.handlers.general import menu, start
from telegram_bot.menus.commands import ADMIN_COMMANDS_CAPTION, COMMANDS_CAPTION
from telegram_bot.menus.welcome import WELCOME_MESSAGE


class MenuContentTests(unittest.IsolatedAsyncioTestCase):
    def test_regular_menu_lists_public_commands_only(self):
        for item in (
            "Kamui-Bot · v3.0.0", "› Info", "› Download", "› Drive", "› Search", "› Tools",
            "/menu ·", "/yt <url> ·", "/anime <title> [-e <ep>] ·", "@vq6oon",
        ):
            with self.subTest(item=item):
                self.assertIn(item, COMMANDS_CAPTION)
        for admin_command in ("/cleardrive", "/uptime", "/clearcache", "/whois"):
            with self.subTest(admin_command=admin_command):
                self.assertNotIn(admin_command, COMMANDS_CAPTION)
        self.assertNotIn("┌─", COMMANDS_CAPTION)
        self.assertNotIn("/getani", COMMANDS_CAPTION)

    async def test_start_sends_welcome_and_points_to_menu_command(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(message=message)

        await start(update, None)

        message.reply_text.assert_awaited_once_with(WELCOME_MESSAGE)
        self.assertIn("/menu", WELCOME_MESSAGE)
        self.assertNotEqual(WELCOME_MESSAGE, COMMANDS_CAPTION)

    async def test_menu_defaults_to_public_banner_and_caption(self):
        message = SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock())
        update = SimpleNamespace(message=message)

        await menu(update, SimpleNamespace(args=[]))

        message.reply_photo.assert_awaited_once()
        kwargs = message.reply_photo.await_args.kwargs
        self.assertEqual(kwargs["caption"], COMMANDS_CAPTION)
        self.assertTrue(kwargs["photo"].name.endswith("/assets/kamui.png"))
        self.assertNotIn("reply_markup", kwargs)

    async def test_admin_flag_shows_admin_commands_to_owner(self):
        message = SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock())
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=42))

        with patch.object(general, "OWNER_ID", 42, create=True):
            await menu(update, SimpleNamespace(args=["--admin"]))

        message.reply_photo.assert_awaited_once()
        caption = message.reply_photo.await_args.kwargs["caption"]
        self.assertEqual(caption, ADMIN_COMMANDS_CAPTION)
        self.assertIn("› Admin", caption)
        for command in ("/cleardrive", "/uptime", "/clearcache", "/whois <id>"):
            with self.subTest(command=command):
                self.assertIn(command, caption)
        for public_command in ("/yt <url>", "/ytm <url>", "/ig <url>", "/tt <url>",
                               "/anime <title>", "/upload", "/list", "/shorten", "/convert", "/status"):
            with self.subTest(public_command=public_command):
                self.assertNotIn(public_command, caption)
        self.assertLess(len(caption), 1024)

    async def test_admin_flag_denies_non_owner_without_sending_admin_menu(self):
        message = SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock())
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=7))

        with patch.object(general, "OWNER_ID", 42, create=True):
            await menu(update, SimpleNamespace(args=["--admin"]))

        message.reply_photo.assert_not_awaited()
        message.reply_text.assert_awaited_once_with("Owner only.")

    async def test_menu_rejects_unknown_arguments(self):
        message = SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock())
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=7))

        await menu(update, SimpleNamespace(args=["--unknown"]))

        message.reply_photo.assert_not_awaited()
        message.reply_text.assert_awaited_once_with("Usage: /menu [--admin]")

    async def test_menu_command_ignores_callback_updates(self):
        update = SimpleNamespace(message=None)

        await menu(update, None)

    async def test_menu_falls_back_to_text_when_banner_missing(self):
        message = SimpleNamespace(reply_photo=AsyncMock(), reply_text=AsyncMock())
        update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=7))

        with patch("telegram_bot.handlers.general.Path.open", side_effect=FileNotFoundError):
            await menu(update, SimpleNamespace(args=[]))

        message.reply_photo.assert_not_awaited()
        message.reply_text.assert_awaited_once_with(COMMANDS_CAPTION)
        self.assertNotIn("reply_markup", message.reply_text.await_args.kwargs)
