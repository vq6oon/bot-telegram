import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from telegram_bot.handlers import media

class TikTokConcurrencyTests(unittest.TestCase):
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
            contexts=[SimpleNamespace(user_data={},bot=Bot()),SimpleNamespace(user_data={},bot=Bot())]
            updates=[SimpleNamespace(message=Message(),effective_user=Message().from_user,effective_chat=SimpleNamespace(id=-1007)) for _ in range(2)]
            with patch.object(media.requests,"get",return_value=Response()):
                await asyncio.gather(*(media.handle_message(u,c) for u,c in zip(updates,contexts)))
            keyboard_msgs=[x for x in sent if x[0]=="private" and "Pilih format" in x[1].get("text","")]
            confirmations=[x for x in sent if x[0]=="reply" and "Pilihan dikirim" in x[1]]
            self.assertEqual(len(keyboard_msgs),2)
            self.assertEqual(len(confirmations),2)
            self.assertTrue(all(kw.get("reply_to_message_id")==51 for _,text,kw in confirmations))
            self.assertTrue(all("owner_id" in c.user_data[next(iter(c.user_data))] for c in contexts))
        asyncio.run(run())
