# P2 网页型自定义源 + 预筛效果预览 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能添加"网页地址"型信息源——httpx 抓网页正文，AI 按用户的一句话说明提取要点，走统一的"AI 预筛 → 入库"管道；同时升级"测试源"按钮，展示 AI 预筛的 keep/drop 预览。

**Architecture:** 新增 `WebpageSource`（抓取→正文提取→LLM 提取→内容哈希水印去重），复用 P1 的 `AiTriage`（提取预算计数器 `DailyBudget` 供两处使用）；流水线 `_build_daily_sources()` 增加 webpage 分支，`fetch_note` 黄灯机制接入现有 `triage_note` SSE 事件；设置 API 接受 `type`/`instruction` 字段；测试端点跑真实预筛并返回每条 keep 标记。

**Tech Stack:** Python 3.11, httpx, anthropic SDK, FastAPI, pytest, 原生 JS（dashboard.html）

**依据:** `docs/superpowers/specs/2026-07-25-custom-ai-sources-design.md` 的 P2 行（webpage 型 + 预筛效果预览）

## Global Constraints

- 所有用户可见输出用中文；代码内部（变量/注释/commit）用英文
- 不引入 Playwright/重依赖；正文提取用正则 + 现有 `clean_html_text`
- LLM max_tokens 一律 2048（思考型模型会先烧输出额度在 reasoning block 上，小了会返回空）
- 网页型源没有 AI 时**无确定性回退**（条目本身就来自 AI 提取）→ 返回空 + `fetch_note` 黄灯说明，不抛异常
- 网页 HTTP 抓取失败（403/超时）→ 抛异常 → 流水线红灯（与"单源失败隔离"模式一致）
- 预筛/提取 LLM 调用都有每日预算，计数器 key 含 UTC 日期自动跨天重置
- 任何代码进入提交前必须测试通过；现有 236 个测试保持全绿

---

### Task 1: DailyBudget 预算计数器提取

AiTriage 的预算逻辑抽成独立类，供 WebpageSource 复用（各自独立的 key 前缀，互不抢占）。

**Files:**
- Modify: `src/signals/ai_triage.py`
- Test: `tests/signals/test_ai_triage.py`

**Interfaces:**
- Produces: `DailyBudget(key_prefix: str, limit: int, get_setting, set_setting)`，方法 `used() -> int`、`exhausted() -> bool`、`increment()`；`CRITERIA`（原 `_CRITERIA` 改为公开，webpage 模块要用）

- [ ] **Step 1: 写失败测试**

在 `tests/signals/test_ai_triage.py` 末尾追加：

```python
def test_daily_budget_counts_until_exhausted():
    from src.signals.ai_triage import DailyBudget
    store, gs, ss = _store()
    budget = DailyBudget("test_count", 2, gs, ss)
    assert budget.used() == 0
    assert not budget.exhausted()
    budget.increment()
    budget.increment()
    assert budget.used() == 2
    assert budget.exhausted()


def test_daily_budget_key_contains_date():
    from src.signals.ai_triage import DailyBudget
    store, gs, ss = _store()
    budget = DailyBudget("test_count", 2, gs, ss)
    from datetime import datetime, timezone
    assert datetime.now(timezone.utc).strftime("%Y-%m-%d") in budget._key()
```

并把已有的 `test_budget_key_contains_date` 改为测新结构：

```python
@pytest.mark.asyncio
async def test_budget_key_contains_date():
    store, gs, ss = _store()
    triage = AiTriage(NO_CFG, gs, ss)
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today in triage.budget._key()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/signals/test_ai_triage.py -q`
Expected: FAIL（`DailyBudget` 不存在；`AiTriage` 无 `budget` 属性）

- [ ] **Step 3: 实现 DailyBudget + 重构 AiTriage**

`src/signals/ai_triage.py`：
1. `_CRITERIA` 改名为 `CRITERIA`（公开），`_build_prompt` 内的引用同步改
2. 新增类：

```python
class DailyBudget:
    """Daily LLM call counter persisted via settings; resets each UTC day."""

    def __init__(
        self,
        key_prefix: str,
        limit: int,
        get_setting: Callable[[str, str], str],
        set_setting: Callable[[str, str], None],
    ) -> None:
        self.key_prefix = key_prefix
        self.limit = limit
        self._get_setting = get_setting
        self._set_setting = set_setting

    def _key(self) -> str:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self.key_prefix}_{day}"

    def used(self) -> int:
        try:
            return int(self._get_setting(self._key(), "0") or "0")
        except ValueError:
            return 0

    def exhausted(self) -> bool:
        return self.used() >= self.limit

    def increment(self) -> None:
        self._set_setting(self._key(), str(self.used() + 1))
```

3. `AiTriage.__init__` 改为：

```python
    def __init__(
        self,
        llm_config: dict,
        get_setting: Callable[[str, str], str],
        set_setting: Callable[[str, str], None],
        daily_budget: int = DEFAULT_DAILY_BUDGET,
    ) -> None:
        self.llm_config = llm_config
        self.budget = DailyBudget(key_prefix="ai_triage_count", limit=daily_budget,
                                  get_setting=get_setting, set_setting=set_setting)
```

