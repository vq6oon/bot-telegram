import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from telegram_bot.handlers import media

class TikTokPhotoPrivacyTests(unittest.TestCase):
    def test_group_photo_album_is_sent_only_to_requester_dm(self):
        async def run():
            events=[]
            class Message:
                text="https://www.tiktok.com/@user/video/123"
                message_id=77
                def __init__(self): self.from_user=SimpleNamespace(id=42,username="u",first_name="User")
                async def reply_text(self,text,**kwargs):
                    events.append(("group_reply",text,kwargs))
                    return SimpleNamespace(edit_text=lambda value: _record(events,"edit",value),delete=lambda: _record(events,"delete",None))
                async def reply_media_group(self,*args,**kwargs): events.append(("group_album",args,kwargs))
            class Bot:
                async def send_media_group(self,**kwargs): events.append(("dm_album",kwargs)); return []
            class Response:
                def json(self): return {"code":0,"data":{"images":["https://cdn.test/one.jpg","https://cdn.test/two.jpg"]}}
            message=Message()
            update=SimpleNamespace(message=message,effective_user=message.from_user,effective_chat=SimpleNamespace(id=-1007))
            context=SimpleNamespace(user_data={},bot=Bot())
            with patch.object(media.requests,"get",return_value=Response()):
                await media.handle_message(update,context)
            self.assertEqual(len([e for e in events if e[0]=="dm_album"]),1)
            self.assertEqual([e[1]["chat_id"] for e in events if e[0]=="dm_album"], [42])
            self.assertFalse(any(e[0]=="group_album" for e in events))
            self.assertFalse(any(e[0]=="group_reply" and ("mengirim" in e[1].lower() or "download" in e[1].lower()) for e in events))
            notice=[e for e in events if e[0]=="group_reply"]
            self.assertTrue(any("pribadi" in e[1].lower() and e[2].get("reply_to_message_id")==77 for e in notice))
        asyncio.run(run())

def _record(events, kind, value):
    events.append((kind,value,{}))
    return asyncio.sleep(0)
