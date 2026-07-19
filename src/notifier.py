"""Notification delivery (email, Feishu, DingTalk, Telegram)."""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from src.config import (
    DINGTALK_WEBHOOK,
    FEISHU_WEBHOOK,
    NOTIFIER_BACKOFF_BASE,
    NOTIFIER_MAX_ATTEMPTS,
    SMTP_HOST,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

logger = logging.getLogger(__name__)


def _format_value(value: float) -> str:
    """Format a dollar value into human-readable B/M/K."""
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.1f}M"
    if value >= 1e3:
        return f"${value / 1e3:.1f}K"
    return f"${int(value)}"


def _format_summary(summary: Optional[dict]) -> str:
    """Format a ReportSummary dict into Chinese notification body."""
    if not summary:
        return ""
    return (
        f"总持仓市值：{_format_value(summary['total_value'])}\n"
        f"新增持仓：{summary['new_positions']} 只\n"
        f"清仓持仓：{summary['sold_positions']} 只\n"
        f"大幅（变化≥20%）增持：{summary['increased_positions']} 只\n"
        f"大幅（变化≥20%）减持：{summary['decreased_positions']} 只"
    )


def _truncate_text(text: str, max_bytes: int = 15000) -> str:
    """Truncate text to fit within Feishu message size limits."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[: max_bytes - 3]
    while truncated:
        try:
            return truncated.decode("utf-8") + "..."
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return "..."


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
        text = notification.title
        if notification.body:
            text += f"\n\n{notification.body}"
        if notification.link:
            text += f"\n\n查看完整报告：{notification.link}"
        text += "\n\n本内容仅供学习参考，不构成投资建议。"
        text = _truncate_text(text)

        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }

        for attempt in range(1, NOTIFIER_MAX_ATTEMPTS + 1):
            try:
                response = await self.client.post(
                    FEISHU_WEBHOOK,
                    json=payload,
                    timeout=20.0,
                )
                response.raise_for_status()
                data = response.json()
                if data.get("code") != 0:
                    raise httpx.HTTPStatusError(
                        f"Feishu error: {data.get('msg')}",
                        request=response.request,
                        response=response,
                    )
                return
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code if exc.response else 0
                # App-level errors (HTTP 200 with non-zero code) and 4xx
                # (except 429 rate limit) are not retryable.
                if code == 200 or (400 <= code < 500 and code != 429):
                    raise
                if attempt == NOTIFIER_MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(NOTIFIER_BACKOFF_BASE * (2 ** (attempt - 1)))
            except httpx.TransportError:
                if attempt == NOTIFIER_MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(NOTIFIER_BACKOFF_BASE * (2 ** (attempt - 1)))

    async def _send_dingtalk(self, notification: Notification) -> None:
        raise NotImplementedError("TODO: implement DingTalk webhook")

    async def _send_email(self, notification: Notification) -> None:
        raise NotImplementedError("TODO: implement SMTP email")

    async def _send_telegram(self, notification: Notification) -> None:
        raise NotImplementedError("TODO: implement Telegram bot")

    async def close(self) -> None:
        await self.client.aclose()
