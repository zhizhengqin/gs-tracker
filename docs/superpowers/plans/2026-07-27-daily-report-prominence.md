# 每日情报页改版（当日优先 + 日报前置自动生成）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日情报页默认展示"今日视图"（AI 日报卡置顶 + 当日信号 + 折叠历史区），日报在流水线跑完后自动生成、页面打开时无缓存兜底。

**Architecture:** 日报生成逻辑从 web 端点抽入 `src/daily_report.py`（含并发去重），web 端点变薄壳；流水线 SSE 流尾部 fire-and-forget 生成、调度器版同步等待；前端 `templates/dashboard.html` 重排为今日视图（现有范围视图移入折叠区，历史日期整页视图保留）。

**Tech Stack:** Python 3.11 / FastAPI / sqlite3（后端）；原生 JS + 已有媒体查询（前端）；pytest（TDD）；Node 全局 playwright（前端验证，零新依赖）。

**设计文档:** `docs/superpowers/specs/2026-07-27-daily-report-prominence-design.md`

## Global Constraints

- 日报的 prompt 原文、三段式结构、合规检查、`max_tokens=2048`、60s 超时、缓存表读写——全部保持现状逐字不变
- 失败不写缓存（无信号 / 无 LLM 配置 / LLM 异常），可重试；合规违规仅记日志（现状）
- 日报生成失败绝不影响流水线结果与 SSE 事件序列
- 所有用户可见文字用中文；代码内部（变量/函数/注释/commit）用英文
- API 密钥只从环境变量或 DB 读取，禁止硬编码、禁止打印
- 提交信息格式：`feat(daily-report): ...`
- 每任务结束 `pytest -q` 全绿（现有 273 + 新增）；1 个既有 StarletteDeprecationWarning 与本特性无关
- 前端验证脚本通过 `npm root -g` 引用全局 playwright，无新增依赖

**事实记录（计划编写时核实，实施代理可直接信任）：**
- `src/llm_config.py` 的 `resolve_llm_config(db_model)` 返回 `{api_key, auth_token, base_url, model}`；web.py:104 的 `_llm_client_kwargs` 只是它的透传包装
- `src/storage.py`：`get_daily_report(date)` → dict|None（键 `report_text`/`signal_count`）；`save_daily_report(date, text, count)` 幂等 upsert；`get_signals_by_date(date)` → `List[Signal]`（按 published_at DESC）；`get_default_llm_model` 也在 storage（web.py:25 导入）
- 日报端点 web.py:876-957，其结束处紧邻 `# ====== Quarter comparison ======` 注释
- `src/main.py`：`run_daily_intel_stream` 的 complete yield 在 274-280 行；`run_daily_intel` 在 283-300 行（消费 stream 的循环后 return summary）
- **测试无现成日报覆盖**（tests/ 里没有任何 daily-report 测试）——本计划新增的是首批
- 前端现状（行号随手机适配已偏移，以锚点字符串为准）：`renderDailyIntel` 有两处写 `mainContent`（empty 分支 + 主分支）；`loadDailyIntel` 一处；包装器（`_origRenderDailyIntel`）注入日期行/AI 开关/底部报告容器；`loadDateSignals` 是历史日期整页视图（自带底部 `#dailyReportContainer` + 生成日报按钮）；SSE complete 处理器用 `setTimeout(() => loadDailyIntel(dailyDays || 30), 1500)` 刷新；`switchMainView('daily')` 调 `loadDailyIntel(dailyDays)`

---

### Task 1: `src/daily_report.py` 抽模块 + 端点薄壳 + 单测

**Files:**
- Create: `src/daily_report.py`
- Modify: `src/web.py:876-957`（端点变薄壳）
- Test: `tests/test_daily_report.py`（新增）、`tests/test_web.py`（追加 2 个端点测试）

**Interfaces:**
- Produces（后续任务依赖的精确签名）：
  - `async generate_daily_report(date: str) -> dict` — 返回 `{"date", "report", "signal_count", "cached", "error"?}`
  - `async ensure_daily_report(date: str) -> Optional[asyncio.Task]` — 有缓存返回 None；否则返回进行中/新建的生成 Task（同日并发去重）
- Consumes: `resolve_llm_config`、`get_daily_report`、`save_daily_report`、`get_signals_by_date`、`get_default_llm_model`

- [ ] **Step 1: 写失败测试 `tests/test_daily_report.py`**

