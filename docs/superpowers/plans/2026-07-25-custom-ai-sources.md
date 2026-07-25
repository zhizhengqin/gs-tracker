# 自定义信息源 + AI 预筛 实施计划（P1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户在设置页添加自定义 RSS 信息源，每日情报流水线抓取后由 AI 批量预筛再入库。

**Architecture:** 参数化现有 NewsSource（source_name + filter_policy）支撑按源实例；新增 AiTriage 组件批量预筛（预算制 + 确定性回退）；流水线在抓取后、评分前插入预筛步骤并推送 triage_note SSE 事件；设置 API/UI 提供自定义源 CRUD 和测试源按钮。

**Tech Stack:** Python 3.11, FastAPI, httpx, feedparser, anthropic SDK, SQLite (app_settings), Jinja2 SPA (vanilla JS)

**Spec:** `docs/superpowers/specs/2026-07-25-custom-ai-sources-design.md`

## Global Constraints

- 现有 215 个测试必须保持全绿（除非任务明确要求修改/替换的测试）
- 用户可见输出全部中文；代码内部（标识符/注释/commit）英文
- LLM 配置解析：DB 默认模型优先，环境变量兜底；API key 只从环境变量/DB 读取，禁止硬编码、禁止打印
- 预筛只适用于新闻类源（内置 `news` + 自定义源）；`8-K`/`13D/13G`/`research_view` 权威源直接入库
- 参数化 SQL；SEC 请求带 User-Agent（现有源已处理，勿破坏）
- 合规：AI 预筛只做相关性判断，不生成投资建议
- 每完成一个 Task 运行 `pytest -q` 验证，然后 commit

---

### Task 1: NewsSource 参数化（source_name + filter_policy）

**Files:**
- Modify: `src/signals/news_source.py`（`__init__` 与 `fetch`）
- Test: `tests/signals/test_news_source.py`

**Interfaces:**
- Consumes: 现有 `NewsSource` 类、`Signal`、`SignalStrength`
- Produces: `NewsSource(rss_urls=None, source_name="news", filter_policy="gs_only")`；`filter_policy ∈ {"gs_only","all"}`；`Signal.source == source_name`。Task 4 的 `_build_daily_sources` 依赖此签名实例化自定义源。

- [ ] **Step 1: Write the failing tests**

在 `tests/signals/test_news_source.py` 的 `TestNewsSource` 类中追加（文件顶部需 `from src.signals.base import SignalStrength`）：

```python
    @pytest.mark.asyncio
    async def test_custom_source_name_and_all_policy(self, httpx_mock: HTTPXMock):
        """filter_policy='all' keeps non-GS items as LOW, tagged with source_name."""
        rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><title>A股三大股指跌超1%</title><link>https://a.com/1</link>
          <description>市场概述，无机构提及</description>
          <pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        httpx_mock.add_response(text=rss, status_code=200)
        source = NewsSource(
            rss_urls=["https://example.com/rss"],
            source_name="caixin",
            filter_policy="all",
        )
        signals = await source.fetch("2026-Q2")
        assert len(signals) == 1
        assert signals[0].source == "caixin"
        assert signals[0].strength == SignalStrength.LOW
        await source.close()

    @pytest.mark.asyncio
    async def test_default_policy_still_gs_only(self, httpx_mock: HTTPXMock):
        """Omitting filter_policy keeps the GS-focused default behavior."""
        rss = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><title>A股三大股指跌超1%</title><link>https://a.com/1</link>
          <description>市场概述，无机构提及</description>
          <pubDate>Mon, 15 May 2026 10:00:00 GMT</pubDate></item>
        </channel></rss>"""
        httpx_mock.add_response(text=rss, status_code=200)
        source = NewsSource(rss_urls=["https://example.com/rss"])
        signals = await source.fetch("2026-Q2")
        assert signals == []
        await source.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/signals/test_news_source.py -q -k "custom_source_name or default_policy"`
Expected: FAIL（`TypeError: NewsSource.__init__() got an unexpected keyword argument 'source_name'`）

- [ ] **Step 3: Implement**

`src/signals/news_source.py` 的 `__init__` 改为：

```python
    def __init__(
        self,
        rss_urls: Optional[List[str]] = None,
        source_name: str = "news",
        filter_policy: str = "gs_only",
    ) -> None:
        """rss_urls: feeds to poll. source_name: Signal.source tag (custom
        sources pass their own name). filter_policy: 'gs_only' keeps only
        GS-related items (default), 'all' keeps everything as LOW."""
        self.rss_urls = rss_urls or []
        self.source_name = source_name
        self.filter_policy = filter_policy
        self.client = httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": SEC_USER_AGENT},
        )
```

`fetch` 中信号构建段改为（替换现有的过滤/强度/Signal 构造逻辑）：

```python
        signals: List[Signal] = []
        for item in all_items:
            title = clean_html_text(item["title"])
            summary_text = clean_html_text(item.get("summary", ""))
            text_lower = (title + " " + summary_text).lower()

            has_gs = any(rx.search(text_lower) for rx in _GS_RE)
            has_viewpoint = any(rx.search(text_lower) for rx in _VIEWPOINT_RE)
            # gs_only: GS angle required (user feedback 2026-07).
            # all: custom-source policy — keep everything as LOW.
            if self.filter_policy == "gs_only" and not (has_gs or has_viewpoint):
                continue

            published_at = datetime.now(timezone.utc)
            if item.get("published_parsed"):
                try:
                    tp = item["published_parsed"]
                    published_at = datetime(*tp[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    pass

            if published_at < cutoff:
                continue

            if self.filter_policy == "gs_only":
                companies: List[str] = []
                for kw, rx in _HOLDING_RE:
                    if rx.search(text_lower):
                        companies.append(kw.upper())
                strength = SignalStrength.HIGH if has_viewpoint else SignalStrength.MEDIUM
            else:
                companies = []
                strength = SignalStrength.LOW

            signals.append(Signal(
                title=title,
                source=self.source_name,
                published_at=published_at,
                summary=summary_text[:200] if summary_text else title,
                companies=companies if companies else ["GS"],
                strength=strength,
                url=item.get("link") or None,
            ))

        return signals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/signals/test_news_source.py -q`
Expected: 全部 PASS（含原有测试）

- [ ] **Step 5: Commit**

```bash
git add src/signals/news_source.py tests/signals/test_news_source.py
git commit -m "feat(news): NewsSource 参数化 source_name + filter_policy 支撑自定义源"
```

---

