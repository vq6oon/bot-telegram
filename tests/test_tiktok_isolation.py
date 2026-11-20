import os
import unittest
from unittest.mock import patch
from telegram_bot.services.tiktok import download_tiktok_file, is_tiktok_owner

class FakeResponse:
    headers = {"Content-Length": "4"}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def raise_for_status(self): pass
    def iter_content(self, chunk_size): yield b"test"

class TikTokIsolationTests(unittest.TestCase):
    def test_unique_files(self):
        with patch("telegram_bot.services.tiktok.requests.get", return_value=FakeResponse()):
            first = download_tiktok_file("https://media.test/a", ".mp4")
            second = download_tiktok_file("https://media.test/b", ".mp4")
        try:
            self.assertNotEqual(first, second)
            self.assertTrue(os.path.basename(first).startswith("telegram-tiktok-"))
            with open(first, "rb") as f: self.assertEqual(f.read(), b"test")
            with open(second, "rb") as f: self.assertEqual(f.read(), b"test")
        finally:
            for path in (first, second):
                if os.path.exists(path): os.remove(path)

    def test_tiktok_callback_rejects_other_user(self):
        import asyncio
        from types import SimpleNamespace
        from telegram_bot.handlers import media
        query = SimpleNamespace(data="tt|video|abc12345", message=SimpleNamespace(chat_id=-1007))
        query.answer = lambda *a, **k: asyncio.sleep(0)
        query.edit_message_text = lambda *a, **k: asyncio.sleep(0)
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=99))
        context = SimpleNamespace(user_data={"tt_abc12345": {"owner_id": 42}}, bot=SimpleNamespace())
        with patch.object(media, "is_tiktok_owner", return_value=False), patch.object(media, "download_tiktok_file") as downloader:
            asyncio.run(media.tiktok_callback_handler(update, context))
            downloader.assert_not_called()

    def test_owner_check(self):
        self.assertTrue(is_tiktok_owner({"owner_id": 42, "chat_id": -1007}, 42))
        self.assertFalse(is_tiktok_owner({"owner_id": 42, "chat_id": -1007}, 99))
        self.assertFalse(is_tiktok_owner({}, 42))