4. 删除 `_budget_key` / `_calls_used_today` / `_increment_calls` 三个方法；`triage()` 内 `self._calls_used_today() >= self.daily_budget` 改为 `self.budget.exhausted()`，`self._increment_calls()` 改为 `self.budget.increment()`

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/signals/test_ai_triage.py -q`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/signals/ai_triage.py tests/signals/test_ai_triage.py
git commit -m "refactor(triage): extract DailyBudget for reuse by webpage sources"
```

---

### Task 2: WebpageSource 核心

**Files:**
- Create: `src/signals/webpage_source.py`
- Test: `tests/signals/test_webpage_source.py`

**Interfaces:**
- Consumes: `DailyBudget`, `CRITERIA`（Task 1）；`clean_html_text`（`src/signals/news_source.py`）；`Signal`/`SignalStrength`（`src/signals/base.py`）
- Produces: `WebpageSource(url, instruction, source_name, filter_policy="gs_only", llm_config=None, get_setting, set_setting, daily_budget=10, recent_titles=None)`，方法 `fetch_since(watermark) -> (list[Signal], str|None)`、`fetch(quarter)`、`close()`；属性 `fetch_note: str`（AI 降级原因，流水线读它发黄灯）；`extract_text(html) -> str`

行为要点：
- 水印 = 正文 SHA1：未变化 → `([], None)`，不调用 LLM；变化才提取
- 提取失败（无配置/预算尽/LLM 报错/JSON 乱）→ `([], None)` + `fetch_note`（水印不推进，下轮重试）
- 页面变了但没有符合内容 → `([], new_hash)`（水印推进，无 note）
- `recent_titles(source_name) -> set[str]`：注入的近期标题集合，跨天去重（指纹含日期，单靠指纹无法跨天去重）
- gs_only → MEDIUM；all → LOW；url = 页面地址；published_at = now

- [ ] **Step 1: 写失败测试**

创建 `tests/signals/test_webpage_source.py`：

```python
"""Tests for src.signals.webpage_source."""
import httpx
import pytest

from src.signals.webpage_source import WebpageSource, extract_text

LLM_CFG = {"api_key": None, "auth_token": "tok", "base_url": "https://x.test", "model": "m"}
NO_CFG = {"api_key": None, "auth_token": None, "base_url": None, "model": "m"}
PAGE = """
<html><head><style>body{color:red}</style><script>var x=1;</script></head>
<body><h1>高盛看好中国市场</h1><p>高盛研报指出A股估值有吸引力。</p></body></html>
"""


def _store():
    store = {}
    return store, (lambda k, d="": store.get(k, d)), (lambda k, v: store.__setitem__(k, v))


def _mock_page(source, html=PAGE, status=200):
    def handler(request):
        return httpx.Response(status, text=html)
    source._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


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


def _patch_llm(monkeypatch, responses):
    client = _FakeClient(responses)
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: client)
    return client


def _make_source(monkeypatch, responses, **kwargs):
    _patch_llm(monkeypatch, responses)
    store, gs, ss = _store()
    kwargs.setdefault("llm_config", LLM_CFG)
    kwargs.setdefault("get_setting", gs)
    kwargs.setdefault("set_setting", ss)
    src = WebpageSource(**kwargs)
    _mock_page(src)
    return src


def test_extract_text_strips_scripts_and_tags():
    text = extract_text(PAGE)
    assert "高盛看好中国市场" in text
    assert "var x" not in text
    assert "color:red" not in text
    assert "<" not in text


@pytest.mark.asyncio
async def test_first_fetch_extracts_items_and_sets_watermark(monkeypatch):
    src = _make_source(monkeypatch, ['{"items": [{"title": "高盛看好A股", "summary": "估值有吸引力"}]}'],
                       url="https://x.test/p", instruction="提取高盛观点", source_name="gs_page")
    signals, wm = await src.fetch_since(None)
    assert len(signals) == 1
    assert signals[0].title == "高盛看好A股"
    assert signals[0].source == "gs_page"
    assert signals[0].url == "https://x.test/p"
    assert signals[0].strength.value == "medium"  # gs_only default
    assert wm
    await src.close()


@pytest.mark.asyncio
async def test_unchanged_page_skips_llm(monkeypatch):
    src = _make_source(monkeypatch, ['{"items": []}'],
                       url="https://x.test/p", instruction="x", source_name="p")
    _signals, wm = await src.fetch_since(None)
    signals2, wm2 = await src.fetch_since(wm)
    assert signals2 == [] and wm2 is None
    assert src._llm_client.calls == 1  # second fetch made no LLM call
    await src.close()


@pytest.mark.asyncio
async def test_all_policy_strength_low(monkeypatch):
    src = _make_source(monkeypatch, ['{"items": [{"title": "t", "summary": "s"}]}'],
                       url="https://x.test/p", instruction="x", source_name="p",
                       filter_policy="all")
    signals, _ = await src.fetch_since(None)
    assert signals[0].strength.value == "low"
    await src.close()


@pytest.mark.asyncio
async def test_no_llm_config_degrades_with_note():
    store, gs, ss = _store()
    src = WebpageSource(url="https://x.test/p", instruction="x", source_name="p",
                        llm_config=NO_CFG, get_setting=gs, set_setting=ss)
    _mock_page(src)
    signals, wm = await src.fetch_since(None)
    assert signals == [] and wm is None
    assert "大模型" in src.fetch_note
    await src.close()


@pytest.mark.asyncio
async def test_llm_error_degrades_with_note(monkeypatch):
    class _Fail:
        def __init__(self, **kw):
            self.messages = self._M()

        class _M:
            async def create(self, **kw):
                raise RuntimeError("gateway down")

    monkeypatch.setattr("anthropic.AsyncAnthropic", _Fail)
    store, gs, ss = _store()
    src = WebpageSource(url="https://x.test/p", instruction="x", source_name="p",
                        llm_config=LLM_CFG, get_setting=gs, set_setting=ss)
    _mock_page(src)
    signals, wm = await src.fetch_since(None)
    assert signals == [] and wm is None
    assert src.fetch_note
    await src.close()


@pytest.mark.asyncio
async def test_unparseable_llm_output_degrades(monkeypatch):
    src = _make_source(monkeypatch, ["我想说几句"],
                       url="https://x.test/p", instruction="x", source_name="p")
    signals, wm = await src.fetch_since(None)
    assert signals == [] and wm is None
    assert "格式" in src.fetch_note
    await src.close()


@pytest.mark.asyncio
async def test_budget_exhausted_skips_llm(monkeypatch):
    src = _make_source(monkeypatch, ['{"items": []}'],
                       url="https://x.test/p", instruction="x", source_name="p",
                       daily_budget=0)
    signals, wm = await src.fetch_since(None)
    assert signals == [] and wm is None
    assert src._llm_client.calls == 0
    assert "预算" in src.fetch_note
    await src.close()


@pytest.mark.asyncio
async def test_http_error_raises():
    store, gs, ss = _store()
    src = WebpageSource(url="https://x.test/p", instruction="x", source_name="p",
                        llm_config=LLM_CFG, get_setting=gs, set_setting=ss)
    _mock_page(src, status=403)
    with pytest.raises(httpx.HTTPStatusError):
        await src.fetch_since(None)
    await src.close()


@pytest.mark.asyncio
async def test_recent_titles_filtered(monkeypatch):
    src = _make_source(monkeypatch, ['{"items": [{"title": "旧闻", "summary": "s"}, {"title": "新闻", "summary": "s2"}]}'],
                       url="https://x.test/p", instruction="x", source_name="p",
                       recent_titles=lambda name: {"旧闻"})
    signals, _ = await src.fetch_since(None)
    assert [s.title for s in signals] == ["新闻"]
    await src.close()
```