```python
"""Tests for src.daily_report."""
import asyncio

import pytest

from src.signals.base import Signal, SignalStrength


def _signal(title="高盛看多A股"):
    from datetime import datetime, timezone
    return Signal(
        title=title, source="news", published_at=datetime.now(timezone.utc),
        summary="摘要", companies=[], strength=SignalStrength.MEDIUM, url=None,
    )


class _FakeClient:
    """Scripted LLM client: returns one text block; records call count."""

    def __init__(self, text):
        self.text = text
        self.calls = 0
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            self._outer.calls += 1

            class _Block:
                pass

            class _Resp:
                pass

            block = _Block()
            block.text = self._outer.text
            resp = _Resp()
            resp.content = [block]
            return resp


def _patch_storage(monkeypatch, cached=None, signals=None):
    saved = {}
    monkeypatch.setattr("src.daily_report.get_daily_report", lambda d: cached)
    monkeypatch.setattr("src.daily_report.get_signals_by_date", lambda d: signals or [])
    monkeypatch.setattr(
        "src.daily_report.save_daily_report",
        lambda d, text, count=0: saved.update(date=d, text=text, count=count),
    )
    monkeypatch.setattr("src.daily_report.get_default_llm_model", lambda: None)
    return saved


def _patch_llm(monkeypatch, text="## 今日高盛观点\n看多。\n\n## 今日披露变动\n无。\n\n## 一句话投资启示\n关注。"):
    client = _FakeClient(text)
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: client)
    monkeypatch.setattr(
        "src.daily_report.resolve_llm_config",
        lambda db_model: {"api_key": None, "auth_token": "tok", "base_url": "https://x.test", "model": "m"},
    )
    return client


@pytest.mark.asyncio
async def test_cache_hit_returns_without_llm(monkeypatch):
    from src.daily_report import generate_daily_report
    _patch_storage(monkeypatch, cached={"report_text": "旧日报", "signal_count": 3})
    client = _patch_llm(monkeypatch)
    result = await generate_daily_report("2026-07-27")
    assert result["cached"] is True
    assert result["report"] == "旧日报"
    assert result["signal_count"] == 3
    assert client.calls == 0


@pytest.mark.asyncio
async def test_no_signals_returns_notice_without_llm(monkeypatch):
    from src.daily_report import generate_daily_report
    _patch_storage(monkeypatch, signals=[])
    client = _patch_llm(monkeypatch)
    result = await generate_daily_report("2026-07-27")
    assert result["signal_count"] == 0
    assert "暂无情报" in result["report"]
    assert client.calls == 0


@pytest.mark.asyncio
async def test_no_llm_config_returns_error_not_cached(monkeypatch):
    from src.daily_report import generate_daily_report
    saved = _patch_storage(monkeypatch, signals=[_signal()])
    monkeypatch.setattr(
        "src.daily_report.resolve_llm_config",
        lambda db_model: {"api_key": None, "auth_token": None, "base_url": None, "model": "m"},
    )
    result = await generate_daily_report("2026-07-27")
    assert result["error"] == "no_llm_configured"
    assert "大模型" in result["report"]
    assert saved == {}


@pytest.mark.asyncio
async def test_llm_success_saves_and_returns(monkeypatch):
    from src.daily_report import generate_daily_report
    saved = _patch_storage(monkeypatch, signals=[_signal()])
    client = _patch_llm(monkeypatch)
    result = await generate_daily_report("2026-07-27")
    assert client.calls == 1
    assert "今日高盛观点" in result["report"]
    assert result["cached"] is False
    assert saved["date"] == "2026-07-27"
    assert "今日高盛观点" in saved["text"]
    assert saved["count"] == 1


@pytest.mark.asyncio
async def test_llm_failure_returns_fallback_not_cached(monkeypatch):
    from src.daily_report import generate_daily_report
    saved = _patch_storage(monkeypatch, signals=[_signal()])
    _patch_llm(monkeypatch)

    class _Fail:
        def __init__(self, **kw):
            self.messages = self._M()

        class _M:
            async def create(self, **kw):
                raise RuntimeError("gateway down")

    monkeypatch.setattr("anthropic.AsyncAnthropic", _Fail)
    result = await generate_daily_report("2026-07-27")
    assert "error" in result
    assert "失败" in result["report"]
    assert saved == {}


@pytest.mark.asyncio
async def test_ensure_returns_none_when_cached(monkeypatch):
    import src.daily_report as dr
    _patch_storage(monkeypatch, cached={"report_text": "x", "signal_count": 1})
    assert await dr.ensure_daily_report("2026-07-27") is None


@pytest.mark.asyncio
async def test_ensure_dedupes_concurrent_calls(monkeypatch):
    import src.daily_report as dr
    dr._report_tasks.clear()
    _patch_storage(monkeypatch, signals=[_signal()])
    client = _patch_llm(monkeypatch)
    t1 = await dr.ensure_daily_report("2026-07-27")
    t2 = await dr.ensure_daily_report("2026-07-27")
    assert t1 is not None and t1 is t2
    await t1
    assert client.calls == 1


@pytest.mark.asyncio
async def test_ensure_swallows_generation_errors(monkeypatch):
    import src.daily_report as dr
    dr._report_tasks.clear()
    _patch_storage(monkeypatch, signals=[_signal()])
    _patch_llm(monkeypatch)
    monkeypatch.setattr(
        "src.daily_report.generate_daily_report",
        _raise := lambda d: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    task = await dr.ensure_daily_report("2026-07-27")
    await task  # must not raise
```

- [ ] **Step 2: 追加端点测试到 `tests/test_web.py`（文件末尾）**

```python
def test_daily_report_endpoint_delegates(client, monkeypatch):
    import src.web as web

    async def _fake(date):
        return {"date": date, "report": "伪日报", "signal_count": 1, "cached": True}

    monkeypatch.setattr(web, "generate_daily_report", _fake)

    async def _none(date):
        return None

    monkeypatch.setattr(web, "ensure_daily_report", _none)
    resp = client.get("/api/daily-report/2026-07-27")
    assert resp.status_code == 200
    assert resp.json()["report"] == "伪日报"


def test_daily_report_endpoint_bad_date(client):
    resp = client.get("/api/daily-report/2026-13-99")
    assert resp.status_code == 422
```

