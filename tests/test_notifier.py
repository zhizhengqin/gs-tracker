"""Tests for src.notifier formatting helpers."""
import httpx
import pytest
from unittest.mock import AsyncMock, patch

from src.notifier import (
    Notification,
    Notifier,
    _format_summary,
    _format_value,
    _truncate_text,
)


def test_format_value_billions():
    assert _format_value(12_345_000_000.0) == "$12.3B"


def test_format_value_millions():
    assert _format_value(123_456_789.0) == "$123.5M"


def test_format_value_thousands():
    assert _format_value(12_345.0) == "$12.3K"


def test_format_value_small():
    assert _format_value(123.0) == "$123"


def test_format_summary_with_data():
    summary = {
        "total_value": 123_400_000_000.0,
        "new_positions": 3,
        "sold_positions": 2,
        "increased_positions": 5,
        "decreased_positions": 1,
    }
    text = _format_summary(summary)
    assert "总持仓市值：$123.4B" in text
    assert "新增持仓：3 只" in text
    assert "清仓持仓：2 只" in text
    assert "大幅（变化≥20%）增持：5 只" in text
    assert "大幅（变化≥20%）减持：1 只" in text


def test_format_summary_without_data():
    assert _format_summary(None) == ""
    assert _format_summary({}) == ""


def test_truncate_text_under_limit():
    assert _truncate_text("hello", 100) == "hello"


def test_truncate_text_over_limit():
    long_text = "x" * 20000
    result = _truncate_text(long_text, 15000)
    assert result.endswith("...")
    assert len(result.encode("utf-8")) <= 15000


@pytest.mark.asyncio
async def test_send_feishu_success(httpx_mock):
    httpx_mock.add_response(url="https://fake.feishu.webhook", json={"code": 0})

    with patch("src.notifier.FEISHU_WEBHOOK", "https://fake.feishu.webhook"):
        notifier = Notifier()
        await notifier.send(Notification(title="hi", body="body", link="https://example.com/r.html"))
        await notifier.close()

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    payload = requests[0].content.decode("utf-8")
    assert "hi" in payload
    assert "body" in payload
    assert "https://example.com/r.html" in payload


@pytest.mark.asyncio
async def test_send_feishu_retries_on_500(httpx_mock):
    httpx_mock.add_response(url="https://fake.feishu.webhook", status_code=500)
    httpx_mock.add_response(url="https://fake.feishu.webhook", json={"code": 0})

    with patch("src.notifier.FEISHU_WEBHOOK", "https://fake.feishu.webhook"):
        with patch("src.notifier.NOTIFIER_BACKOFF_BASE", 0.0):
            notifier = Notifier()
            await notifier.send(Notification(title="hi", body="body"))
            await notifier.close()

    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_send_feishu_retries_on_429(httpx_mock):
    httpx_mock.add_response(url="https://fake.feishu.webhook", status_code=429)
    httpx_mock.add_response(url="https://fake.feishu.webhook", json={"code": 0})

    with patch("src.notifier.FEISHU_WEBHOOK", "https://fake.feishu.webhook"):
        with patch("src.notifier.NOTIFIER_BACKOFF_BASE", 0.0):
            notifier = Notifier()
            await notifier.send(Notification(title="hi", body="body"))
            await notifier.close()

    assert len(httpx_mock.get_requests()) == 2


@pytest.mark.asyncio
async def test_send_feishu_does_not_retry_403(httpx_mock):
    httpx_mock.add_response(url="https://fake.feishu.webhook", status_code=403)

    with patch("src.notifier.FEISHU_WEBHOOK", "https://fake.feishu.webhook"):
        with patch("src.notifier.NOTIFIER_BACKOFF_BASE", 0.0):
            notifier = Notifier()
            with pytest.raises(httpx.HTTPStatusError):
                await notifier.send(Notification(title="hi", body="body"))
            await notifier.close()

    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.asyncio
async def test_send_feishu_app_error_raises(httpx_mock):
    httpx_mock.add_response(url="https://fake.feishu.webhook", json={"code": 9499, "msg": "bad"})

    with patch("src.notifier.FEISHU_WEBHOOK", "https://fake.feishu.webhook"):
        notifier = Notifier()
        with pytest.raises(httpx.HTTPStatusError):
            await notifier.send(Notification(title="hi", body="body"))
        await notifier.close()


@pytest.mark.asyncio
async def test_send_skips_when_not_configured():
    with patch("src.notifier.FEISHU_WEBHOOK", ""):
        notifier = Notifier()
        # Should not raise or make any request
        await notifier.send(Notification(title="hi", body="body"))
        await notifier.close()