注意：测试里引用 `src._llm_client.calls` 统计 LLM 调用次数——实现时把 `anthropic.AsyncAnthropic` 实例缓存为 `self._llm_client`（懒创建）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/signals/test_webpage_source.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 WebpageSource**

创建 `src/signals/webpage_source.py`：

```python
"""Webpage-type custom source: fetch a page, extract its text, and let the
LLM pull out intelligence items guided by the user's instruction.

There is NO deterministic fallback without the LLM (the items originate from
the extraction itself), so AI failures degrade to "no items + fetch_note" —
the pipeline surfaces fetch_note as a yellow triage_note SSE event. HTTP
fetch errors raise, so the pipeline marks the source red (fault isolation
keeps other sources running).

Watermark = SHA1 of the extracted page text: an unchanged page short-circuits
before any LLM call. A changed page with no matching items still advances the
watermark (nothing to retry). AI degradation does NOT advance it.
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

import httpx

from src.signals.ai_triage import CRITERIA, DailyBudget
from src.signals.base import Signal, SignalStrength
from src.signals.news_source import clean_html_text

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 6000
MAX_ITEMS = 10
DEFAULT_DAILY_BUDGET = 10

_UA = {"User-Agent": "GS-Tracker/1.0 (market research; contact: admin@gs-tracker.local)"}
_SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)


def extract_text(html: str) -> str:
    """Strip script/style/noscript blocks, then tags; cap the length."""
    no_scripts = _SCRIPT_RE.sub(" ", html)
    return clean_html_text(no_scripts)[:MAX_TEXT_CHARS]


def _parse_items(text: str) -> Optional[list]:
    """Extract the items array from model output; None if unparseable."""
    match = re.search(r'"items"\s*:\s*(\[.*\])', text, re.S)
    if not match:
        return None
    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(items, list):
        return None
    result = []
    for it in items[:MAX_ITEMS]:
        if isinstance(it, dict) and it.get("title"):
            result.append({
                "title": str(it["title"]).strip()[:120],
                "summary": str(it.get("summary") or "").strip()[:300],
            })
    return result


class WebpageSource:
    """One webpage + one user instruction → AI-extracted signals."""

    def __init__(
        self,
        url: str,
        instruction: str,
        source_name: str,
        filter_policy: str = "gs_only",
        llm_config: Optional[dict] = None,
        get_setting: Callable[[str, str], str] = lambda k, d="": d,
        set_setting: Callable[[str, str], None] = lambda k, v: None,
        daily_budget: int = DEFAULT_DAILY_BUDGET,
        recent_titles: Optional[Callable[[str], set]] = None,
    ) -> None:
        self.url = url
        self.instruction = instruction
        self.source_name = source_name
        self.filter_policy = filter_policy
        self.llm_config = llm_config or {}
        self.budget = DailyBudget("ai_webpage_count", daily_budget, get_setting, set_setting)
        self._recent_titles = recent_titles or (lambda name: set())
        self.fetch_note = ""  # AI degradation reason; read by the pipeline
        self._client = httpx.AsyncClient(timeout=30.0, headers=_UA, follow_redirects=True)
        self._llm_client = None  # lazy anthropic.AsyncAnthropic

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self, quarter: str) -> List[Signal]:
        signals, _ = await self.fetch_since(None)
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        self.fetch_note = ""
        resp = await self._client.get(self.url)
        resp.raise_for_status()
        text = extract_text(resp.text)
        if not text:
            return [], None
        page_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()
        if page_hash == watermark:
            return [], None  # page unchanged since last run

        items = await self._extract_items(text)
        if items is None:
            return [], None  # AI degraded (fetch_note set); retry next run
        seen = self._recent_titles(self.source_name)
        items = [it for it in items if it["title"] not in seen]
        if not items:
            return [], page_hash  # changed, but nothing (new) to keep

        strength = (
            SignalStrength.MEDIUM if self.filter_policy == "gs_only"
            else SignalStrength.LOW
        )
        now = datetime.now(timezone.utc)
        signals = [
            Signal(
                title=it["title"],
                source=self.source_name,
                published_at=now,
                summary=it["summary"],
                companies=[],
                strength=strength,
                url=self.url,
            )
            for it in items
        ]
        return signals, page_hash

    def _build_prompt(self, text: str) -> str:
        criteria = CRITERIA.get(self.filter_policy, CRITERIA["gs_only"])
        return (
            "你是投资情报提取助手。用户是中国 A 股个人投资者，关注高盛观点以判断市场趋势。\n\n"
            f"网页地址：{self.url}\n"
            f"用户提取要求：{self.instruction}\n"
            f"筛选标准：{criteria}\n\n"
            f"网页正文（已截断）：\n{text}\n\n"
            '只输出 JSON，不要输出其他内容：{"items": [{"title": "要点标题", "summary": "150字内摘要"}]}，'
            f"最多 {MAX_ITEMS} 条；没有符合要求的内容则输出空数组。"
        )

    def _get_llm_client(self):
        if self._llm_client is None:
            import anthropic

            self._llm_client = anthropic.AsyncAnthropic(
                api_key=self.llm_config.get("api_key"),
                auth_token=self.llm_config.get("auth_token"),
                base_url=self.llm_config.get("base_url"),
                timeout=60.0,
            )
        return self._llm_client

    async def _extract_items(self, text: str) -> Optional[list]:
        """LLM extraction; None means degraded (fetch_note explains)."""
        if not (self.llm_config.get("api_key") or self.llm_config.get("auth_token")):
            self.fetch_note = "未配置大模型，网页型源无法提取内容"
            return None
        if self.budget.exhausted():
            self.fetch_note = "网页提取 AI 预算已用完，明日自动恢复"
            return None
        try:
            resp = await self._get_llm_client().messages.create(
                model=self.llm_config["model"],
                max_tokens=2048,  # thinking-block models burn budget on reasoning first
                messages=[{"role": "user", "content": self._build_prompt(text)}],
            )
            self.budget.increment()
        except Exception as exc:
            logger.warning("Webpage extraction failed for %s: %s", self.source_name, exc)
            self.fetch_note = "AI 提取失败，本次跳过该网页"
            return None
        out = "".join(b.text for b in resp.content if hasattr(b, "text"))
        items = _parse_items(out)
        if items is None:
            logger.warning("Webpage extraction unparseable for %s: %.200s", self.source_name, out)
            self.fetch_note = "AI 返回格式异常，本次跳过该网页"
        return items
```