注意：`tests/test_web.py` 现有的 client fixture 直接用；若该文件已有同名测试或 fixture 名不同（如 `TestClient` 实例名），按现有测试的 fixture 名调整。端点实现见 Step 4：它先 `await ensure_daily_report(date)`、有 task 则 await、最后 `return await generate_daily_report(date)`——所以两个函数都要替换成假的。

- [ ] **Step 3: 跑测试确认失败**

Run: `pytest tests/test_daily_report.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.daily_report'`）
Run: `pytest tests/test_web.py -q -k daily_report`
Expected: FAIL（`AttributeError: ... has no attribute 'generate_daily_report'` 或委托测试失败）

- [ ] **Step 4: 实现 `src/daily_report.py`**

```python
"""Daily intelligence summary report — single source of truth for generation.

Extracted from the /api/daily-report/{date} endpoint so the web layer and the
daily-intel pipeline share one implementation. Behavior contract (unchanged
from the legacy endpoint):
- cache hit           -> return cached row, no LLM call
- no signals that day -> notice text, no LLM call, nothing cached
- no LLM configured   -> notice + error="no_llm_configured", nothing cached
- LLM success         -> compliance check (violations only logged) -> cache -> return
- LLM failure         -> fallback text + error, nothing cached (retryable)

ensure_daily_report() adds process-wide dedupe so the pipeline tail, the
endpoint fallback, and the scheduler can never double-generate one date.
"""
import asyncio
import logging
from typing import Optional

from src.llm_config import resolve_llm_config
from src.storage import (
    get_daily_report,
    get_default_llm_model,
    get_signals_by_date,
    save_daily_report,
)

logger = logging.getLogger(__name__)

# date -> in-flight generation Task (process-wide dedupe)
_report_tasks: dict = {}


async def generate_daily_report(date: str) -> dict:
    """Return (or generate) the daily summary report for `date` (YYYY-MM-DD)."""
    cached = await asyncio.to_thread(get_daily_report, date)
    if cached:
        return {"date": date, "report": cached["report_text"], "signal_count": cached["signal_count"], "cached": True}

    signals = await asyncio.to_thread(get_signals_by_date, date)
    if not signals:
        return {"date": date, "report": "该日期暂无情报数据。", "signal_count": 0, "cached": False}

    # Build LLM prompt from signals (HTML-stripped — legacy rows may carry tags)
    from src.signals.news_source import clean_html_text

    signal_texts = []
    for s in signals[:20]:
        signal_texts.append(f"- [{s.source}] {clean_html_text(s.title)}: {clean_html_text(s.summary)[:150]}")
    combined = "\n".join(signal_texts)

    try:
        import anthropic
        from src.compliance import check_content

        db_model = await asyncio.to_thread(get_default_llm_model)
        llm = resolve_llm_config(db_model)
        if not llm["api_key"] and not llm["auth_token"]:
            return {
                "date": date,
                "report": "尚未配置大模型，请先在「设置」页添加大模型（如 DeepSeek/Kimi）后再生成日报。",
                "signal_count": len(signals),
                "cached": False,
                "error": "no_llm_configured",
            }

        client = anthropic.AsyncAnthropic(
            api_key=llm["api_key"],
            auth_token=llm["auth_token"],
            base_url=llm["base_url"],
            timeout=60.0,
        )
        prompt = (
            "你是一位资深的高盛情报分析师。请基于以下今日高盛相关情报信号，"
            "生成一份面向中国普通投资者的每日情报摘要。\n\n"
            f"今日日期：{date}\n"
            f"信号总数：{len(signals)}\n\n"
            "=== 今日情报信号 ===\n"
            f"{combined}\n\n"
            "请按以下三段式输出：\n\n"
            "## 今日高盛观点\n"
            "（概括高盛研究/分析师当日主要观点，2-4句话）\n\n"
            "## 今日披露变动\n"
            "（概括当日 SEC 文件/持仓变动等重要披露，2-3句话）\n\n"
            "## 一句话投资启示\n"
            "（用通俗语言写一句话，帮助普通投资者理解今日信息的意义）\n\n"
            "合规要求：所有评级/目标价必须署名来源（如'高盛'），禁止以本系统名义给出买卖建议。全部使用中文输出，控制在500字以内。"
        )
        resp = await client.messages.create(
            model=llm["model"],
            max_tokens=2048,  # leave room for thinking-block models
            messages=[{"role": "user", "content": prompt}],
        )
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text += block.text

        report = text.strip() or "AI 未生成有效日报"
        passed, violations = check_content(report)
        if not passed:
            logger.warning("Daily report compliance violations: %s", violations)

        await asyncio.to_thread(save_daily_report, date, report, len(signals))
        return {"date": date, "report": report, "signal_count": len(signals), "cached": False}
    except Exception as exc:
        logger.exception("Daily report generation failed for %s", date)
        fallback = f"## 今日情报概览\n\n今日共收录 {len(signals)} 条高盛相关情报信号。\n\nAI 日报生成失败：{exc}"
        return {"date": date, "report": fallback, "signal_count": len(signals), "cached": False, "error": str(exc)}


async def _generate_safe(date: str) -> None:
    """Task wrapper: generation failures must never crash callers."""
    try:
        await generate_daily_report(date)
    except Exception:
        logger.exception("Daily report generation task failed for %s", date)


async def ensure_daily_report(date: str) -> Optional[asyncio.Task]:
    """Idempotent fire-and-forget generation.

    Returns None when a cached report already exists; otherwise returns the
    in-flight (or newly created) generation Task. Callers that only want
    fire-and-forget ignore the return; callers that must wait (scheduler/CLI)
    await it.
    """
    if await asyncio.to_thread(get_daily_report, date):
        return None
    task = _report_tasks.get(date)
    if task is None or task.done():
        task = asyncio.create_task(_generate_safe(date))
        _report_tasks[date] = task
    return task
```