### Task 2: 共享 LLM 配置解析（src/llm_config.py）

**Files:**
- Create: `src/llm_config.py`
- Modify: `src/web.py`（`_llm_client_kwargs` 改为委托）
- Test: `tests/test_llm_config.py`（新建）

**Interfaces:**
- Consumes: `src.config` 的 `ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL / GS_LLM_MODEL`；DB 模型 dict（键 `auth_token/base_url/model_name`）
- Produces: `resolve_llm_config(db_model: dict | None) -> dict`，返回键 `api_key, auth_token, base_url, model`（前三者可 None）。Task 3 的 AiTriage 和 Task 4 的流水线依赖；`web.py` 保留 `_llm_client_kwargs` 同名薄封装（现有测试不破坏）。

- [ ] **Step 1: Write the failing test**

新建 `tests/test_llm_config.py`：

```python
"""Tests for src.llm_config."""
from src.llm_config import resolve_llm_config


def test_db_model_wins(monkeypatch):
    db_model = {"auth_token": "db-token", "base_url": "https://db.test", "model_name": "db-model"}
    cfg = resolve_llm_config(db_model)
    assert cfg == {
        "api_key": None,
        "auth_token": "db-token",
        "base_url": "https://db.test",
        "model": "db-model",
    }


def test_env_fallback_includes_api_key(monkeypatch):
    monkeypatch.setattr("src.config.ANTHROPIC_API_KEY", "ak-123")
    monkeypatch.setattr("src.config.ANTHROPIC_AUTH_TOKEN", "")
    monkeypatch.setattr("src.config.ANTHROPIC_BASE_URL", "")
    monkeypatch.setattr("src.config.GS_LLM_MODEL", "env-model")
    cfg = resolve_llm_config(None)
    assert cfg["api_key"] == "ak-123"
    assert cfg["auth_token"] is None
    assert cfg["base_url"] is None
    assert cfg["model"] == "env-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_config.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.llm_config'`）

- [ ] **Step 3: Implement**

新建 `src/llm_config.py`：

```python
"""Shared LLM client configuration resolution (DB default first, env fallback)."""
from typing import Optional


def resolve_llm_config(db_model: Optional[dict]) -> dict:
    """Resolve LLM settings. db_model: row from get_default_llm_model() or None.
    Returns dict with keys api_key, auth_token, base_url, model (first three
    may be None when unset)."""
    if db_model:
        return {
            "api_key": None,
            "auth_token": db_model["auth_token"] or None,
            "base_url": db_model["base_url"] or None,
            "model": db_model["model_name"],
        }
    from src.config import (
        ANTHROPIC_API_KEY,
        ANTHROPIC_AUTH_TOKEN,
        ANTHROPIC_BASE_URL,
        GS_LLM_MODEL,
    )
    return {
        "api_key": ANTHROPIC_API_KEY or None,
        "auth_token": ANTHROPIC_AUTH_TOKEN or None,
        "base_url": ANTHROPIC_BASE_URL or None,
        "model": GS_LLM_MODEL,
    }
```

`src/web.py` 中 `_llm_client_kwargs` 改为薄封装（保持现有测试兼容）：

```python
def _llm_client_kwargs(db_model: Optional[dict]) -> dict:
    """Thin wrapper kept for existing call sites; logic lives in llm_config."""
    from src.llm_config import resolve_llm_config

    return resolve_llm_config(db_model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_config.py tests/test_web.py -q`
Expected: 全部 PASS（`test_llm_client_kwargs_*` 两个旧测试仍绿）

- [ ] **Step 5: Commit**

```bash
git add src/llm_config.py src/web.py tests/test_llm_config.py
git commit -m "refactor(llm): 抽取共享 LLM 配置解析到 src/llm_config.py"
```

---

### Task 3: AiTriage AI 预筛器

**Files:**
- Create: `src/signals/ai_triage.py`
- Test: `tests/signals/test_ai_triage.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `resolve_llm_config` 输出 dict；`get_setting/set_setting` 可调用对（键值存取，签名同 `src.storage`）；`anthropic.AsyncAnthropic`
- Produces:
  - `TriageResult` dataclass：`kept_indices: list[int]`, `fallback_used: bool = False`, `note: str = ""`
  - `AiTriage(llm_config: dict, get_setting, set_setting, daily_budget: int = 20)`
  - `AiTriage.triage(items: list[dict], source_label: str, filter_policy: str) -> TriageResult`（协程；items 元素含 `title`/`summary` 键；kept_indices 为 0 基索引，升序）
  - 失败语义：任何 LLM 故障/预算耗尽/未配置 → 返回全部索引 + `fallback_used=True` + 中文 `note`（调用方对 gs_only 源已做关键词预过滤，"全保留"即回退）

- [ ] **Step 1: Write the failing tests**

新建 `tests/signals/test_ai_triage.py`：

```python
"""Tests for src.signals.ai_triage."""
import pytest

from src.signals.ai_triage import AiTriage, TriageResult

LLM_CFG = {"api_key": None, "auth_token": "tok", "base_url": "https://x.test", "model": "m"}
NO_CFG = {"api_key": None, "auth_token": None, "base_url": None, "model": "m"}


def _store():
    store = {}
    return store, (lambda k, d="": store.get(k, d)), (lambda k, v: store.__setitem__(k, v))


def _items(n):
    return [{"title": f"标题{i}", "summary": f"摘要{i}"} for i in range(n)]