注意 `test_unchanged_page_skips_llm` / `test_budget_exhausted_skips_llm` 检查 `src._llm_client.calls`：`_make_source` 里 `_patch_llm` 把 `anthropic.AsyncAnthropic` 换成 lambda 返回 fake client，懒创建后 `self._llm_client` 就是那个 fake。无 LLM 调用时 `self._llm_client is None`——测试里断言前先确认非 None（`test_budget_exhausted_skips_llm` 中预算尽时不会创建 client，断言改为 `assert src._llm_client is None or src._llm_client.calls == 0`）。

修正 Step 1 中两处断言：
- `test_unchanged_page_skips_llm`：`assert src._llm_client.calls == 1`
- `test_budget_exhausted_skips_llm`：`assert src._llm_client is None or src._llm_client.calls == 0`

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/signals/test_webpage_source.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/signals/webpage_source.py tests/signals/test_webpage_source.py
git commit -m "feat(sources): WebpageSource — httpx page fetch + LLM extraction per user instruction"
```

---

### Task 3: 流水线集成

**Files:**
- Modify: `src/main.py`（`_build_daily_sources`、`_fetch_one`、as_completed 循环）
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `WebpageSource`（Task 2）
- Produces: SSE 事件不变；`_fetch_one` 返回 `(name, signals, note)` 三元组（note 来自 `src.fetch_note`，非空时循环里补发 `triage_note` 事件）

- [ ] **Step 1: 写失败测试**

`tests/test_main.py` 追加（参照已有 `_default_settings` / `_mock_sources` fixture 风格）：

```python
def test_build_daily_sources_includes_webpage(monkeypatch):
    """webpage-type custom entries become WebpageSource instances."""
    import json as _json
    from src.signals.webpage_source import WebpageSource

    entries = [{
        "name": "gs_insights", "label": "高盛观点页", "type": "webpage",
        "url": "https://example.com/insights", "instruction": "提取高盛观点",
        "filter_policy": "gs_only", "enabled": True, "builtin": False,
    }]
    monkeypatch.setattr(
        "src.main.get_setting",
        lambda k, d="": _json.dumps(entries, ensure_ascii=False) if k == "sources_config" else d,
    )
    monkeypatch.setattr("src.main.get_default_llm_model", lambda: None)
    sources = dict(main._build_daily_sources())
    assert isinstance(sources["gs_insights"], WebpageSource)
    assert sources["gs_insights"].instruction == "提取高盛观点"
    assert sources["gs_insights"].filter_policy == "gs_only"