- [ ] **Step 5: web.py 端点变薄壳 + 顶部导入**

在 `src/web.py` 顶部导入区（约第 15 行 `from src.llm_config import resolve_llm_config` 附近）加：
```python
from src.daily_report import ensure_daily_report, generate_daily_report
```

替换整个 `api_get_daily_report` 函数体。先用 Read 确认边界（web.py:876 起，到 `# ====== Quarter comparison ======` 注释前止），然后 Edit：old_string 为现有完整函数（`@app.get("/api/daily-report/{date}")` 装饰器保留，只换函数），new_string：
```python
async def api_get_daily_report(date: str) -> dict:
    """Return (or generate) a daily summary report for the given date."""
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM-DD")
    # Route through the dedupe map so a pipeline-tail generation in flight
    # is awaited instead of duplicated.
    task = await ensure_daily_report(date)
    if task is not None:
        await task
    return await generate_daily_report(date)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/test_daily_report.py tests/test_web.py -q`
Expected: 全部 PASS（含 8 个新模块测试 + 2 个端点测试 + 原有全部 web 测试）

- [ ] **Step 7: 全量回归 + Commit**

```bash
pytest -q
git add src/daily_report.py src/web.py tests/test_daily_report.py tests/test_web.py
git commit -m "feat(daily-report): extract generation module with dedupe, slim endpoint"
```
Expected: 全绿（273 + 10 新增 = 283 左右，以实际为准）

---

### Task 2: 流水线尾部自动生成 + 集成测试

**Files:**
- Modify: `src/main.py`（`run_daily_intel_stream` complete yield 前 + `run_daily_intel` return 前）
- Test: `tests/test_main.py`（追加 2 个测试）

**Interfaces:**
- Consumes: Task 1 的 `ensure_daily_report(date) -> Optional[asyncio.Task]`
- Produces: 无新约定

**注意（与 spec 措辞的刻意偏差，实现者照本计划执行）**：spec 写"complete 事件 yield 之后 create_task"；本计划改为 complete yield **之前** `await ensure_daily_report(...)`。原因：客户端收到 complete 后立即断开时，async generator 在 yield 点被关闭，yield 之后的代码不会执行，日报调度会丢；而 `ensure_daily_report` 只是一次缓存查询 + 建 task（微秒级），不拖住完成状态。行为与 spec 意图一致（流水线完成即后台生成、失败吞掉只记日志）。

- [ ] **Step 1: 写失败测试（追加到 `tests/test_main.py` 末尾）**

仿照文件里现有 stream 测试的搭建方式（如 `test_stream_emits_triage_note_from_fetch_note` 附近的 fixtures/mocks——用相同的 `_build_daily_sources` patch 或空源列表，让流水线以零源/假源快速跑完）：

```python
@pytest.mark.asyncio
async def test_stream_schedules_daily_report(monkeypatch):
    """complete 事件前，流水线应调度当日日报生成（fire-and-forget）。"""
    import json as _json
    from datetime import datetime, timezone
    import src.main as main_mod

    calls = []

    async def _fake_ensure(date):
        calls.append(date)
        return None

    monkeypatch.setattr(main_mod, "ensure_daily_report", _fake_ensure)
    monkeypatch.setattr(main_mod, "_build_daily_sources", lambda: [])
    monkeypatch.setattr(main_mod, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main_mod, "save_signals_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "cleanup_expired_signals", lambda *a, **kw: None)

    events = []
    async for event_json in main_mod.run_daily_intel_stream():
        events.append(_json.loads(event_json))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert calls == [today]
    assert events[-1]["event"] == "complete"


@pytest.mark.asyncio
async def test_run_daily_intel_awaits_report_task(monkeypatch):
    """调度器/CLI 路径必须等日报生成完（一次性进程退出前落地）。"""
    import asyncio
    from datetime import datetime, timezone
    import src.main as main_mod

    generated = []

    async def _gen():
        await asyncio.sleep(0)
        generated.append("done")

    async def _fake_ensure(date):
        return asyncio.create_task(_gen())

    monkeypatch.setattr(main_mod, "ensure_daily_report", _fake_ensure)
    monkeypatch.setattr(main_mod, "_build_daily_sources", lambda: [])
    monkeypatch.setattr(main_mod, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main_mod, "save_signals_incremental", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main_mod, "cleanup_expired_signals", lambda *a, **kw: None)

    summary = await main_mod.run_daily_intel()
    assert generated == ["done"]
    assert summary["new_signals"] == 0
```