class _FakeClient:
    """Scripted LLM client. responses: list of texts, one per create() call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            self._outer.calls += 1
            text = self._outer.responses.pop(0)

            class _Block:
                pass

            class _Resp:
                pass

            block = _Block()
            block.text = text
            resp = _Resp()
            resp.content = [block]
            return resp


class _FailClient:
    def __init__(self, **kwargs):
        self.messages = self._Messages()

    class _Messages:
        async def create(self, **kwargs):
            raise RuntimeError("gateway down")


def _patch_client(monkeypatch, client_or_responses):
    if isinstance(client_or_responses, list):
        client = _FakeClient(client_or_responses)
        monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: client)
        return client
    monkeypatch.setattr("anthropic.AsyncAnthropic", client_or_responses)
    return None


@pytest.mark.asyncio
async def test_keep_indices_parsed(monkeypatch):
    store, gs, ss = _store()
    _patch_client(monkeypatch, ['{"keep": [2], "reason": "仅这条相关"}'])
    triage = AiTriage(LLM_CFG, gs, ss)
    result = await triage.triage(_items(3), "测试源", "gs_only")
    assert result.kept_indices == [1]
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_batches_split(monkeypatch):
    store, gs, ss = _store()
    client = _patch_client(monkeypatch, ['{"keep": [1]}', '{"keep": [21]}'])
    triage = AiTriage(LLM_CFG, gs, ss)
    result = await triage.triage(_items(25), "测试源", "all")
    assert client.calls == 2
    assert result.kept_indices == [0, 20]


@pytest.mark.asyncio
async def test_garbage_json_falls_back(monkeypatch):
    store, gs, ss = _store()
    _patch_client(monkeypatch, ["我觉得都不错"])
    triage = AiTriage(LLM_CFG, gs, ss)
    result = await triage.triage(_items(2), "测试源", "gs_only")
    assert result.kept_indices == [0, 1]
    assert result.fallback_used is True
    assert result.note


@pytest.mark.asyncio
async def test_llm_error_falls_back(monkeypatch):
    store, gs, ss = _store()
    _patch_client(monkeypatch, _FailClient)
    triage = AiTriage(LLM_CFG, gs, ss)
    result = await triage.triage(_items(2), "测试源", "gs_only")
    assert result.kept_indices == [0, 1]
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_budget_exhausted(monkeypatch):
    store, gs, ss = _store()
    client = _patch_client(monkeypatch, ['{"keep": [1]}'])
    triage = AiTriage(LLM_CFG, gs, ss, daily_budget=1)
    result = await triage.triage(_items(25), "测试源", "all")
    assert client.calls == 1  # 第二批不再调用
    assert result.kept_indices == [0] + list(range(20, 25))
    assert result.fallback_used is True
    assert "预算" in result.note


@pytest.mark.asyncio
async def test_no_llm_configured_falls_back():
    store, gs, ss = _store()
    triage = AiTriage(NO_CFG, gs, ss)
    result = await triage.triage(_items(2), "测试源", "gs_only")
    assert result.kept_indices == [0, 1]
    assert result.fallback_used is True
    assert "大模型" in result.note


@pytest.mark.asyncio
async def test_budget_key_contains_date():
    store, gs, ss = _store()
    triage = AiTriage(NO_CFG, gs, ss)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today in triage._budget_key()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/signals/test_ai_triage.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'src.signals.ai_triage'`）

- [ ] **Step 3: Implement**

新建 `src/signals/ai_triage.py`：

```python
"""AI-based pre-ingest triage for news-type signal sources.

Batches candidate items through the configured LLM to decide keep/drop.
Any failure (no config, LLM error, unparseable output, budget exhausted)
falls back deterministically to keeping everything — callers pre-filter
gs_only sources by keywords at fetch time, so 'keep all' IS the fallback.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
DEFAULT_DAILY_BUDGET = 20

_CRITERIA = {
    "gs_only": (
        "仅保留与高盛（Goldman Sachs）相关的内容：高盛的观点、研报、评级、"
        "目标价、人事与业务动态。与高盛无关的一律不留。"
    ),
    "all": (
        "保留对 A 股投资者有参考价值的内容：市场趋势、宏观政策、机构观点、"
        "重大公司动态。丢弃广告、软文、推广、与财经无关的花边。拿不准的可以保留。"
    ),
}


@dataclass
class TriageResult:
    kept_indices: list = field(default_factory=list)
    fallback_used: bool = False
    note: str = ""


def _parse_keep(text: str, batch_len: int) -> Optional[list]:
    """Extract {"keep": [1-based indices]} from model output; None if unparseable."""
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    keep = obj.get("keep")
    if not isinstance(keep, list):
        return None
    return [i - 1 for i in keep if isinstance(i, int) and 1 <= i <= batch_len]