@pytest.mark.asyncio
async def test_stream_emits_triage_note_from_fetch_note(monkeypatch):
    """A source's fetch_note surfaces as a yellow triage_note SSE event."""
    class _NoteSource:
        source_name = "gs_page"
        fetch_note = ""

        async def fetch_since(self, watermark=None):
            self.fetch_note = "网页提取 AI 预算已用完，明日自动恢复"
            return [], None

        async def close(self):
            pass

    monkeypatch.setattr(main, "_build_daily_sources", lambda: [("gs_page", _NoteSource())])
    monkeypatch.setattr(main, "get_recent_signals", lambda days=30: [])
    monkeypatch.setattr(main, "save_signals_incremental", lambda q, s: None)
    monkeypatch.setattr(main, "save_signal_run", lambda *a, **kw: None)
    monkeypatch.setattr(main, "cleanup_expired_signals", lambda days: None)
    monkeypatch.setattr(main, "init_db", lambda: None)
    monkeypatch.setattr(main, "ensure_directories", lambda: None)

    events = [json.loads(e) async for e in main.run_daily_intel_stream()]
    notes = [e for e in events if e.get("event") == "triage_note"]
    assert any(n["source"] == "gs_page" and "预算" in n["note"] for n in notes)
```

（文件顶部需有 `import json`、`from src import main`、`import pytest`——按现有 import 情况补齐。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_main.py -q`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**

`src/main.py`：

1. 顶部 import 增加：`from src.signals.webpage_source import WebpageSource`
2. `_build_daily_sources()` 的自定义源循环改为：

```python
    # Custom sources from the settings page (one instance per source)
    for entry in _custom_source_configs():
        if entry.get("name") not in enabled or not entry.get("url"):
            continue
        if entry.get("type") == "rss":
            sources.append((
                entry["name"],
                NewsSource(
                    rss_urls=[entry["url"]],
                    source_name=entry["name"],
                    filter_policy=entry.get("filter_policy", "gs_only"),
                ),
            ))
        elif entry.get("type") == "webpage":
            sources.append((
                entry["name"],
                WebpageSource(
                    url=entry["url"],
                    instruction=entry.get("instruction", ""),
                    source_name=entry["name"],
                    filter_policy=entry.get("filter_policy", "gs_only"),
                    llm_config=resolve_llm_config(get_default_llm_model()),
                    get_setting=get_setting,
                    set_setting=set_setting,
                    recent_titles=lambda name: {
                        s.title for s in get_recent_signals(days=30) if s.source == name
                    },
                ),
            ))
```

3. `_fetch_one` 返回三元组并带上 note：

```python
    async def _fetch_one(name: str, src: object) -> tuple[str, list[Signal], str]:
        try:
            if hasattr(src, "fetch_since"):
                wm = get_source_state(name, "default") if name != "8-K" else None
                result, new_wm = await src.fetch_since(watermark=wm)
                if new_wm and new_wm != wm:
                    save_source_state(name, "default", new_wm)
                source_status[name] = "ok"
                return name, result, getattr(src, "fetch_note", "")
            else:
                result = await src.fetch("")
                source_status[name] = "ok"
                return name, result, getattr(src, "fetch_note", "")
        except Exception as exc:
            logger.exception("%s source failed in daily intel", name)
            errors.append(f"{name}: {exc}")
            source_status[name] = "error"
            return name, [], ""
```

4. as_completed 循环解包三元组，`source_done` 之后补发 note：

```python
    for fut in asyncio.as_completed(tasks):
        name, sigs, note = await fut
        new_signals.extend(sigs)
        status = source_status.get(name, "ok")
        yield json.dumps({
            "event": "source_done",
            "source": name,
            "status": status,
            "count": len(sigs),
            "error": errors[-1] if status == "error" and errors else "",
        })
        if note:
            yield json.dumps({"event": "triage_note", "source": name, "note": note})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_main.py -q`