注意：上述 mock 清单是按 main.py 当前实现（240-280 行）写的；若现有 stream 测试已有可复用的 setup helper/fixture，优先复用它，只加 `ensure_daily_report` 的 patch 与断言。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_main.py -q -k daily_report or pytest tests/test_main.py -q -k "report_task or schedules_daily_report"`
Expected: FAIL（`AttributeError: module 'src.main' has no attribute 'ensure_daily_report'`）

- [ ] **Step 3: 实现——main.py 两处插入**

顶部导入区加：
```python
from src.daily_report import ensure_daily_report
```

插入 1——`run_daily_intel_stream` 的 complete yield（274 行 `yield json.dumps({`）**之前**：
```python
    # Kick off daily report generation (add-on: never blocks/fails the pipeline;
    # web SSE keeps the loop alive so the task completes).
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        await ensure_daily_report(today)
    except Exception:
        logger.exception("Failed to schedule daily report generation")

```

插入 2——`run_daily_intel` 的 `return summary`（300 行）**之前**：
```python
    # Scheduler/CLI path: wait for the report so one-shot processes don't exit
    # before it lands (dedupe: the stream already scheduled it above).
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        task = await ensure_daily_report(today)
        if task is not None:
            await task
    except Exception:
        logger.exception("Daily report generation wait failed")

```

- [ ] **Step 4: 跑测试确认通过 + 全量回归 + Commit**

```bash
pytest tests/test_main.py -q
pytest -q
git add src/main.py tests/test_main.py
git commit -m "feat(daily-report): auto-generate daily report at pipeline tail"
```

---

### Task 3: 前端今日视图重排 + 验证脚本

**Files:**
- Modify: `templates/dashboard.html`（CSS 主样式区 + 多处 JS）
- Create: `scripts/verify_today_view.js`

**Interfaces:**
- Consumes: Task 1/2 的后端行为（端点无缓存时自动生成）；`scripts/ui_snapshot.js` 的用法模式
- Produces: `#dailyReportContainer`（置顶）、`#todayFeed`、`#earlierToggle`/`#earlierBody`、`loadTodayView()`/`renderTodayFeed()`/`toggleEarlier()`/`addAiToggles(rootEl)`/`filterSignalsBy(data)` 全局函数、`todayData` 全局变量

**改动总览（8 处，全部给出完整新旧代码）：**
1. 新增全局 `let todayData = [];`（放在 `let dailyData = [];` 旁）
2. `switchMainView('daily')` 分支：`await loadDailyIntel(dailyDays);` → `await loadTodayView();`
3. 新增 `loadTodayView`/`renderTodayView`/`renderTodayFeed`/`filterSignalsBy`/`toggleEarlier` 函数
4. `loadDailyIntel` + `renderDailyIntel` 三处 `mainContent` 写入改为目标感知（`earlierBody || mainContent`）
5. 包装器简化：去掉日期行注入和底部报告容器注入，AI 开关逻辑抽成 `addAiToggles(rootEl)`
6. `onFilterChange` 今日视图适配
7. `loadDateSignals` 头部加"← 返回今日"按钮
8. SSE complete 刷新逻辑：`setTimeout(() => loadDailyIntel(dailyDays || 30), 1500)` → 条件刷新
9. CSS 主样式区（非媒体查询）新增 `.earlier-section`/`.earlier-toggle`/`.today-title` 样式

- [ ] **Step 1: CSS——主样式区新增（放在 `.daily-report-card` 规则附近）**

```css
        .today-title { font-size: 1.0em; color: var(--primary); margin: 18px 0 10px; }
        .earlier-section { margin-top: 20px; }
        .earlier-toggle {
            width: 100%; padding: 12px; border: 1px dashed #c9ced6; border-radius: 10px;
            background: #fafbfc; color: #667; font-size: 0.9em; cursor: pointer; transition: all .15s;
        }
        .earlier-toggle:hover { border-color: var(--accent); color: var(--accent); }
```

- [ ] **Step 2: JS——全局变量 + switchMainView 分支**

old_string：
```js
let dailyData = [];       // signals from /api/signals/recent
```
new_string：
```js
let dailyData = [];       // signals from /api/signals/recent (earlier range view)
let todayData = [];       // today's signals (today view)
```

old_string（switchMainView 的 daily 分支）：
```js
        await loadDailyIntel(dailyDays);
```
new_string：
```js
        await loadTodayView();
```

- [ ] **Step 3: JS——新增今日视图函数（放在 `loadDailyIntel` 定义之前）**

```js
// ====== Today view (default daily view) ======
async function loadTodayView() {
    dailyDays = null;  // today mode
    document.getElementById('mainContent').innerHTML = '<div class="loading">加载中...</div>';
    const today = new Date().toISOString().slice(0, 10);
    try {
        const resp = await fetch(`/api/signals/date/${today}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        todayData = json.signals || [];
    } catch (e) {
        console.error('Failed to load today signals', e);
        todayData = [];
    }
    renderTodayView(today);
    loadDailyReport(today);  // auto: cached -> instant; missing -> generated on demand
}

function renderTodayView(today) {
    document.getElementById('mainContent').innerHTML = `
        <div class="daily-header">
            <h2>📡 每日情报</h2>
            <div class="date-picker-row">
                <span style="font-size:0.85em;color:#888;">📅 查看日期：</span>
                <input type="date" id="dailyDatePicker" value="${today}" onchange="loadDateSignals(this.value)">
                <button class="btn-sm primary" onclick="loadDateSignals(document.getElementById('dailyDatePicker').value)">查看</button>
            </div>
        </div>
        <div id="dailyReportContainer"></div>
        <div id="todayFeed"></div>
        <div class="earlier-section">
            <button class="earlier-toggle" id="earlierToggle" onclick="toggleEarlier()">▾ 查看更早的情报</button>
            <div id="earlierBody" style="display:none;"></div>
        </div>`;
    renderTodayFeed();
}