class AiTriage:
    """Batch LLM screening with daily call budget and deterministic fallback."""

    def __init__(
        self,
        llm_config: dict,
        get_setting: Callable[[str, str], str],
        set_setting: Callable[[str, str], None],
        daily_budget: int = DEFAULT_DAILY_BUDGET,
    ) -> None:
        self.llm_config = llm_config
        self._get_setting = get_setting
        self._set_setting = set_setting
        self.daily_budget = daily_budget

    def _budget_key(self) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"ai_triage_count_{day}"

    def _calls_used_today(self) -> int:
        try:
            return int(self._get_setting(self._budget_key(), "0") or "0")
        except ValueError:
            return 0

    def _increment_calls(self) -> None:
        self._set_setting(self._budget_key(), str(self._calls_used_today() + 1))

    def _build_prompt(self, batch: list, source_label: str, filter_policy: str) -> str:
        criteria = _CRITERIA.get(filter_policy, _CRITERIA["gs_only"])
        numbered = "\n".join(
            f"{i + 1}. {it['title']} — {it['summary'][:150]}"
            for i, it in enumerate(batch)
        )
        return (
            "你是投资情报筛选助手。用户是中国 A 股个人投资者，关注高盛观点以判断市场趋势。\n\n"
            f"信息源：{source_label}\n"
            f"筛选标准：{criteria}\n\n"
            f"候选内容（编号. 标题 — 摘要）：\n{numbered}\n\n"
            '只输出 JSON，不要输出其他内容：{"keep": [要保留的编号], "reason": "一句话理由"}'
        )

    async def triage(self, items: list, source_label: str, filter_policy: str) -> TriageResult:
        if not items:
            return TriageResult(kept_indices=[])
        if not (self.llm_config.get("api_key") or self.llm_config.get("auth_token")):
            return TriageResult(
                kept_indices=list(range(len(items))),
                fallback_used=True,
                note="未配置大模型，已跳过 AI 预筛",
            )

        import anthropic

        client = anthropic.AsyncAnthropic(
            api_key=self.llm_config.get("api_key"),
            auth_token=self.llm_config.get("auth_token"),
            base_url=self.llm_config.get("base_url"),
            timeout=30.0,
        )

        kept: list = []
        fallback_note = ""
        for start in range(0, len(items), BATCH_SIZE):
            if self._calls_used_today() >= self.daily_budget:
                kept.extend(range(start, len(items)))
                fallback_note = "AI 预算已用完，其余条目按基础规则保留"
                break
            batch = items[start:start + BATCH_SIZE]
            prompt = self._build_prompt(batch, source_label, filter_policy)
            try:
                resp = await client.messages.create(
                    model=self.llm_config["model"],
                    max_tokens=512,
                    messages=[{"role": "user", "content": prompt}],
                )
                self._increment_calls()
            except Exception as exc:
                logger.warning("AI triage call failed: %s", exc)
                kept.extend(range(start, len(items)))
                fallback_note = "AI 预筛不可用，已用基础过滤"
                break
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            batch_keep = _parse_keep(text, len(batch))
            if batch_keep is None:
                logger.warning("AI triage returned unparseable output: %.200s", text)
                kept.extend(range(start, len(items)))
                fallback_note = "AI 返回格式异常，已用基础过滤"
                break
            kept.extend(start + i for i in batch_keep)

        return TriageResult(
            kept_indices=sorted(kept),
            fallback_used=bool(fallback_note),
            note=fallback_note,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/signals/test_ai_triage.py -q`
Expected: 7 个测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/signals/ai_triage.py tests/signals/test_ai_triage.py
git commit -m "feat(triage): AiTriage 批量 AI 预筛器（预算制 + 确定性回退）"
```

---

### Task 4: 流水线集成（main.py）

**Files:**
- Modify: `src/main.py`（imports、`_build_daily_sources`、新增 `_custom_source_configs`、删除 `_all_rss_feeds`、`run_daily_intel_stream` 插入预筛）
- Test: `tests/test_main.py`（替换 `test_all_rss_feeds_merges_custom_sources`，新增 3 个测试）

**Interfaces:**
- Consumes: Task 1 的 `NewsSource(rss_urls, source_name, filter_policy)`；Task 2 的 `resolve_llm_config`；Task 3 的 `AiTriage`/`TriageResult`；`src.storage` 的 `get_default_llm_model`、`set_setting`
- Produces:
  - `_custom_source_configs() -> list[dict]`（sources_config 中 `builtin` 非 true 的条目）
  - `_build_daily_sources()` 末尾追加启用的自定义 RSS 源
  - SSE 新事件：`{"event": "triage_note", "source": <name>, "note": <中文>}`（前端 Task 7 消费）
  - `complete` 事件的 `new_signals` 为预筛后数量

- [ ] **Step 1: Write the failing tests**

`tests/test_main.py`：删除整个 `test_all_rss_feeds_merges_custom_sources`，在 `TestDailyIntel` 中新增：

```python
    @pytest.mark.asyncio
    async def test_build_daily_sources_includes_custom(self, monkeypatch):
        """Enabled custom RSS entries become per-source NewsSource instances."""
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = json.dumps([
            {"name": "news", "enabled": True, "builtin": True},
            {"name": "caixin", "label": "财新网", "type": "rss",
             "url": "https://custom.test/feed", "filter_policy": "all",
             "enabled": True, "builtin": False},
        ])
        with patch("src.main.get_setting", return_value=config), \
             patch("src.main.NewsSource") as MockNews, \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"):
            from src.main import _build_daily_sources

            _build_daily_sources()

        custom_call = MockNews.call_args_list[0]
        assert custom_call.kwargs["rss_urls"] == ["https://custom.test/feed"]
        assert custom_call.kwargs["source_name"] == "caixin"
        assert custom_call.kwargs["filter_policy"] == "all"

    @pytest.mark.asyncio
    async def test_build_daily_sources_skips_disabled_custom(self, monkeypatch):
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = json.dumps([
            {"name": "news", "enabled": True, "builtin": True},
            {"name": "caixin", "label": "财新网", "type": "rss",
             "url": "https://custom.test/feed", "enabled": False, "builtin": False},
        ])
        with patch("src.main.get_setting", return_value=config), \
             patch("src.main.NewsSource"), \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"):
            from src.main import _build_daily_sources

            names = [n for n, _ in _build_daily_sources()]

        assert "caixin" not in names

    @pytest.mark.asyncio
    async def test_stream_runs_triage_and_emits_note(self, tmp_path, monkeypatch, _mock_sources, _mock_storage, make_signal):
        """News items go through AiTriage; fallback emits a triage_note event."""
        from src.signals.ai_triage import TriageResult

        monkeypatch.setattr("src.main.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.config.REPORT_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("src.main.RSS_FEEDS", ["https://x.test/rss"])
        sig1 = make_signal(id="n1", source="news", title="高盛研报A")
        sig2 = make_signal(id="n2", source="news", title="无关新闻B")
        _mock_sources["news"].return_value.fetch_since = AsyncMock(
            return_value=([sig1, sig2], None)
        )

        with patch("src.main.AiTriage") as MockTriage, \
             patch("src.main.get_default_llm_model", return_value=None), \
             patch("src.main.get_recent_signals", return_value=[]):
            MockTriage.return_value.triage = AsyncMock(
                return_value=TriageResult(
                    kept_indices=[0], fallback_used=True, note="AI 预算已用完"
                )
            )
            from src.main import run_daily_intel_stream

            events = []
            async for ev in run_daily_intel_stream():
                events.append(json.loads(ev))

        note_events = [e for e in events if e["event"] == "triage_note"]
        assert len(note_events) == 1
        assert note_events[0]["source"] == "news"
        assert "预算" in note_events[0]["note"]
        complete = events[-1]
        assert complete["event"] == "complete"
        assert complete["new_signals"] == 1  # 仅保留 triage 选中的第 1 条
```

并在现有 `test_stream_emits_start_source_done_complete` 末尾追加一行断言（无新闻信号时不产生 triage_note）：

```python
        assert not any(e["event"] == "triage_note" for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -q -k "custom or triage"`
Expected: FAIL（`test_build_daily_sources_includes_custom` 断言失败；`test_stream_runs_triage_and_emits_note` 无 triage_note 事件）

- [ ] **Step 3: Implement**

`src/main.py` 顶部 imports 追加：

```python
from src.llm_config import resolve_llm_config
from src.signals.ai_triage import AiTriage
```

storage imports 中追加 `get_default_llm_model`、`set_setting`（并入现有 `from src.storage import (...)` 列表，保持字母序）。

删除 `_all_rss_feeds` 函数，替换为：

```python
def _custom_source_configs() -> list:
    """Custom (non-builtin) source entries from sources_config."""
    try:
        raw = get_setting("sources_config", "")
        if raw:
            return [s for s in json.loads(raw) if not s.get("builtin", False)]
    except Exception:
        logger.warning("Failed to parse custom sources from sources_config")
    return []
```

`_build_daily_sources` 改为：

```python
def _build_daily_sources() -> list:
    """Instantiate daily-intel sources, honoring per-source enable switches."""
    enabled = _enabled_source_names()
    sources: list[tuple[str, object]] = []
    if "8-K" in enabled:
        sources.append(("8-K", Sec8kSource()))
    if "13D/13G" in enabled:
        sources.append(("13D/13G", ThirteenDGSource()))
    if "research_view" in enabled:
        sources.append(("research_view", ResearchViewSource()))
    if "news" in enabled:
        feeds = list(RSS_FEEDS)
        if feeds:
            sources.append(("news", NewsSource(rss_urls=feeds)))
    # Custom RSS sources from the settings page (one instance per source)
    for entry in _custom_source_configs():
        if entry.get("name") in enabled and entry.get("type") == "rss" and entry.get("url"):
            sources.append((
                entry["name"],
                NewsSource(
                    rss_urls=[entry["url"]],
                    source_name=entry["name"],
                    filter_policy=entry.get("filter_policy", "gs_only"),
                ),
            ))
    return sources
```

`run_daily_intel_stream` 中，在 `# Merge + score` 注释之前插入预筛块：

```python
    # AI pre-ingest triage: news-type sources only (builtin "news" + custom
    # sources). Authoritative SEC/research sources bypass triage entirely.
    custom_entries = _custom_source_configs()
    triageable_names = {"news"} | {e.get("name", "") for e in custom_entries}
    triage_groups: dict[str, list[int]] = {}
    for idx, sig in enumerate(new_signals):
        if sig.source in triageable_names:
            triage_groups.setdefault(sig.source, []).append(idx)

    if triage_groups:
        policy_by_source = {"news": "gs_only"}
        policy_by_source.update(
            {e["name"]: e.get("filter_policy", "gs_only") for e in custom_entries}
        )
        llm_cfg = resolve_llm_config(get_default_llm_model())
        triage = AiTriage(llm_cfg, get_setting, set_setting)
        keep_indices: set[int] = set()
        for source_name, idxs in triage_groups.items():
            items = [
                {"title": new_signals[i].title, "summary": new_signals[i].summary}
                for i in idxs
            ]
            result = await triage.triage(items, source_name, policy_by_source[source_name])
            for kept in result.kept_indices:
                keep_indices.add(idxs[kept])
            if result.fallback_used:
                yield json.dumps({
                    "event": "triage_note",
                    "source": source_name,
                    "note": result.note,
                })
        new_signals = [
            sig for idx, sig in enumerate(new_signals)
            if sig.source not in triageable_names or idx in keep_indices
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -q`
Expected: 全部 PASS（含新 3 个 + 修改的流测试）

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(pipeline): 自定义源进入每日情报流水线 + AI 预筛 + triage_note SSE 事件"
```

---

### Task 5: 设置 API（自定义源 CRUD + 测试源）

**Files:**
- Modify: `src/web.py`（新增 4 个端点；`api_get_sources` 抽取共享辅助）
- Test: `tests/test_web.py`（追加测试类）

**Interfaces:**
- Consumes: `get_setting/set_setting`（sources_config JSON）；Task 1 的 `NewsSource`
- Produces:
  - `POST /api/settings/sources/custom`（201；body: name/label/url/filter_policy）—— 校验失败 422，重名 409
  - `PUT /api/settings/sources/custom/{name}`（body 可选字段 label/url/filter_policy/enabled）—— 内置或不存在 404
  - `DELETE /api/settings/sources/custom/{name}` —— 内置 400，不存在 404
  - `POST /api/settings/sources/test`（body: url）→ `{ok, count, sample_titles}`，不跑 AI、不入库
  - 辅助：`_default_source_entries() -> list`、`_stored_or_default_sources() -> list`、`BUILTIN_SOURCE_NAMES: set`

- [ ] **Step 1: Write the failing tests**

`tests/test_web.py` 末尾追加：

```python
# ====== Custom source settings API ======

def _custom_payload(**overrides):
    payload = {
        "name": "caixin",
        "label": "财新网",
        "url": "https://example.com/rss",
        "filter_policy": "all",
    }
    payload.update(overrides)
    return payload


def test_custom_source_crud_cycle(signals_db):
    resp = client.post("/api/settings/sources/custom", json=_custom_payload())
    assert resp.status_code == 201

    sources = client.get("/api/settings/sources").json()
    custom = [s for s in sources if s["name"] == "caixin"]
    assert len(custom) == 1
    assert custom[0]["builtin"] is False
    assert custom[0]["filter_policy"] == "all"
    assert custom[0]["enabled"] is True

    resp = client.put("/api/settings/sources/custom/caixin", json={"label": "财新", "enabled": False})
    assert resp.status_code == 200
    custom = [s for s in client.get("/api/settings/sources").json() if s["name"] == "caixin"]
    assert custom[0]["label"] == "财新"
    assert custom[0]["enabled"] is False

    resp = client.delete("/api/settings/sources/custom/caixin")
    assert resp.status_code == 200
    assert not [s for s in client.get("/api/settings/sources").json() if s["name"] == "caixin"]


def test_custom_source_validation(signals_db):
    assert client.post("/api/settings/sources/custom", json=_custom_payload(name="Bad Name")).status_code == 422
    assert client.post("/api/settings/sources/custom", json=_custom_payload(url="ftp://x")).status_code == 422
    assert client.post("/api/settings/sources/custom", json=_custom_payload(filter_policy="weird")).status_code == 422
    assert client.post("/api/settings/sources/custom", json=_custom_payload(label="")).status_code == 422


def test_custom_source_duplicate_rejected(signals_db):
    assert client.post("/api/settings/sources/custom", json=_custom_payload()).status_code == 201
    assert client.post("/api/settings/sources/custom", json=_custom_payload()).status_code == 409
    assert client.post("/api/settings/sources/custom", json=_custom_payload(name="news")).status_code == 409


def test_custom_source_delete_builtin_rejected(signals_db):
    assert client.delete("/api/settings/sources/custom/news").status_code == 400
    assert client.delete("/api/settings/sources/custom/nosuch").status_code == 404


def test_custom_source_edit_builtin_rejected(signals_db):
    assert client.put("/api/settings/sources/custom/news", json={"label": "x"}).status_code == 404


def test_test_source_endpoint(signals_db, monkeypatch, make_signal):
    class _FakeSource:
        def __init__(self, **kwargs):
            pass

        async def fetch(self, quarter):
            return [
                make_signal(id="t1", title="标题一"),
                make_signal(id="t2", title="标题二"),
            ]

        async def close(self):
            pass

    monkeypatch.setattr("src.signals.news_source.NewsSource", _FakeSource)
    resp = client.post("/api/settings/sources/test", json={"url": "https://example.com/rss"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["sample_titles"] == ["标题一", "标题二"]

    resp = client.post("/api/settings/sources/test", json={"url": "not-a-url"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web.py -q -k "custom_source or test_source_endpoint"`
Expected: FAIL（404/405 — 端点不存在）

- [ ] **Step 3: Implement**

`src/web.py` 顶部 imports 追加 `import json`、`import re`（若已有则跳过）。

`api_get_sources` 重构 + 新增端点（放在 `# ====== Signals by date ======` 注释之前）：

```python
BUILTIN_SOURCE_NAMES = {"13F", "8-K", "13D/13G", "research_view", "news", "macro_view"}


def _default_source_entries() -> list:
    """The six built-in sources, all enabled."""
    return [
        {"name": "13F", "label": "13F 持仓", "description": "高盛季度 13F 持仓报告", "enabled": True, "builtin": True},
        {"name": "8-K", "label": "SEC 8-K", "description": "高盛重大事件即时披露", "enabled": True, "builtin": True},
        {"name": "13D/13G", "label": "13D/13G", "description": "大股东权益变动披露", "enabled": True, "builtin": True},
        {"name": "research_view", "label": "高盛研究", "description": "官方 Insights 研究文章", "enabled": True, "builtin": True},
        {"name": "news", "label": "新闻", "description": "RSS 新闻关键词匹配", "enabled": True, "builtin": True},
        {"name": "macro_view", "label": "宏观指标", "description": "FRED 宏观数据（利率/VIX/美元）", "enabled": True, "builtin": True},
    ]


def _stored_or_default_sources() -> list:
    raw = get_setting("sources_config", "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return _default_source_entries()
```

`api_get_sources` 函数体简化为 `return _stored_or_default_sources()`。

新增端点：

```python
# ====== Custom signal sources ======

_CUSTOM_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _validate_custom_payload(config: dict) -> tuple:
    """Return (name, label, url, filter_policy) or raise 422."""
    name = (config.get("name") or "").strip()
    label = (config.get("label") or "").strip()
    url = (config.get("url") or "").strip()
    filter_policy = config.get("filter_policy") or "gs_only"
    if not name or not _CUSTOM_NAME_RE.match(name):
        raise HTTPException(status_code=422, detail="标识 name 必填，仅限小写字母/数字/下划线")
    if not label or len(label) > 30:
        raise HTTPException(status_code=422, detail="名称 label 必填且不超过 30 字")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
    if filter_policy not in ("gs_only", "all"):
        raise HTTPException(status_code=422, detail="filter_policy 必须是 gs_only 或 all")
    return name, label, url, filter_policy


@app.post("/api/settings/sources/custom", status_code=201)
async def api_add_custom_source(config: dict = Body(...)) -> dict:
    """Add a custom RSS signal source."""
    name, label, url, filter_policy = _validate_custom_payload(config)
    sources = _stored_or_default_sources()
    if any(s.get("name") == name for s in sources) or name in BUILTIN_SOURCE_NAMES:
        raise HTTPException(status_code=409, detail=f"标识 {name} 已存在")
    sources.append({
        "name": name,
        "label": label,
        "type": "rss",
        "url": url,
        "filter_policy": filter_policy,
        "enabled": True,
        "builtin": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    set_setting("sources_config", json.dumps(sources, ensure_ascii=False))
    return {"status": "ok", "name": name}


@app.put("/api/settings/sources/custom/{name}")
async def api_edit_custom_source(name: str, config: dict = Body(...)) -> dict:
    """Edit a custom source (label/url/filter_policy/enabled)."""
    sources = _stored_or_default_sources()
    entry = next((s for s in sources if s.get("name") == name and not s.get("builtin", True)), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="自定义源不存在")
    if "label" in config:
        label = (config.get("label") or "").strip()
        if not label or len(label) > 30:
            raise HTTPException(status_code=422, detail="名称 label 必填且不超过 30 字")
        entry["label"] = label
    if "url" in config:
        url = (config.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
        entry["url"] = url
    if "filter_policy" in config:
        if config["filter_policy"] not in ("gs_only", "all"):
            raise HTTPException(status_code=422, detail="filter_policy 必须是 gs_only 或 all")
        entry["filter_policy"] = config["filter_policy"]
    if "enabled" in config:
        entry["enabled"] = bool(config["enabled"])
    set_setting("sources_config", json.dumps(sources, ensure_ascii=False))
    return {"status": "ok"}


@app.delete("/api/settings/sources/custom/{name}")
async def api_delete_custom_source(name: str) -> dict:
    """Delete a custom source. Built-in sources cannot be deleted."""
    if name in BUILTIN_SOURCE_NAMES:
        raise HTTPException(status_code=400, detail="内置源不可删除")
    sources = _stored_or_default_sources()
    remaining = [s for s in sources if s.get("name") != name]
    if len(remaining) == len(sources):
        raise HTTPException(status_code=404, detail="自定义源不存在")
    set_setting("sources_config", json.dumps(remaining, ensure_ascii=False))
    return {"status": "ok"}


@app.post("/api/settings/sources/test")
async def api_test_source(config: dict = Body(...)) -> dict:
    """Fetch a candidate RSS URL once; return item count + sample titles.
    No AI calls, nothing persisted."""
    url = (config.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
    from src.signals.news_source import NewsSource

    source = NewsSource(rss_urls=[url], source_name="_test", filter_policy="all")
    try:
        signals = await source.fetch("")
        return {
            "ok": True,
            "count": len(signals),
            "sample_titles": [s.title for s in signals[:3]],
        }
    except Exception as exc:
        return {"ok": False, "error": f"抓取失败：{exc}"}
    finally:
        await source.close()
```

注意：`api_edit_custom_source` 中 `not s.get("builtin", True)` 的查找使得内置源（builtin=True）返回 404；删除走单独的 400 分支。

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/web.py tests/test_web.py
git commit -m "feat(settings): 自定义源 CRUD + 测试源 API"
```

---

### Task 6: 设置页自定义源 UI

**Files:**
- Modify: `templates/dashboard.html`（`renderSettings` 的 sources 循环 + 新增自定义源区块和 5 个 JS 函数）

**Interfaces:**
- Consumes: Task 5 的 4 个端点 + 现有 `GET/PUT /api/settings/sources`
- Produces: JS 函数 `saveCustomSource()`、`editCustomSource(name)`、`deleteCustomSource(name)`、`testCustomSource()`；模块级变量 `_editingSourceName`（null=新增模式）

- [ ] **Step 1: 修改 sources 列表渲染**

`renderSettings` 中 `sources.forEach(s => {...})` 的整段替换为：

```javascript
        sources.forEach(s => {
            const typeTag = s.type ? ` <span style="font-size:0.7em;background:#ede7f6;color:#5e35b1;padding:1px 6px;border-radius:8px;">${esc(s.type.toUpperCase())}</span>` : '';
            const policyTag = s.filter_policy ? ` <span style="font-size:0.7em;background:#e0f2f1;color:#00695c;padding:1px 6px;border-radius:8px;">${s.filter_policy === 'gs_only' ? '仅高盛' : '全保留'}</span>` : '';
            const actions = s.builtin ? '' :
                ` <button class="btn-sm" onclick="editCustomSource('${esc(s.name)}')">✏️ 编辑</button>` +
                ` <button class="btn-sm danger" onclick="deleteCustomSource('${esc(s.name)}')">🗑 删除</button>`;
            html += `<div class="source-row">
                <div class="info"><div class="name">${esc(s.label)}${typeTag}${policyTag} <span style="font-size:0.75em;color:#888;">(${esc(s.name)})</span></div>
                <div class="desc">${esc(s.description || s.url || '')} ${s.builtin ? '<span style="color:#888;">· 内置</span>' : '<span style="color:var(--accent);">· 自定义</span>'}</div></div>
                <div>
                <button class="toggle-btn ${s.enabled?'on':'off'}" onclick="toggleSource('${esc(s.name)}',${!s.enabled})">${s.enabled?'✅ 已启用':'⏸ 已禁用'}</button>${actions}
                </div>
            </div>`;
        });
```

- [ ] **Step 2: 新增自定义源表单区块**

`renderSettings` 中 `html += '</div>';`（信号源 section 收尾，原第 1047 行附近）之前插入：

```javascript
    // --- Custom source add/edit form ---
    html += `<div class="add-form" id="customSourceForm" style="margin-top:12px;">
        <div style="font-weight:600;margin-bottom:6px;" id="csFormTitle">➕ 添加自定义信息源</div>
        <input id="csLabel" placeholder="名称（如 财新网）">
        <input id="csName" placeholder="标识（小写英文/数字/下划线，如 caixin）">
        <select id="csType"><option value="rss">RSS 订阅</option><option disabled>网页地址（即将上线）</option><option disabled>主题搜索（即将上线）</option></select>
        <input id="csUrl" placeholder="RSS 地址（https://…）" style="flex:1;min-width:260px;">
        <label style="white-space:nowrap;"><input type="radio" name="csPolicy" value="gs_only" checked> 仅高盛相关</label>
        <label style="white-space:nowrap;"><input type="radio" name="csPolicy" value="all"> 全部保留</label>
        <button class="btn-sm" onclick="testCustomSource()">🔍 测试源</button>
        <button class="btn-sm primary" onclick="saveCustomSource()">💾 保存</button>
        <button class="btn-sm" onclick="resetCustomSourceForm()" id="csCancelBtn" style="display:none;">取消</button>
        <div id="csTestResult" style="width:100%;font-size:0.85em;color:#555;"></div>
    </div>`;
```

- [ ] **Step 3: 新增 5 个 JS 函数**

放在 `toggleSource` 函数之后：

```javascript
let _editingSourceName = null;

function _csPolicy() {
    return document.querySelector('input[name="csPolicy"]:checked').value;
}

function resetCustomSourceForm() {
    _editingSourceName = null;
    document.getElementById('csFormTitle').textContent = '➕ 添加自定义信息源';
    document.getElementById('csLabel').value = '';
    document.getElementById('csName').value = '';
    document.getElementById('csName').disabled = false;
    document.getElementById('csUrl').value = '';
    document.getElementById('csCancelBtn').style.display = 'none';
    document.getElementById('csTestResult').textContent = '';
}

async function saveCustomSource() {
    const label = document.getElementById('csLabel').value.trim();
    const url = document.getElementById('csUrl').value.trim();
    const body = {label, url, filter_policy: _csPolicy()};
    let resp;
    if (_editingSourceName) {
        resp = await fetch('/api/settings/sources/custom/' + encodeURIComponent(_editingSourceName), {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    } else {
        const name = document.getElementById('csName').value.trim();
        if (!name) { alert('请填写标识（小写英文）'); return; }
        resp = await fetch('/api/settings/sources/custom', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({...body, name})});
    }
    const data = await resp.json();
    if (!resp.ok) { alert('保存失败: ' + (data.detail || resp.status)); return; }
    resetCustomSourceForm();
    renderSettings();
    buildSourceFilters();
}

async function editCustomSource(name) {
    const sources = await (await fetch('/api/settings/sources')).json();
    const s = sources.find(x => x.name === name);
    if (!s) return;
    _editingSourceName = name;
    document.getElementById('csFormTitle').textContent = '✏️ 编辑自定义源：' + s.label;
    document.getElementById('csLabel').value = s.label;
    document.getElementById('csName').value = s.name;
    document.getElementById('csName').disabled = true;
    document.getElementById('csUrl').value = s.url || '';
    document.querySelector(`input[name="csPolicy"][value="${s.filter_policy || 'gs_only'}"]`).checked = true;
    document.getElementById('csCancelBtn').style.display = 'inline-block';
    document.getElementById('customSourceForm').scrollIntoView({behavior: 'smooth'});
}

async function deleteCustomSource(name) {
    if (!confirm('确定删除该自定义源？其历史情报保留，但不再抓取新内容。')) return;
    const resp = await fetch('/api/settings/sources/custom/' + encodeURIComponent(name), {method:'DELETE'});
    if (!resp.ok) { const e = await resp.json(); alert('删除失败: ' + e.detail); return; }
    renderSettings();
    buildSourceFilters();
}

async function testCustomSource() {
    const url = document.getElementById('csUrl').value.trim();
    const box = document.getElementById('csTestResult');
    if (!url) { box.textContent = '请先填写地址'; return; }
    box.textContent = '⏳ 正在抓取测试…';
    try {
        const resp = await fetch('/api/settings/sources/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url})});
        const data = await resp.json();
        if (!resp.ok) { box.textContent = '❌ ' + (data.detail || '请求失败'); return; }
        if (!data.ok) { box.textContent = '❌ ' + (data.error || '抓取失败'); return; }
        box.textContent = data.count > 0
            ? `✅ 抓取成功：${data.count} 条。最新示例：${data.sample_titles.join('；')}`
            : '⚠️ 地址可访问但近期 0 条内容，请确认地址是否正确';
    } catch(e) { box.textContent = '❌ 网络错误: ' + e; }
}
```

（`buildSourceFilters` 在 Task 7 定义；这里先调用无碍——Task 6 与 7 同批完成前端。）

- [ ] **Step 4: 浏览器验证**

启动本地服务 `.venv/bin/uvicorn src.web:app --port 8770`，用 browse 工具：
1. 打开设置页 → 出现"➕ 添加自定义信息源"表单
2. 填入 `测试源 / testsrc / https://dedicated.wallstreetcn.com/rss.xml / 全部保留` → 点"🔍 测试源" → 显示抓取成功和条数
3. 点"💾 保存" → 列表出现该源，带 `[RSS]` `[全保留]` 标签
4. 点"✏️ 编辑" → 表单回填 → 改名称 → 保存 → 列表更新
5. 点"🗑 删除" → 确认 → 列表移除
6. console 无报错（`browse console --errors`）

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(settings-ui): 自定义源添加/编辑/删除/测试表单"
```

---

### Task 7: 动态筛选器 + 进度面板 triage_note + 全量验证

**Files:**
- Modify: `templates/dashboard.html`（筛选器容器、`init`、`updateProgressPanel`、SSE onmessage、`srcClass`、CSS）

**Interfaces:**
- Consumes: `GET /api/settings/sources`；Task 4 的 `triage_note` SSE 事件
- Produces: JS 函数 `buildSourceFilters()`；模块级 `_sourceLabels`（name→label 映射，progress panel 共用）

- [ ] **Step 1: 筛选器改为动态生成**

`templates/dashboard.html` 第 257-262 行的 6 个硬编码 `<label>` 替换为：

```html
            <span id="sourceFilterBox">
            <label><input type="checkbox" checked onchange="onFilterChange()" class="filter-source" value="13F"> 13F 持仓</label>
            <label><input type="checkbox" checked onchange="onFilterChange()" class="filter-source" value="8-K"> SEC 8-K</label>
            <label><input type="checkbox" checked onchange="onFilterChange()" class="filter-source" value="13D/13G"> 13D/13G</label>
            <label><input type="checkbox" checked onchange="onFilterChange()" class="filter-source" value="research_view"> 高盛研究</label>
            <label><input type="checkbox" checked onchange="onFilterChange()" class="filter-source" value="news"> 新闻</label>
            <label><input type="checkbox" checked onchange="onFilterChange()" class="filter-source" value="macro_view"> 宏观指标</label>
            </span>
```

（静态默认作为加载失败兜底。）新增函数并挂入 `init`：

```javascript
let _sourceLabels = {};

async function buildSourceFilters() {
    try {
        const resp = await fetch('/api/settings/sources');
        const sources = await resp.json();
        const box = document.getElementById('sourceFilterBox');
        if (!box) return;
        const prev = new Set([...document.querySelectorAll('.filter-source:checked')].map(cb => cb.value));
        box.innerHTML = sources.map(s => {
            _sourceLabels[s.name] = s.label;
            const checked = prev.size === 0 || prev.has(s.name) ? 'checked' : '';
            return `<label><input type="checkbox" ${checked} onchange="onFilterChange()" class="filter-source" value="${esc(s.name)}"> ${esc(s.label)}</label>`;
        }).join('');
    } catch(e) { console.error('Failed to build source filters', e); }
}
```

`init()` 中 `await switchMainView('daily');` 之前插入一行：`await buildSourceFilters();`

- [ ] **Step 2: 进度面板消费 triage_note + 动态标签**

`runDailyIntel` 的 `onmessage` 中，`} else if (data.event === 'source_done') {` 分支后插入：

```javascript
            } else if (data.event === 'triage_note') {
                (sourceStates.__notes = sourceStates.__notes || []).push(data);
                updateProgressPanel(sourceStates);
```

`updateProgressPanel` 中：
- `const sourceLabels = {...}` 一行替换为：`const sourceLabels = {'8-K':'SEC 8-K 重大事件','13D/13G':'13D/13G 大动作','research_view':'高盛研究观点','news':'RSS 新闻','macro_view':'FRED 宏观', ..._sourceLabels};`
- `for (const [name, state] of Object.entries(sourceStates)) {` 循环体第一行插入：`if (name === '__notes') continue;`
- `if (isComplete && summary) {` 之前插入黄灯提示块：

```javascript
    (sourceStates.__notes || []).forEach(n => {
        html += `<div style="color:#b26a00;font-size:0.85em;padding:4px 0;">🟡 ${esc(sourceLabels[n.source] || n.source)}：${esc(n.note)}</div>`;
    });
```

- [ ] **Step 3: 自定义源标签颜色**

CSS 第 122 行 `.sig-source.src-news {...}` 之后追加：

```css
        .sig-source.src-custom { background: #ede7f6; color: #5e35b1; }
```

`srcClass` 的 `return m[source] || 'src-13F';` 改为 `return m[source] || 'src-custom';`

- [ ] **Step 4: 全量回归 + 浏览器端到端验证**

```bash
pytest -q   # 期望全部 PASS（约 230 个）
```

启动本地服务，用 browse 工具验证：
1. 每日情报页 → 左侧筛选器包含自定义源（先按 Task 6 步骤添加一个）
2. 点"手动运行每日情报" → 进度面板出现自定义源行并亮绿灯
3. console 无报错

- [ ] **Step 5: Commit + 部署**

```bash
git add templates/dashboard.html
git commit -m "feat(dashboard): 动态来源筛选器 + triage_note 黄灯提示 + 自定义源标签色"
git push origin main   # GitHub Actions 自动部署
```

---

## Self-Review 记录

- **Spec 覆盖**：数据模型校验（Task 5 `_validate_custom_payload`）、AiTriage 预算/回退（Task 3）、流水线集成与 triage_note（Task 4）、设置 UI（Task 6）、动态筛选器（Task 7）、测试源按钮（Task 5+6）、P2/P3 仅留类型枚举（Task 6 下拉置灰）—— 全覆盖
- **类型一致性**：`TriageResult(kept_indices, fallback_used, note)` 在 Task 3 定义、Task 4 消费一致；`NewsSource(rss_urls, source_name, filter_policy)` Task 1 定义、Task 4/5 使用一致；`resolve_llm_config` Task 2 定义、Task 4 使用一致
- **有意的偏差说明**：spec 中 `CustomRssSource` 独立类简化为 NewsSource 参数化（spec 允许"基类或组合"，参数化更 DRY）；`_all_rss_feeds` 移除（spec 明确要求）；内置 news 源同样过 AI 预筛（spec "预筛适用范围"明确包含）
