import asyncio
import base64
import json
import os
import time
from typing import Any, Dict, Union, List, Optional

import httpx
from bilibili_api import Credential
from bilibili_api.video import Video as BiliVideo
from bilibili_api.session import Session, EventType, Event
from bilibili_api.user import User as BiliUser

from core.logging_manager import get_logger
from core.adapter.adapter_utils import IMAdapter
from core.adapter.adapter_info import AdapterInfo
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult
from core.chat import User

from core.chat.message_elements import (
    Text,
    Image,
    Emoji
)


logger = get_logger("bili_dm_adapter", "blue")


class BiliDMAdapter(IMAdapter):
    """BiliBili Direct Message adapter

    Uses bilibili_api.session.Session to listen for incoming private messages
    and send_msg to send replies. Supports TEXT and PICTURE message types.
    """

    def __init__(self, info: AdapterInfo, event_queue: asyncio.Queue):
        super().__init__(info, event_queue)

        # config
        self.bot_uid: str = self.config.get("bot_uid", "")
        self.message_types = ["text", "img", "at", "reply", "emoji", "share_video"]

        self.emoji_dict = self._load_dict(os.path.join(os.path.dirname(os.path.abspath(__file__)), "emoji.json"))

        # credential
        self._credential = Credential(
            sessdata=self.config.get("sesdata", ""),
            bili_jct=self.config.get("bili_jct", ""),
            buvid3=self.config.get("buvid3", ""),
            dedeuserid=self.config.get("dedeuserid", ""),
            ac_time_value=self.config.get("ac_time_value", ""),
        )

        # runtime
        self._session: Optional[Session] = None
        self._running = False
        self._user_info_cache: Dict[int, Dict[str, str]] = {}

    @staticmethod
    def _load_dict(path: str) -> Dict[str, Any]:
        """Load dictionary from file"""
        try:
            with open(path, 'r', encoding="utf-8") as f:
                emoji_json = f.read()
            return json.loads(emoji_json)
        except Exception:
            return {}

    async def start(self):
        """Start the BiliBili DM adapter.

        Creates a bilibili_api Session and registers event handlers
        for TEXT, PICTURE, and SHARE_VIDEO event types. The session
        polls BiliBili's API every ~6 seconds for new private messages.
        """
        if not self._credential.sessdata:
            logger.error("BiliBili credential (sesdata) is not set")
            return

        try:
            self._session = Session(self._credential, debug=False)

            @self._session.on(EventType.TEXT)
            async def on_text(event: Event):
                await self._handle_incoming_event(event, "text")

            @self._session.on(EventType.PICTURE)
            async def on_picture(event: Event):
                await self._handle_incoming_event(event, "picture")

            @self._session.on(EventType.SHARE_VIDEO)
            async def on_share_video(event: Event):
                await self._handle_incoming_event(event, "share_video")

            self._running = True
            logger.info(f"Start listening DM for BiliBili user {self.bot_uid}")
            await self._session.start(exclude_self=True)
        except Exception as e:
            logger.error(f"Failed to start BiliBili DM adapter: {e}")

    async def stop(self):
        """Stop the BiliBili DM adapter"""
        if self._session:
            try:
                self._session.close()
                self._running = False
                logger.info(f"Stopped BiliBili DM adapter for {self.bot_uid}")
            except Exception as e:
                logger.error(f"Error stopping BiliBili DM adapter: {e}")

    def get_client(self):
        return self._session

    # ===== Permission check =====
    def _should_process(self, sender_uid: str) -> bool:
        """Check whether to process messages from this user"""
        if self.permission_mode == "allow_list":
            return sender_uid in self.user_list
        elif self.permission_mode == "deny_list":
            return sender_uid not in self.user_list
        return True

    # ===== User info cache =====
    async def _get_user_nickname(self, uid: int) -> str:
        """Fetch BiliBili user nickname via User().get_user_info(), with in-memory cache."""
        uid_int = int(uid)
        if uid_int in self._user_info_cache:
            return self._user_info_cache[uid_int]["name"]
        try:
            bili_user = BiliUser(uid=uid_int, credential=self._credential)
            info = await bili_user.get_user_info()
            nickname = info.get("name", str(uid))
            self._user_info_cache[uid_int] = info
            return nickname
        except Exception as e:
            logger.warning(f"[BiliDM] Failed to get user info for {uid}: {e}")
            return str(uid)

    # ===== Image download with cookie =====
    async def _download_image_as_base64_url(self, url: str) -> str:
        """Download an image from BiliBili with cookie auth and return as base64 data URL."""
        cookies = {}
        if self._credential.sessdata:
            cookies["SESSDATA"] = self._credential.sessdata
        if self._credential.bili_jct:
            cookies["bili_jct"] = self._credential.bili_jct
        if self._credential.buvid3:
            cookies["buvid3"] = self._credential.buvid3
        if self._credential.dedeuserid:
            cookies["DedeUserID"] = self._credential.dedeuserid
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.get(url, cookies=cookies, headers={
                    "Referer": "https://www.bilibili.com",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                })
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/png")
                b64_str = base64.b64encode(resp.content).decode("utf-8")
                return f"data:{content_type};base64,{b64_str}"
        except Exception as e:
            logger.error(f"[BiliDM] Failed to download image from {url}: {e}")
            return ""

    # ===== Incoming message handler =====
    async def _handle_incoming_event(self, event: Event, msg_kind: str):
        """Unified handler for all incoming private message events.

        Args:
            event: The raw BiliBili Event object.
            msg_kind: One of 'text', 'picture', 'share_video'.
        """
        sender_uid = str(event.sender_uid)
        if not self._should_process(sender_uid):
            return

        try:
            # Fetch real nickname via User().get_user_info()
            nickname = await self._get_user_nickname(event.sender_uid)

            elements: List = []

            if msg_kind == "text":
                # event.content is a str for TEXT
                content = str(event.content) if event.content else ""
                elements.append(Text(content))

            elif msg_kind == "picture":
                # event.content is a Picture object with .url
                # BiliBili IM images require cookie auth; download and convert to base64
                content = event.content
                if hasattr(content, 'url') and content.url:
                    b64_url = await self._download_image_as_base64_url(content.url)
                    if b64_url:
                        elements.append(Image(b64_url))
                    else:
                        elements.append(Text("[Picture download failed]"))
                else:
                    elements.append(Text("[Picture]"))

            elif msg_kind == "share_video":
                # event.content is a Video object; fetch info to build a rich description
                content = event.content
                if isinstance(content, BiliVideo):
                    try:
                        video_info = await content.get_info()
                        title = video_info.get("title", "Unknown")
                        bvid = video_info.get("bvid", "")
                        owner_name = video_info.get("owner", {}).get("name", "Unknown")
                        view = video_info.get("stat", {}).get("view", 0)
                        like = video_info.get("stat", {}).get("like", 0)
                        url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
                        elements.append(
                            Text(f"[Shared Video] {title}\nUP主: {owner_name} | 播放: {view} | 点赞: {like}\n{url}")
                        )
                    except Exception as e:
                        logger.warning(f"[BiliDM] Failed to get video info: {e}")
                        bvid = getattr(content, 'bvid', '')
                        if bvid:
                            elements.append(Text(f"[Shared Video] https://www.bilibili.com/video/{bvid}"))
                        else:
                            elements.append(Text("[Shared Video]"))
                elif hasattr(content, 'bvid') and content.bvid:
                    elements.append(Text(f"[Shared Video] https://www.bilibili.com/video/{content.bvid}"))
                else:
                    elements.append(Text("[Shared Video]"))

            message_chain = MessageChain(elements or [Text("[Unsupported message]")])
            ts = int(event.timestamp) if event.timestamp else int(time.time())

            message_obj = KiraMessageEvent(
                adapter=self.info,
                message_types=self.message_types,
                message=KiraIMMessage(
                    timestamp=ts,
                    sender=User(
                        user_id=sender_uid,
                        nickname=nickname
                    ),
                    is_mentioned=True,
                    message_id=str(event.msg_key),
                    self_id=self.bot_uid,
                    chain=message_chain,
                ),
                timestamp=ts
            )
            self.publish(message_obj)
            logger.info(f"[BiliDM] Received {msg_kind} from {sender_uid}")
        except Exception as e:
            logger.error(f"[BiliDM] Error handling {msg_kind} message: {e}")

    # ===== Send messages (called by core) =====
    async def send_direct_message(self, user_id: Union[int, str], send_message_obj: MessageChain) -> Optional[KiraIMSentResult]:
        """Send direct message to a BiliBili user via bilibili_api send_msg.

        Supports Text and Image elements. Other element types are sent as plain text.
        """
        if not self._credential.sessdata:
            return KiraIMSentResult(ok=False, err="BiliBili credential not configured")

        try:
            from bilibili_api.session import send_msg
            from bilibili_api.session import EventType as SessionEventType
            from bilibili_api.utils.picture import Picture

            for ele in send_message_obj:
                if isinstance(ele, Text):
                    await send_msg(
                        self._credential,
                        int(user_id),
                        SessionEventType.TEXT,
                        ele.text
                    )
                elif isinstance(ele, Image):
                    if ele.image_type == "url":
                        pic = await Picture.load_url(ele.image)
                    else:
                        img_bytes = base64.b64decode(await ele.to_base64())
                        pic = Picture.from_content(img_bytes, "png")
                    await send_msg(
                        self._credential,
                        int(user_id),
                        SessionEventType.PICTURE,
                        pic
                    )
                elif isinstance(ele, Emoji):
                    emoji_content = self.emoji_dict.get(ele.emoji_id, ele.emoji_id)
                    await send_msg(
                        self._credential,
                        int(user_id),
                        SessionEventType.TEXT,
                        emoji_content
                    )
                else:
                    text_content = str(getattr(ele, 'text', '[Message]'))
                    await send_msg(
                        self._credential,
                        int(user_id),
                        SessionEventType.TEXT,
                        text_content
                    )

            logger.info(f"[BiliDM] Sent DM to {user_id}")
            return KiraIMSentResult(ok=True)
        except Exception as e:
            logger.error(f"[BiliDM] Failed to send DM to {user_id}: {e}")
            return KiraIMSentResult(ok=False, err=f"Failed to send direct message: {e}")

    async def send_group_message(self, group_id: Union[int, str], send_message_obj: MessageChain) -> Optional[KiraIMSentResult]:
        """BiliBili DM does not support group messages; falls back to direct message."""
        logger.warning(f"[BiliDM] Group message not supported, redirecting to DM for user {group_id}")
        return await self.send_direct_message(group_id, send_message_obj)


__all__ = ["BiliDMAdapter"]
