# GS-Tracker 飞书通知推送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在新季度 13F 报告生成后，自动向飞书群机器人发送一条中文通知消息；失败不阻断主流程，同一季度只通知一次。

**Architecture：** 复用现有 `src/notifier.py` 的 `Notifier` 类，实现 `_send_feishu`；新增 `PUBLIC_BASE_URL` 与重试配置；在 SQLite 中新增 `sent_notifications` 表做去重；在 `src/main.py` 报告生成成功后构造消息并发送。

**Tech Stack：** Python 3.11+, httpx, pytest, pytest-asyncio, pytest-httpx, SQLite, pandas

## Global Constraints

- Python 3.11+，类型注解，PEP 8
- 异步用 httpx + asyncio
- 每个模块对应 `tests/` 下的测试文件
- 标准 logging，参数化 SQL 防注入
- API 密钥/URL 只从环境变量读取，禁止硬编码
- 所有用户可见输出必须为中文
- 错误信息对用户展示时使用中文
- TDD：先写失败测试，再写最小实现，最后重构
- 提交信息格式：`type(scope): description`

---

## File Structure

| 文件 | 职责 |
|---|---|
| `src/config.py` | 新增 `PUBLIC_BASE_URL`、`NOTIFIER_MAX_ATTEMPTS`、`NOTIFIER_BACKOFF_BASE` |
| `src/storage.py` | 新增 `sent_notifications` 表；新增 `mark_notification_sent`、`is_notification_sent` |
| `src/notifier.py` | 实现 `_send_feishu`、重试逻辑、消息格式化/截断 |
| `src/main.py` | 报告生成后构造 `Notification`、调用发送、成功后标记去重 |
| `tests/test_config.py` | 配置项读取测试 |
| `tests/test_storage.py` | 去重表测试 |
| `tests/test_notifier.py` | 飞书发送、重试、格式化、截断测试 |
| `tests/test_main.py` | pipeline 集成通知测试 |
| `.env.example` | 增加新环境变量示例 |

---

### Task 1: 新增通知相关配置项

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `config.PUBLIC_BASE_URL` (`str`), `config.NOTIFIER_MAX_ATTEMPTS` (`int`), `config.NOTIFIER_BACKOFF_BASE` (`float`)

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加：

```python
def test_public_base_url_default():
    assert config.PUBLIC_BASE_URL == ""


def test_notifier_max_attempts_default():
    assert config.NOTIFIER_MAX_ATTEMPTS == 3


def test_notifier_backoff_base_default():
    assert config.NOTIFIER_BACKOFF_BASE == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_config.py::test_public_base_url_default tests/test_config.py::test_notifier_max_attempts_default tests/test_config.py::test_notifier_backoff_base_default -v
```

Expected: 3 FAIL，提示 `AttributeError`

- [ ] **Step 3: 写最小实现**

在 `src/config.py` 中 `TELEGRAM_CHAT_ID` 之后、空行之前插入：

```python
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "")
NOTIFIER_MAX_ATTEMPTS = int(os.getenv("NOTIFIER_MAX_ATTEMPTS", "3"))
NOTIFIER_BACKOFF_BASE = float(os.getenv("NOTIFIER_BACKOFF_BASE", "1.0"))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_config.py -v
```

Expected: 5 passed

- [ ] **Step 5: 更新 `.env.example`**

在 `# Output` 段落后新增：

```text
# Public base URL for report links in notifications
PUBLIC_BASE_URL=https://your-domain.com

# Notification retry settings
NOTIFIER_MAX_ATTEMPTS=3
NOTIFIER_BACKOFF_BASE=1.0
```

- [ ] **Step 6: 提交**

```bash
git add src/config.py tests/test_config.py .env.example
git commit -m "feat(config): add notification env vars"
```

---

### Task 2: SQLite 去重表

**Files:**
- Modify: `src/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `storage.mark_notification_sent(quarter: str) -> bool`
- Produces: `storage.is_notification_sent(quarter: str) -> bool`

- [ ] **Step 1: 写失败测试**

在 `tests/test_storage.py` 末尾追加：

```python
def test_mark_notification_sent_first_time(fresh_db):
    assert mark_notification_sent("2026-Q1") is True


def test_mark_notification_sent_duplicate_returns_false(fresh_db):
    mark_notification_sent("2026-Q1")
    assert mark_notification_sent("2026-Q1") is False