Expected: 全绿（含 P1 的自定义 RSS 源测试）

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(pipeline): wire webpage sources into daily intel + fetch_note yellow SSE"
```

---

### Task 4: 设置 API — type/instruction + 测试预览

**Files:**
- Modify: `src/web.py`（`_validate_custom_payload`、POST/PUT custom、test 端点）
- Test: `tests/test_web.py`

**Interfaces:**
- POST/PUT 接受 `type`（`rss`|`webpage`，默认 `rss`）与 `instruction`（webpage 必填，≤100 字）
- 测试端点请求增加 `type`/`filter_policy`/`instruction`；响应增加 `items: [{title, kept}]`、`ai_used: bool`、可选 `note: str`（保留旧字段 `ok/count/sample_titles/error`）

- [ ] **Step 1: 写失败测试**

`tests/test_web.py` 追加：

```python
def test_webpage_source_crud(signals_db):
    payload = _custom_payload(name="gs_page", type="webpage", instruction="提取高盛观点")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201

    sources = client.get("/api/settings/sources").json()
    entry = [s for s in sources if s["name"] == "gs_page"][0]
    assert entry["type"] == "webpage"
    assert entry["instruction"] == "提取高盛观点"

    resp = client.put("/api/settings/sources/custom/gs_page", json={"instruction": "提取目标价"})
    assert resp.status_code == 200
    entry = [s for s in client.get("/api/settings/sources").json() if s["name"] == "gs_page"][0]
    assert entry["instruction"] == "提取目标价"


def test_webpage_source_requires_instruction(signals_db):
    resp = client.post(
        "/api/settings/sources/custom",
        json=_custom_payload(type="webpage", instruction=""),
    )
    assert resp.status_code == 422


def test_webpage_edit_cannot_drop_instruction(signals_db):
    payload = _custom_payload(name="wp", type="webpage", instruction="提取要点")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201
    resp = client.put("/api/settings/sources/custom/wp", json={"instruction": "  "})
    assert resp.status_code == 422


def test_bad_source_type_rejected(signals_db):
    resp = client.post("/api/settings/sources/custom", json=_custom_payload(type="topic"))
    assert resp.status_code == 422


