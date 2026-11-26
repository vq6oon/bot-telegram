import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram_bot.handlers import media

class TikTokConcurrencyTests(unittest.TestCase):
    def test_callback_without_user_data_skips_tiktok_session(self):
        async def run():
            user = SimpleNamespace(id=42, username="u", first_name="User")
            message = SimpleNamespace(
                message_id=51,
                reply_text=AsyncMock(return_value=SimpleNamespace(edit_text=AsyncMock())),
            )
            update = SimpleNamespace(
                message=message,
                effective_user=user,
                effective_chat=SimpleNamespace(id=-1007),
            )
            context = SimpleNamespace(user_data=None)
            response = SimpleNamespace(
                json=lambda: {
                    "code": 0,
                    "data": {"play": "https://cdn.test/video.mp4", "title": "T"},
                }
            )

            with patch.object(media.requests, "get", return_value=response):
                await media._process_tiktok_url(
                    update, context, "https://www.tiktok.com/@x/video/123"
                )

            message.reply_text.assert_awaited_once_with("Detecting TikTok link...")
            status = message.reply_text.await_args.return_value
            status.edit_text.assert_awaited_once_with(
                "Unable to prepare the TikTok download. Please try again."
            )

        asyncio.run(run())

    def test_two_group_links_get_independent_private_choices(self):
        async def run():
            sent=[]
            class Message:
                chat_id=-1007
                message_id=51
                text="https://www.tiktok.com/@x/video/123"
                def __init__(self): self.from_user=SimpleNamespace(username="u",first_name="User",id=42)
                async def reply_text(self,text,**kwargs):
                    sent.append(("reply",text,kwargs)); return SimpleNamespace(edit_text=lambda *_: asyncio.sleep(0),delete=lambda:asyncio.sleep(0))
                async def reply_media_group(self,*a,**k): return []
            class Bot:
                async def send_message(self,**kwargs): sent.append(("private",kwargs)); return SimpleNamespace()
                async def send_video(self,**kwargs): sent.append(("delivery",kwargs)); return SimpleNamespace()
            class Response:
                def json(self): return {"code":0,"data":{"play":"https://cdn.test/v.mp4","music":"https://cdn.test/a.mp3","title":"T"}}
            contexts=[SimpleNamespace(user_data={},bot=Bot(),args=["https://www.tiktok.com/@x/video/123"]),SimpleNamespace(user_data={},bot=Bot(),args=["https://www.tiktok.com/@x/video/123"])]
            updates=[SimpleNamespace(message=Message(),effective_user=Message().from_user,effective_chat=SimpleNamespace(id=-1007)) for _ in range(2)]
            with patch.object(media.requests,"get",return_value=Response()):
                await asyncio.gather(*(media.download_tiktok_command(u,c) for u,c in zip(updates,contexts)))
            keyboard_msgs=[x for x in sent if x[0]=="private" and "Choose a TikTok format" in x[1].get("text","")]
            confirmations=[x for x in sent if x[0]=="reply" and "Format options sent" in x[1]]
            self.assertEqual(len(keyboard_msgs),2)
            self.assertEqual(len(confirmations),2)
            self.assertTrue(all(kw.get("reply_to_message_id")==51 for _,text,kw in confirmations))
            self.assertTrue(all("owner_id" in c.user_data[next(iter(c.user_data))] for c in contexts))
        asyncio.run(run())
