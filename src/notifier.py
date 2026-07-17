"""Notification delivery (email, Feishu, DingTalk, Telegram)."""
import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from src.config import (
    DINGTALK_WEBHOOK,
    FEISHU_WEBHOOK,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_USER,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

logger = logging.getLogger(__name__)


@dataclass
class Notification:
    """A notification payload."""

    title: str
    body: str
    link: Optional[str] = None


class Notifier:
    """Send notifications to configured channels."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=20.0)

    async def send(self, notification: Notification) -> None:
        """Send notification to all enabled channels."""
        if FEISHU_WEBHOOK:
            await self._send_feishu(notification)
        if DINGTALK_WEBHOOK:
            await self._send_dingtalk(notification)
        if SMTP_HOST:
            await self._send_email(notification)
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            await self._send_telegram(notification)

    async def _send_feishu(self, notification: Notification) -> None:
        raise NotImplementedError("TODO: implement Feishu webhook")

    async def _send_dingtalk(self, notification: Notification) -> None:
        raise NotImplementedError("TODO: implement DingTalk webhook")

    async def _send_email(self, notification: Notification) -> None:
        raise NotImplementedError("TODO: implement SMTP email")

    async def _send_telegram(self, notification: Notification) -> None:
        raise NotImplementedError("TODO: implement Telegram bot")

    async def close(self) -> None:
        await self.client.aclose()