def test_test_source_webpage_preview(signals_db, monkeypatch, make_signal):
    """Webpage test runs extraction + AI triage preview with per-item keep flags."""
    class _FakeWebSource:
        def __init__(self, **kwargs):
            self.fetch_note = ""

        async def fetch(self, quarter):
            return [make_signal(id="w1", title="要点一"), make_signal(id="w2", title="要点二")]

        async def close(self):
            pass

    class _FakeTriage:
        def __init__(self, *a, **kw):
            pass

        async def triage(self, items, label, policy):
            from src.signals.ai_triage import TriageResult
            return TriageResult(kept_indices=[0], fallback_used=False, note="")

    monkeypatch.setattr("src.signals.webpage_source.WebpageSource", _FakeWebSource)
    monkeypatch.setattr("src.web.AiTriage", _FakeTriage)
    monkeypatch.setattr("src.web.resolve_llm_config",
                        lambda m: {"api_key": None, "auth_token": "t", "base_url": "u", "model": "m"})

    resp = client.post("/api/settings/sources/test", json={
        "url": "https://example.com/page", "type": "webpage", "instruction": "提取要点",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["ai_used"] is True
    assert data["items"] == [{"title": "要点一", "kept": True}, {"title": "要点二", "kept": False}]


def test_test_source_webpage_requires_instruction(signals_db):
    resp = client.post("/api/settings/sources/test",
                       json={"url": "https://example.com/p", "type": "webpage"})
    assert resp.status_code == 422
```

同时把已有 `test_test_source_endpoint` 的断言扩展（RSS 默认无 LLM 配置 → items 全 kept、ai_used False）：

```python
    assert data["items"] == [{"title": "标题一", "kept": True}, {"title": "标题二", "kept": True}]
    assert data["ai_used"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_web.py -q -k "custom or test_source"`
Expected: 新测试 FAIL

- [ ] **Step 3: 实现**

`src/web.py`：

1. 顶部确认/补充 import：`from src.llm_config import resolve_llm_config`、`from src.signals.ai_triage import AiTriage`（`get_default_llm_model` 已存在）
2. `_validate_custom_payload` 改为返回六元组：

```python
def _validate_custom_payload(config: dict) -> tuple:
    """Return (name, label, url, filter_policy, source_type, instruction) or raise 422."""
    name = (config.get("name") or "").strip()
    label = (config.get("label") or "").strip()
    url = (config.get("url") or "").strip()
    filter_policy = config.get("filter_policy") or "gs_only"
    source_type = config.get("type") or "rss"
    instruction = (config.get("instruction") or "").strip()
    if not name or not _CUSTOM_NAME_RE.match(name):
        raise HTTPException(status_code=422, detail="标识 name 必填，仅限小写字母/数字/下划线")
    if not label or len(label) > 30:
        raise HTTPException(status_code=422, detail="名称 label 必填且不超过 30 字")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
    if filter_policy not in ("gs_only", "all"):
        raise HTTPException(status_code=422, detail="filter_policy 必须是 gs_only 或 all")
    if source_type not in ("rss", "webpage"):
        raise HTTPException(status_code=422, detail="type 必须是 rss 或 webpage")
    if source_type == "webpage" and not instruction:
        raise HTTPException(status_code=422, detail="网页型源必须填写提取说明")
    if len(instruction) > 100:
        raise HTTPException(status_code=422, detail="提取说明不超过 100 字")
    return name, label, url, filter_policy, source_type, instruction
```

3. POST 端点：

```python
    name, label, url, filter_policy, source_type, instruction = _validate_custom_payload(config)
    ...
    sources.append({
        "name": name,
        "label": label,
        "type": source_type,
        "url": url,
        "filter_policy": filter_policy,
        "instruction": instruction,
        "enabled": True,
        "builtin": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
```

4. PUT 端点在 `enabled` 分支后追加，并在所有更新后做一致性校验：

```python
    if "type" in config:
        if config["type"] not in ("rss", "webpage"):
            raise HTTPException(status_code=422, detail="type 必须是 rss 或 webpage")
        entry["type"] = config["type"]
    if "instruction" in config:
        instruction = (config.get("instruction") or "").strip()
        if len(instruction) > 100:
            raise HTTPException(status_code=422, detail="提取说明不超过 100 字")
        entry["instruction"] = instruction
    if entry.get("type") == "webpage" and not (entry.get("instruction") or "").strip():
        raise HTTPException(status_code=422, detail="网页型源必须填写提取说明")
```

（注意：一致性校验要在写库之前——把校验放在 `set_setting` 调用前。）

5. 测试端点整体替换：

```python
@app.post("/api/settings/sources/test")
async def api_test_source(config: dict = Body(...)) -> dict:
    """Fetch a candidate source once, then preview AI triage keep/drop.
    Nothing persisted. Triage preview consumes the normal daily budget."""
    url = (config.get("url") or "").strip()
    source_type = config.get("type") or "rss"
    filter_policy = config.get("filter_policy") or "gs_only"
    instruction = (config.get("instruction") or "").strip()
    label = (config.get("label") or "").strip() or url
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
    if source_type not in ("rss", "webpage"):
        raise HTTPException(status_code=422, detail="type 必须是 rss 或 webpage")

    if source_type == "webpage":
        if not instruction:
            raise HTTPException(status_code=422, detail="网页型源必须填写提取说明")
        from src.signals.webpage_source import WebpageSource

        source = WebpageSource(
            url=url, instruction=instruction, source_name="_test",
            filter_policy=filter_policy,
            llm_config=resolve_llm_config(get_default_llm_model()),
            get_setting=get_setting, set_setting=set_setting,
        )
    else:
        from src.signals.news_source import NewsSource

        source = NewsSource(rss_urls=[url], source_name="_test", filter_policy=filter_policy)

    try:
        signals = await source.fetch("")
        result = {
            "ok": True,
            "count": len(signals),
            "sample_titles": [s.title for s in signals[:3]],
            "ai_used": False,
            "items": [{"title": s.title, "kept": True} for s in signals[:20]],
        }
        note = getattr(source, "fetch_note", "")
        if note:
            result["note"] = note
            return result
        items = [{"title": s.title, "summary": s.summary} for s in signals[:20]]
        if not items:
            return result
        llm_cfg = resolve_llm_config(get_default_llm_model())
        if not (llm_cfg.get("api_key") or llm_cfg.get("auth_token")):
            result["note"] = "未配置大模型，未预览 AI 预筛"
            return result
        triage = AiTriage(llm_cfg, get_setting, set_setting)
        verdict = await triage.triage(items, label, filter_policy)
        kept_set = set(verdict.kept_indices)
        result["items"] = [
            {"title": it["title"], "kept": i in kept_set}
            for i, it in enumerate(items)
        ]
        result["ai_used"] = not verdict.fallback_used
        if verdict.fallback_used:
            result["note"] = verdict.note
        return result
    except HTTPException:
        raise
    except Exception as exc:
        return {"ok": False, "error": f"抓取失败：{exc}"}
    finally:
        await source.close()
```

行为变化说明：RSS 测试现在按**真实 filter_policy** 抓取（gs_only 会先关键词预筛），更贴近流水线真实行为。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add src/web.py tests/test_web.py
git commit -m "feat(settings-api): webpage type + instruction field + AI triage preview in source test"
```

---

### Task 5: 设置页 UI

**Files:**
- Modify: `templates/dashboard.html`（表单、列表标签、JS 函数）

**Interfaces:**
- Consumes: Task 4 的 API 形状

- [ ] **Step 1: 表单改造**

`renderSettings()` 里 `#customSourceForm` 的 HTML 改为：

```html
    html += `<div class="add-form" id="customSourceForm" style="margin-top:12px;">
        <div style="font-weight:600;margin-bottom:6px;" id="csFormTitle">➕ 添加自定义信息源</div>
        <input id="csLabel" placeholder="名称（如 高盛研报页）">
        <input id="csName" placeholder="标识（小写英文/数字/下划线，如 gs_insights）">
        <select id="csType" onchange="onCsTypeChange()"><option value="rss">RSS 订阅</option><option value="webpage">网页地址</option><option disabled>主题搜索（即将上线）</option></select>
        <input id="csUrl" placeholder="地址（https://…）" style="flex:1;min-width:260px;">
        <input id="csInstruction" placeholder="提取说明（如：提取页面中高盛的市场观点与目标价）" style="flex:1;min-width:260px;display:none;">
        <label style="white-space:nowrap;"><input type="radio" name="csPolicy" value="gs_only" checked> 仅高盛相关</label>
        <label style="white-space:nowrap;"><input type="radio" name="csPolicy" value="all"> 全部保留</label>
        <button class="btn-sm" onclick="testCustomSource()">🔍 测试源</button>
        <button class="btn-sm primary" onclick="saveCustomSource()">💾 保存</button>
        <button class="btn-sm" onclick="resetCustomSourceForm()" id="csCancelBtn" style="display:none;">取消</button>
        <div id="csTestResult" style="width:100%;font-size:0.85em;color:#555;"></div>
    </div>`;
```

类型标签中文化（列表渲染处，约 line 1069）：

```js
const typeTag = s.type ? ` <span style="font-size:0.7em;background:#ede7f6;color:#5e35b1;padding:1px 6px;border-radius:8px;">${({rss:'RSS',webpage:'网页'})[s.type] || esc(s.type)}</span>` : '';
```

- [ ] **Step 2: JS 函数更新**

```js
function onCsTypeChange() {
    const isWeb = document.getElementById('csType').value === 'webpage';
    document.getElementById('csInstruction').style.display = isWeb ? '' : 'none';
}

function resetCustomSourceForm() {
    _editingSourceName = null;
    document.getElementById('csFormTitle').textContent = '➕ 添加自定义信息源';
    document.getElementById('csLabel').value = '';
    document.getElementById('csName').value = '';
    document.getElementById('csName').disabled = false;
    document.getElementById('csType').value = 'rss';
    document.getElementById('csUrl').value = '';
    document.getElementById('csInstruction').value = '';
    document.getElementById('csCancelBtn').style.display = 'none';
    document.getElementById('csTestResult').textContent = '';
    onCsTypeChange();
}
```

`saveCustomSource()` 的 body 改为：

```js
    const body = {
        label, url,
        type: document.getElementById('csType').value,
        instruction: document.getElementById('csInstruction').value.trim(),
        filter_policy: _csPolicy(),
    };
```

`editCustomSource()` 追加：

```js
    document.getElementById('csType').value = s.type || 'rss';
    document.getElementById('csInstruction').value = s.instruction || '';
    onCsTypeChange();
```

`testCustomSource()` 整体替换：

```js
async function testCustomSource() {
    const url = document.getElementById('csUrl').value.trim();
    const box = document.getElementById('csTestResult');
    if (!url) { box.textContent = '请先填写地址'; return; }
    const body = {
        url,
        type: document.getElementById('csType').value,
        instruction: document.getElementById('csInstruction').value.trim(),
        filter_policy: _csPolicy(),
        label: document.getElementById('csLabel').value.trim(),
    };
    box.textContent = '⏳ 正在抓取并预览 AI 预筛…';
    try {
        const resp = await fetch('/api/settings/sources/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
        const data = await resp.json();
        if (!resp.ok) { box.textContent = '❌ ' + (data.detail || '请求失败'); return; }
        if (!data.ok) { box.textContent = '❌ ' + (data.error || '抓取失败'); return; }
        if (data.count === 0) {
            box.textContent = '⚠️ 地址可访问但没有符合条件的内容' + (data.note ? `（${data.note}）` : '，请确认地址和策略是否正确');
            return;
        }
        const kept = (data.items || []).filter(i => i.kept).length;
        let head = `✅ 抓取 ${data.count} 条`;
        head += data.ai_used ? `，AI 预筛保留 ${kept} 条` : '';
        if (data.note) head += `（${data.note}）`;
        const lines = (data.items || []).map(i => `${i.kept ? '✅' : '❌'} ${esc(i.title)}`).join('<br>');
        box.innerHTML = esc(head) + '<br>' + lines;
    } catch(e) { box.textContent = '❌ 网络错误: ' + e; }
}
```

- [ ] **Step 3: 浏览器验证**

本地启动 `uvicorn src.web:app --port 8770`，用 browse 工具：
1. 设置页 → 类型选"网页地址" → 提取说明输入框出现
2. 填高盛 insights 页或其他可访问页面 + 说明 → 🔍 测试源 → 显示每条 ✅/❌ 预览
3. 保存 → 列表出现 [网页] 标签 → 编辑回填正确 → 删除
4. RSS 源回归：类型切回 RSS，说明框隐藏，保存正常

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(settings-ui): webpage type + instruction field + AI keep/drop preview"
```

---

### Task 6: 全量回归 + e2e + 部署

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/pytest -q`
Expected: 246+ passed（236 现有 + 本计划新增）

- [ ] **Step 2: 本地 e2e**

真机跑一个真实网页源（如某可访问的财经页面），验证：抓取→提取→预筛→入库全链路 + SSE 事件序列 + 再跑一遍水印去重（第二次 0 条、无 LLM 调用）。

- [ ] **Step 3: 更新 spec 阶段表**

`docs/superpowers/specs/2026-07-25-custom-ai-sources-design.md` 阶段划分表 P2 行状态改为"已实施（2026-07-25）"。

- [ ] **Step 4: 部署**

```bash
git push origin main
gh run list --limit 1   # 等 completed + success
curl -s -o /dev/null -w "%{http_code}" http://111.228.23.109/api/health   # 401 = 在线
```