function renderTodayFeed() {
    const el = document.getElementById('todayFeed');
    if (!el) return;
    const filtered = filterSignalsBy(todayData);
    if (filtered.length === 0) {
        el.innerHTML = `<div class="empty-state">
            <div class="icon">📭</div>
            <p>今日暂无情报</p>
            <p style="font-size:0.85em;margin-top:8px;">点左侧「📡 手动运行每日情报」开始抓取</p>
        </div>`;
        return;
    }
    el.innerHTML = `<h3 class="today-title">今日情报（${filtered.length} 条）</h3>
        <div class="daily-feed">${filtered.map(s => renderSignalCard(s)).join('')}</div>`;
    addAiToggles(el);
}

function filterSignalsBy(data) {
    const activeSources = [...document.querySelectorAll('.filter-source:checked')].map(cb => cb.value);
    const activeStrengths = [...document.querySelectorAll('.filter-strength:checked')].map(cb => cb.value);
    return data.filter(s => activeSources.includes(s.source) && activeStrengths.includes(s.strength));
}

async function toggleEarlier() {
    const body = document.getElementById('earlierBody');
    const btn = document.getElementById('earlierToggle');
    if (!body || !btn) return;
    if (body.style.display === 'none') {
        body.style.display = 'block';
        btn.textContent = '▴ 收起更早的情报';
        if (!body.dataset.loaded) {
            body.dataset.loaded = '1';
            await loadDailyIntel(30);
        }
    } else {
        body.style.display = 'none';
        btn.textContent = '▾ 查看更早的情报';
    }
}