def test_is_notification_sent(fresh_db):
    assert is_notification_sent("2026-Q1") is False
    mark_notification_sent("2026-Q1")
    assert is_notification_sent("2026-Q1") is True
```

并在文件顶部 `from src.storage import init_db, save_holdings, get_holdings` 改为：

```python
from src.storage import (
    get_holdings,
    init_db,
    is_notification_sent,
    mark_notification_sent,
    save_holdings,
)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_storage.py::test_mark_notification_sent_first_time -v
```

Expected: FAIL，提示 `mark_notification_sent` 未定义

- [ ] **Step 3: 写最小实现**

在 `src/storage.py` 中：

1. `init_db()` 的 `conn.executescript(...)` 的 SQL 字符串末尾追加：

```sql
            CREATE TABLE IF NOT EXISTS sent_notifications (
                quarter TEXT PRIMARY KEY,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
```

2. 在文件末尾新增函数：

```python

def mark_notification_sent(quarter: str) -> bool:
    """Mark a quarter as notified.

    Returns True if this call inserted the row (first time),
    False if the quarter was already present.
    """
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO sent_notifications (quarter) VALUES (?)",
                (quarter,),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def is_notification_sent(quarter: str) -> bool:
    """Return whether a notification has already been sent for this quarter."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM sent_notifications WHERE quarter = ?",
            (quarter,),
        )
        return cursor.fetchone() is not None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_storage.py -v
```

Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add src/storage.py tests/test_storage.py
git commit -m "feat(storage): add sent_notifications dedup table"
```

---

### Task 3: Notifier 消息格式化与截断

**Files:**
- Modify: `src/notifier.py`
- Test: `tests/test_notifier.py`（新建）

**Interfaces:**
- Produces: `notifier._format_value(value: float) -> str`
- Produces: `notifier._format_summary(summary: Optional[dict]) -> str`
- Produces: `notifier._truncate_text(text: str, max_bytes: int = 15000) -> str`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_notifier.py`：

```python
"""Tests for src.notifier formatting helpers."""
from src.notifier import _format_summary, _format_value, _truncate_text


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_notifier.py -v
```

Expected: 全部 FAIL，提示函数未定义

- [ ] **Step 3: 写最小实现**

在 `src/notifier.py` 中，文件顶部 `logger = logging.getLogger(__name__)` 之后新增：

```python

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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_notifier.py -v
```

Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "feat(notifier): add message formatting and truncation helpers"
```

---

### Task 4: 飞书 Webhook 发送与重试

**Files:**
- Modify: `src/notifier.py`
- Test: `tests/test_notifier.py`

**Interfaces:**
- Produces: `Notifier._send_feishu(notification: Notification) -> None`
- Consumes: `config.FEISHU_WEBHOOK`, `config.NOTIFIER_MAX_ATTEMPTS`, `config.NOTIFIER_BACKOFF_BASE`

- [ ] **Step 1: 写失败测试**

在 `tests/test_notifier.py` 末尾追加：

```python
import httpx
import pytest
from unittest.mock import AsyncMock, patch

from src.notifier import Notification, Notifier


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_notifier.py::test_send_feishu_success -v
```

Expected: FAIL，提示 `_send_feishu` 为 `NotImplementedError`

- [ ] **Step 3: 写最小实现**

在 `src/notifier.py` 中，把 `_send_feishu` 占位替换为：

```python
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
                if 400 <= code < 500 and code != 429:
                    raise
                if attempt == NOTIFIER_MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(NOTIFIER_BACKOFF_BASE * (2 ** (attempt - 1)))
            except httpx.TransportError:
                if attempt == NOTIFIER_MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(NOTIFIER_BACKOFF_BASE * (2 ** (attempt - 1)))
```

并在文件顶部导入 `asyncio`：

```python
import asyncio
import json
import logging
```

以及从 config 导入新增变量：

```python
from src.config import (
    DINGTALK_WEBHOOK,
    FEISHU_WEBHOOK,
    NOTIFIER_BACKOFF_BASE,
    NOTIFIER_MAX_ATTEMPTS,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_USER,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_notifier.py -v
```

Expected: 14 passed

- [ ] **Step 5: 提交**

```bash
git add src/notifier.py tests/test_notifier.py
git commit -m "feat(notifier): implement Feishu webhook send with retry"
```

---

### Task 5: main.py 集成通知发送

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `notifier.Notification`, `notifier.Notifier`, `notifier._format_summary`
- Consumes: `storage.get_holdings`, `storage.mark_notification_sent`
- Consumes: `quarter_compare.QuarterComparator`
- Consumes: `config.FEISHU_WEBHOOK`, `config.PUBLIC_BASE_URL`

- [ ] **Step 1: 写失败测试**

在 `tests/test_main.py` 末尾追加：

```python
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_pipeline_sends_notification_after_report(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    mock_df = pd.DataFrame(
        {
            "cusip": ["A"],
            "name_of_issuer": ["Apple"],
            "title_of_class": ["COM"],
            "value": [1000000.0],
            "shares": [1000],
            "investment_discretion": ["SOLE"],
        }
    )

    async def fake_fetch(filing_info):
        filing_info["report_date"] = "2026-06-30"
        return mock_df

    with patch("src.main.SEC13FFetcher") as MockFetcher:
        MockFetcher.report_date_to_quarter = SEC13FFetcher.report_date_to_quarter
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = fake_fetch
        with patch("src.main.save_holdings"):
            with patch("src.main.GSAnalyzer") as MockAnalyzer:
                analyzer = MockAnalyzer.return_value
                analyzer.analyze_holdings = AsyncMock(return_value=MagicMock())
                with patch("src.main.ReportGenerator") as MockReporter:
                    reporter = MockReporter.return_value
                    reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q2.html"
                    with patch("src.main.Notifier") as MockNotifier:
                        notifier = MockNotifier.return_value
                        notifier.send = AsyncMock()
                        with patch("src.main.mark_notification_sent", return_value=True) as mock_mark:
                            with patch("src.main.FEISHU_WEBHOOK", "https://fake.webhook"):
                                with patch("src.main.PUBLIC_BASE_URL", "https://example.com"):
                                    with patch("src.main.get_holdings", return_value=[]):
                                        await run_pipeline()
                                        notifier.send.assert_awaited_once()
                                        mock_mark.assert_called_once_with("2026-Q2")


@pytest.mark.asyncio
async def test_run_pipeline_marks_notification_after_success(tmp_path, monkeypatch):
    monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)

    mock_df = pd.DataFrame(
        {
            "cusip": ["A"],
            "name_of_issuer": ["Apple"],
            "title_of_class": ["COM"],
            "value": [1000000.0],
            "shares": [1000],
            "investment_discretion": ["SOLE"],
        }
    )

    async def fake_fetch(filing_info):
        filing_info["report_date"] = "2026-06-30"
        return mock_df

    with patch("src.main.SEC13FFetcher") as MockFetcher:
        MockFetcher.report_date_to_quarter = SEC13FFetcher.report_date_to_quarter
        instance = MockFetcher.return_value.__aenter__.return_value
        instance.fetch_latest_holdings = fake_fetch
        with patch("src.main.save_holdings"):
            with patch("src.main.GSAnalyzer") as MockAnalyzer:
                analyzer = MockAnalyzer.return_value
                analyzer.analyze_holdings = AsyncMock(return_value=MagicMock())
                with patch("src.main.ReportGenerator") as MockReporter:
                    reporter = MockReporter.return_value
                    reporter.generate_report = lambda *args, **kwargs: tmp_path / "2026-Q2.html"
                    with patch("src.main.Notifier") as MockNotifier:
                        notifier = MockNotifier.return_value
                        notifier.send = AsyncMock(side_effect=RuntimeError("boom"))
                        with patch("src.main.mark_notification_sent") as mock_mark:
                            with patch("src.main.FEISHU_WEBHOOK", "https://fake.webhook"):
                                with patch("src.main.PUBLIC_BASE_URL", "https://example.com"):
                                    with patch("src.main.get_holdings", return_value=[]):
                                        await run_pipeline()
                                        notifier.send.assert_awaited_once()
                                        mock_mark.assert_not_called()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_main.py::test_run_pipeline_sends_notification_after_report -v
```

Expected: FAIL，提示 `Notification` / `Notifier` 未导入或 `mark_notification_sent` 未调用

- [ ] **Step 3: 写最小实现**

在 `src/main.py` 中：

1. 文件顶部新增导入：

```python
import pandas as pd

from src.notifier import Notification, Notifier, _format_summary
from src.quarter_compare import QuarterComparator
from src.storage import get_holdings, init_db, mark_notification_sent, save_holdings
```

把原来的 `from src.storage import init_db, save_holdings` 删除。

2. 在 `run_pipeline()` 中，生成报告之后、函数返回之前插入：

```python
    summary = None
    previous_quarter = _previous_quarter(quarter)
    if previous_quarter:
        previous_records = get_holdings(cik, previous_quarter)
        if previous_records:
            prev_df = pd.DataFrame(previous_records)
            comparison = QuarterComparator().compare(
                mock_df, prev_df, quarter, previous_quarter
            )
            summary = {
                "total_value": float(df["value"].sum()),
                "new_positions": len(comparison.new_positions),
                "sold_positions": len(comparison.sold_positions),
                "increased_positions": len(comparison.increased_positions),
                "decreased_positions": len(comparison.decreased_positions),
            }

    if FEISHU_WEBHOOK:
        base = (PUBLIC_BASE_URL or "").rstrip("/")
        report_url = f"{base}/reports/{quarter}.html" if base else None
        if not base:
            logger.warning("PUBLIC_BASE_URL not set; notification will not include report link")

        notification = Notification(
            title=f"高盛动向情报 — {quarter} 报告已生成",
            body=_format_summary(summary),
            link=report_url,
        )
        notifier = Notifier()
        try:
            await notifier.send(notification)
            mark_notification_sent(quarter)
        except Exception:
            logger.exception("Failed to send notification for %s", quarter)
        finally:
            await notifier.close()
```

注意：上面代码中 `mock_df` 是测试里的变量名，实际应使用 `df`。请使用 `df`：

```python
            comparison = QuarterComparator().compare(
                df, prev_df, quarter, previous_quarter
            )
```

3. 在 `src/main.py` 末尾新增辅助函数：

```python

def _previous_quarter(quarter: str) -> Optional[str]:
    """Return the quarter before the given one, or None for the first quarter."""
    year, q = quarter.split("-")
    year = int(year)
    q_num = int(q.replace("Q", ""))
    if q_num == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{q_num - 1}"
```

并在文件顶部导入 `Optional`：

```python
from typing import Optional
```

4. 同时从 `src.config` 导入新增变量。将 `from src.config import REPORT_OUTPUT_DIR, ensure_directories` 改为：

```python
from src.config import (
    FEISHU_WEBHOOK,
    PUBLIC_BASE_URL,
    REPORT_OUTPUT_DIR,
    ensure_directories,
)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_main.py -v
```

Expected: 全部通过

- [ ] **Step 5: 运行全量回归测试**

```bash
pytest -v
```

Expected: 全部通过

- [ ] **Step 6: 代码风格检查**

```bash
flake8 src/main.py tests/test_main.py src/notifier.py tests/test_notifier.py src/storage.py tests/test_storage.py src/config.py tests/test_config.py
mypy src/main.py src/notifier.py src/storage.py src/config.py
```

Expected: 无错误

- [ ] **Step 7: 提交**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(main): send Feishu notification after report generation"
```

---

## 自我检查

**1. Spec coverage:**
- 飞书 Webhook 发送 ✅ Task 4
- 中文消息 ✅ Task 3/4
- 报告链接 ✅ Task 5
- 免责声明 ✅ Task 4
- 同一季度去重 ✅ Task 2/5
- 失败不阻断主流程 ✅ Task 4/5
- 重试策略 ✅ Task 4
- 环境变量配置 ✅ Task 1

**2. Placeholder scan:**
- 无 "TBD" / "TODO" / "implement later" / "Add appropriate error handling" / "Similar to Task N"
- 每个步骤包含完整代码和命令

**3. Type consistency：**
- `mark_notification_sent(quarter: str) -> bool` 全计划一致
- `Notification(title, body, link)` 与现有 dataclass 一致
- `_format_summary(summary: Optional[dict]) -> str` 全计划一致
- `QuarterComparator().compare(df, prev_df, quarter, previous_quarter)` 与 `src/quarter_compare.py` 一致

---

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-07-18-feishu-notification.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using `executing-plans`, batch execution with checkpoints

Which approach?