```

- [ ] **Step 4: JS——loadDailyIntel / renderDailyIntel 目标感知（3 处小改）**

改 1（loadDailyIntel 的 loading 行）：
old_string：
```js
async function loadDailyIntel(days) {
    dailyDays = days;
    document.getElementById('mainContent').innerHTML = '<div class="loading">加载中...</div>';
```
new_string：
```js
async function loadDailyIntel(days) {
    dailyDays = days;
    const target = document.getElementById('earlierBody') || document.getElementById('mainContent');
    target.innerHTML = '<div class="loading">加载中...</div>';
```

改 2（renderDailyIntel 的 empty 分支）：
old_string：
```js
    if (dailyData.length === 0 && filtered.length === 0) {
        document.getElementById('mainContent').innerHTML = `
```
new_string：
```js
    const target = document.getElementById('earlierBody') || document.getElementById('mainContent');
    if (dailyData.length === 0 && filtered.length === 0) {
        target.innerHTML = `
```

改 3（renderDailyIntel 主分支末尾）：
old_string：
```js
    document.getElementById('mainContent').innerHTML = html;
}

function filterDailySignals() {
```
new_string：
```js
    target.innerHTML = html;
}

function filterDailySignals() {
```

- [ ] **Step 5: JS——包装器简化 + 抽 addAiToggles**

old_string（整个包装器，从 `// Override renderDailyIntel` 注释到 `};` 结束）：
```js
// Override renderDailyIntel to add date picker + AI analysis + daily report
const _origRenderDailyIntel = renderDailyIntel;
renderDailyIntel = function() {
    _origRenderDailyIntel();

    // Add date picker to daily header
    const today = new Date().toISOString().slice(0,10);
    const header = document.querySelector('.daily-header');
    if (header) {
        const existingPicker = header.querySelector('.date-picker-row');
        if (!existingPicker) {
            const picker = document.createElement('div');
            picker.className = 'date-picker-row';
            picker.innerHTML = `<span style="font-size:0.85em;color:#888;">📅 查看日期：</span>
                <input type="date" id="dailyDatePicker" value="${today}" onchange="loadDateSignals(this.value)">
                <button class="btn-sm primary" onclick="loadDateSignals(document.getElementById('dailyDatePicker').value)">查看</button>
                <button class="btn-sm" onclick="loadDailyReport(document.getElementById('dailyDatePicker').value)">📋 生成日报</button>`;
            header.appendChild(picker);
        }
    }

    // Add AI toggle to each signal card
    document.querySelectorAll('.signal-card').forEach(card => {
        const titleEl = card.querySelector('h4');
        if (!titleEl) return;
        const sigId = card.dataset.signalId;
        if (!sigId) return;

        // Check if AI toggle already exists
        if (card.querySelector('.ai-toggle')) return;

        const toggle = document.createElement('span');
        toggle.className = 'ai-toggle';
        toggle.textContent = '🤖 AI 解读';
        toggle.onclick = function() {
            const title = titleEl.textContent || '';
            const summaryEl = card.querySelector('.sig-summary');
            const summary = summaryEl ? summaryEl.textContent : '';
            const sourceEl = card.querySelector('.sig-source');
            const source = sourceEl ? sourceEl.textContent : '';
            analyzeSignal(sigId, title, summary, source);
        };
        card.appendChild(toggle);

        const panel = document.createElement('div');
        panel.className = 'ai-panel';
        panel.id = 'ai-' + sigId;
        card.appendChild(panel);
    });

    // Daily report container
    let reportContainer = document.getElementById('dailyReportContainer');
    if (!reportContainer) {
        reportContainer = document.createElement('div');
        reportContainer.id = 'dailyReportContainer';
        const feed = document.querySelector('.daily-feed');
        if (feed) feed.appendChild(reportContainer);
    }
};
```
new_string：
```js
// Add AI-analysis toggles to every signal card under a root element.
function addAiToggles(rootEl) {
    (rootEl || document).querySelectorAll('.signal-card').forEach(card => {
        const titleEl = card.querySelector('h4');
        if (!titleEl) return;
        const sigId = card.dataset.signalId;
        if (!sigId) return;

        // Check if AI toggle already exists
        if (card.querySelector('.ai-toggle')) return;

        const toggle = document.createElement('span');
        toggle.className = 'ai-toggle';
        toggle.textContent = '🤖 AI 解读';
        toggle.onclick = function() {
            const title = titleEl.textContent || '';
            const summaryEl = card.querySelector('.sig-summary');
            const summary = summaryEl ? summaryEl.textContent : '';
            const sourceEl = card.querySelector('.sig-source');
            const source = sourceEl ? sourceEl.textContent : '';
            analyzeSignal(sigId, title, summary, source);
        };
        card.appendChild(toggle);

        const panel = document.createElement('div');
        panel.className = 'ai-panel';
        panel.id = 'ai-' + sigId;
        card.appendChild(panel);
    });
}

// Override renderDailyIntel (earlier range view) to add AI toggles.
// Date picker lives in the today-view header; the daily report card is
// rendered at the top of the today view, not appended to the feed.
const _origRenderDailyIntel = renderDailyIntel;
renderDailyIntel = function() {
    _origRenderDailyIntel();
    addAiToggles(document.getElementById('earlierBody') || document.getElementById('mainContent'));
};
```

- [ ] **Step 6: JS——onFilterChange 今日视图适配**

old_string：
```js
function onFilterChange() {
    if (currentView === 'daily') {
        renderDailyIntel();
    } else {
        renderSignals();
    }
}
```
new_string：
```js
function onFilterChange() {
    if (currentView === 'daily') {
        if (document.getElementById('todayFeed')) {
            renderTodayFeed();
            const body = document.getElementById('earlierBody');
            if (body && body.dataset.loaded) renderDailyIntel();
        } else {
            renderDailyIntel();
        }
    } else {
        renderSignals();
    }
}
```

- [ ] **Step 7: JS——loadDateSignals 加"返回今日"**

old_string（loadDateSignals 的 header 部分）：
```js
            <div class="date-picker-row">
                <span style="font-size:0.85em;color:#888;">📅 查看日期：</span>
                <input type="date" id="dailyDatePicker" value="${dateStr}" onchange="loadDateSignals(this.value)">
                <button class="btn-sm primary" onclick="loadDateSignals(document.getElementById('dailyDatePicker').value)">查看</button>
                <button class="btn-sm" onclick="loadDailyReport(document.getElementById('dailyDatePicker').value)">📋 生成日报</button>
            </div>
```
new_string：
```js
            <div class="date-picker-row">
                <span style="font-size:0.85em;color:#888;">📅 查看日期：</span>
                <input type="date" id="dailyDatePicker" value="${dateStr}" onchange="loadDateSignals(this.value)">
                <button class="btn-sm primary" onclick="loadDateSignals(document.getElementById('dailyDatePicker').value)">查看</button>
                <button class="btn-sm" onclick="loadDailyReport(document.getElementById('dailyDatePicker').value)">📋 生成日报</button>
                <button class="btn-sm" onclick="loadTodayView()">← 返回今日</button>
            </div>
```

- [ ] **Step 8: JS——SSE complete 条件刷新**

old_string：
```js
                // Reload daily intel view
                setTimeout(() => loadDailyIntel(dailyDays || 30), 1500);
```
new_string：
```js
                // Reload the active daily view (today view by default)
                setTimeout(() => {
                    if (document.getElementById('todayFeed')) loadTodayView();
                    else loadDailyIntel(dailyDays || 30);
                }, 1500);
```

- [ ] **Step 9: 创建验证脚本 `scripts/verify_today_view.js`**

```js
// scripts/verify_today_view.js — today-view structure assertions at 390px + 1280px.
// Usage: node scripts/verify_today_view.js <url> <outdir>
// Exit 0 = all checks pass. Screenshots saved to <outdir>.
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');
const pw = require(path.join(execSync('npm root -g').toString().trim(), 'playwright'));

const URL_ = process.argv[2] || 'http://127.0.0.1:8770';
const OUT = process.argv[3] || '/tmp/gs_today_verify';
const failures = [];
function check(name, ok) {
    console.log((ok ? 'PASS' : 'FAIL') + '  ' + name);
    if (!ok) failures.push(name);
}
process.on('unhandledRejection', e => {
    console.log('FAIL  exception: ' + e.message);
    process.exit(1);
});

(async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const b = await pw.chromium.launch();
    for (const [w, h, tag] of [[390, 844, 'mobile'], [1280, 900, 'desktop']]) {
        const pg = await b.newPage({ viewport: { width: w, height: h } });
        await pg.goto(URL_, { waitUntil: 'networkidle' });
        await pg.waitForTimeout(1200);

        check(tag + ': report container above today feed', await pg.evaluate(() => {
            const rc = document.getElementById('dailyReportContainer');
            const tf = document.getElementById('todayFeed');
            if (!rc || !tf) return false;
            return !!(rc.compareDocumentPosition(tf) & Node.DOCUMENT_POSITION_FOLLOWING);
        }));

        check(tag + ': earlier section collapsed by default', await pg.evaluate(() => {
            const body = document.getElementById('earlierBody');
            return body && body.style.display === 'none';
        }));

        await pg.click('#earlierToggle');
        await pg.waitForTimeout(1500);
        check(tag + ': earlier expands with day selector', await pg.evaluate(() => {
            const body = document.getElementById('earlierBody');
            return body && body.style.display !== 'none' && !!body.querySelector('.day-selector');
        }));
        await pg.screenshot({ path: path.join(OUT, tag + '_today_expanded.png'), fullPage: true });

        await pg.evaluate(() => { document.getElementById('dailyDatePicker').value = '2026-07-24'; });
        await pg.click('.daily-header .date-picker-row .btn-sm.primary');
        await pg.waitForTimeout(1200);
        check(tag + ': historical view offers back-to-today', await pg.evaluate(() =>
            [...document.querySelectorAll('button')].some(b => b.textContent.includes('返回今日'))
        ));
        await pg.screenshot({ path: path.join(OUT, tag + '_historical.png'), fullPage: true });

        await pg.click('button:has-text("返回今日")');
        await pg.waitForTimeout(1200);
        check(tag + ': back-to-today restores today view', await pg.evaluate(() =>
            !!document.getElementById('todayFeed')
        ));
        await pg.close();
    }
    await b.close();
    console.log(failures.length ? `\n${failures.length} FAIL` : '\nALL PASS');
    process.exit(failures.length ? 1 : 0);
})();
```

- [ ] **Step 10: 重启服务 + 跑验证（GREEN）**

```bash
pkill -f "uvicorn src.web:app --port 8770"; sleep 1
nohup uvicorn src.web:app --port 8770 > /tmp/uv8770.log 2>&1 & sleep 3
node scripts/verify_today_view.js http://127.0.0.1:8770 /tmp/gs_today_verify
```
Expected: 10 个 PASS + `ALL PASS`，退出码 0。注意：打开页面会触发真实日报生成（若今日无缓存且有 LLM 配置），属预期行为，不影响结构断言。

- [ ] **Step 11: 回归 + 手机端既有验证不破 + Commit**

```bash
pytest -q
node scripts/verify_mobile.js http://127.0.0.1:8770 /tmp/gs_mobile_recheck
git add templates/dashboard.html scripts/verify_today_view.js
git commit -m "feat(daily-report): today-first daily intel view with top report card"
```
Expected：pytest 全绿；verify_mobile.js 仍然 ALL PASS（抽屉/溢出/面板断言不受本次改动影响——若 daily 视图相关断言失败，分析根因再修，不要猜）。

---

### Task 4: 全量回归 + 部署 + 真机确认

**Files:** 无新增（纯验证与发布）

- [ ] **Step 1: 全量 pytest**

```bash
pytest -q
```
Expected: 全绿（283+，以实际为准）

- [ ] **Step 2: 桌面端结构对比**

今日视图是本特性有意的全端改动（桌面也变为今日视图），所以不做像素对比，改为人工核对 1280px 截图（`/tmp/gs_today_verify/desktop_*.png`）：布局合理、无溢出、季度/设置页不受影响（`node scripts/ui_snapshot.js http://127.0.0.1:8770 1280 900 /tmp/gs_d_recheck` 核对 2_settings/3_quarter 与 `/tmp/gs_d_before/` 一致）。

- [ ] **Step 3: Commit 计划/报告残留 + 部署**

```bash
git status --short  # 确认无未提交残留（.superpowers/ 已被 gitignore）
git push origin main
sleep 30
curl -s -o /dev/null -w "%{http_code}" http://111.228.23.109/
```
Expected: 工作区干净；push 成功；`401`

- [ ] **Step 4: 真机验证（用户手动）**

给用户操作步骤：手机打开 `http://111.228.23.109` → 每日情报默认展示今日视图：顶部📋摘要卡（首次可能显示"生成中…"约 30-60 秒后出内容）→ 今日情报列表 → 底部"▾ 查看更早的情报"展开正常 → 点日期"查看"进历史视图 → "← 返回今日"正常 → 跑一次"📡 手动运行每日情报"，结束后页面自动刷新且日报最终出现。

---

## Self-Review 记录

- **Spec 覆盖**：spec 组件 1（抽模块）→Task 1；组件 2（流水线接入）→Task 2；组件 3（前端重排）→Task 3；测试策略→各任务 + Task 4。spec"历史日期日报手动按钮"→ loadDateSignals 保留生成日报按钮（Task 3 Step 7 可见）。
- **占位符扫描**：无 TBD/TODO；每步含完整新代码；删除目标均给出完整 old_string 或精确边界（函数行号范围 + 相邻注释锚点）。
- **命名一致性**：`generate_daily_report`/`ensure_daily_report`（Task 1 产出，Task 2/端点消费）；`todayData`/`loadTodayView`/`renderTodayView`/`renderTodayFeed`/`filterSignalsBy`/`toggleEarlier`/`addAiToggles`/`#dailyReportContainer`/`#todayFeed`/`#earlierToggle`/`#earlierBody`（Task 3 内一致，验证脚本引用同一批 id）；`filterDailySignals` 保留兼容（内部转调 `filterSignalsBy`）。
- **冗余检查**：`filterDailySignals()` 现有调用点（renderDailyIntel、loadDateSignals）继续工作——Step 3 的 `filterSignalsBy` 是其泛化，`filterDailySignals` 本体不动（仍 `return filterSignalsBy(dailyData)`……注意：本计划不修改 `filterDailySignals` 的现有实现，它已等价于 `filterSignalsBy(dailyData)`）。
