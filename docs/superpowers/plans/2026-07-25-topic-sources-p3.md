# P3 主题搜索型自定义源 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能添加"主题搜索"型信息源——只给一句主题（如"高盛对中国股市的最新观点"），AI 每天用网关 web_search 工具自行搜索、整理出条目，走统一的"AI 预筛 → 入库"管道。

**Architecture:** 新增 `TopicSource`（LLM + web_search 工具调用 → JSON items → Signal），镜像 P2 `WebpageSource` 的降级/预算/`fetch_note` 模式；无页面水印（搜索天然是增量的），去重靠 P2 的 `recent_titles` 注入；设置 API 放开 topic 型的 url 必填限制；UI 按类型切换 URL/说明输入框。

**Tech Stack:** Python 3.11, anthropic SDK（web_search_20250305 server tool）, FastAPI, pytest, 原生 JS

**依据:** `docs/superpowers/specs/2026-07-25-custom-ai-sources-design.md` 的 P3 行（topic 型：AI 按主题自行搜索整理）

**已验证的技术前提**（2026-07-25 实测）:
- Kimi 网关支持 `web_search_20250305` server tool（server_tool_use / web_search_tool_result blocks 正常返回）
- max_tokens=8192 + max_uses=3 时模型能完成多轮搜索并输出干净 JSON `{"items": [...]}`，条目带真实来源 URL，质量高

## Global Constraints

- 所有用户可见输出用中文；代码内部（变量/注释/commit）用英文
- max_tokens=8192（web_search 多轮很烧 token，小了会在搜索中途截断）
- 主题源**无水印**：每次运行都搜索；成本控制靠每日预算（LLM 调用计，默认 10 次/天，key `ai_topic_count_YYYY-MM-DD`）+ 每次运行 max_uses=3 次搜索上限
- 跨天去重靠 `recent_titles`（与 P2 相同；指纹含日期，单靠指纹无法跨天去重）
- AI 不可用/预算尽/JSON 乱 → `fetch_note` 黄灯，不抛异常（主题源无确定性回退）
- type=topic 时 url 字段可空；非空仍须 http(s)
- 现有 256 个测试保持全绿

---

### Task 1: TopicSource 核心

**Files:**
- Create: `src/signals/topic_source.py`
- Modify: `src/signals/webpage_source.py`（`_parse_items` 提取为共享函数，支持可选 url 字段）
- Test: `tests/signals/test_topic_source.py`、`tests/signals/test_webpage_source.py`（保持绿）

**Interfaces:**
- Consumes: `DailyBudget`, `CRITERIA`（`src/signals/ai_triage.py`）；`Signal`/`SignalStrength`
- Produces: `TopicSource(topic, source_name, filter_policy="gs_only", llm_config=None, get_setting, set_setting, daily_budget=10, recent_titles=None, max_searches=3)`；方法 `fetch_since(watermark) -> (list[Signal], None)`、`fetch(quarter)`、`close()`；属性 `fetch_note: str`
- 共享解析：`parse_items_json(text, max_items) -> list | None`（放 `src/signals/ai_triage.py`，返回 `{title, summary, url}` dicts，url 仅保留 http(s)）；`WebpageSource._parse_items` 改用它

行为要点：
- 工具声明：`tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": self.max_searches}]`
- Signal.url = 条目自带 url（空则 None）；published_at=now；companies=[]；强度 gs_only→MEDIUM / all→LOW
- `recent_titles(source_name)` 过滤已见标题
- `close()`：无 httpx client，no-op（保持协议一致）
- 水印恒返回 None（不推进）

- [ ] **Step 1: 写失败测试**

创建 `tests/signals/test_topic_source.py`：

```python
"""Tests for src.signals.topic_source."""
import pytest

from src.signals.topic_source import TopicSource

LLM_CFG = {"api_key": None, "auth_token": "tok", "base_url": "https://x.test", "model": "m"}
NO_CFG = {"api_key": None, "auth_token": None, "base_url": None, "model": "m"}


def _store():
    store = {}
    return store, (lambda k, d="": store.get(k, d)), (lambda k, v: store.__setitem__(k, v))


class _FakeClient:
    """Scripted LLM client. responses: list of texts, one per create() call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.kwargs_seen = []
        self.messages = self._Messages(self)

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        async def create(self, **kwargs):
            self._outer.calls += 1
            self._outer.kwargs_seen.append(kwargs)
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
    client = _patch_llm(monkeypatch, responses)
    store, gs, ss = _store()
    kwargs.setdefault("llm_config", LLM_CFG)
    kwargs.setdefault("get_setting", gs)
    kwargs.setdefault("set_setting", ss)
    src = TopicSource(**kwargs)
    return src, client


ITEMS_JSON = (
    '{"items": ['
    '{"title": "高盛超配A股", "summary": "沪深300看涨12%", "url": "https://wallstreetcn.com/a/1"},'
    '{"title": "高盛资金流入预测", "summary": "3.6万亿增量", "url": "https://caixin.com/2"}'
    ']}'
)


@pytest.mark.asyncio
async def test_search_returns_signals_with_urls(monkeypatch):
    src, client = _make_source(monkeypatch, [ITEMS_JSON],
                               topic="高盛对中国股市的最新观点", source_name="gs_china")
    signals, wm = await src.fetch_since(None)
    assert len(signals) == 2
    assert signals[0].title == "高盛超配A股"
    assert signals[0].url == "https://wallstreetcn.com/a/1"
    assert signals[0].source == "gs_china"
    assert signals[0].strength.value == "medium"
    assert wm is None  # no watermark for search sources
    # web_search tool declared with max_uses
    tools = client.kwargs_seen[0]["tools"]
    assert tools[0]["type"] == "web_search_20250305"
    assert tools[0]["max_uses"] == 3
    assert client.kwargs_seen[0]["max_tokens"] == 8192
    await src.close()


@pytest.mark.asyncio
async def test_all_policy_strength_low(monkeypatch):
    src, _ = _make_source(monkeypatch, [ITEMS_JSON],
                          topic="x", source_name="t", filter_policy="all")
    signals, _ = await src.fetch_since(None)
    assert signals[0].strength.value == "low"
    await src.close()


@pytest.mark.asyncio
async def test_item_without_url_gets_none(monkeypatch):
    src, _ = _make_source(
        monkeypatch,
        ['{"items": [{"title": "t", "summary": "s", "url": "ftp://bad"}, {"title": "t2", "summary": "s"}]}'],
        topic="x", source_name="t")
    signals, _ = await src.fetch_since(None)
    assert signals[0].url is None
    assert signals[1].url is None
    await src.close()


@pytest.mark.asyncio
async def test_no_llm_config_degrades_with_note():
    store, gs, ss = _store()
    src = TopicSource(topic="x", source_name="t", llm_config=NO_CFG,
                      get_setting=gs, set_setting=ss)
    signals, _ = await src.fetch_since(None)
    assert signals == []
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
    src = TopicSource(topic="x", source_name="t", llm_config=LLM_CFG,
                      get_setting=gs, set_setting=ss)
    signals, _ = await src.fetch_since(None)
    assert signals == []
    assert src.fetch_note
    await src.close()


@pytest.mark.asyncio
async def test_unparseable_output_degrades(monkeypatch):
    src, _ = _make_source(monkeypatch, ["没找到什么"], topic="x", source_name="t")
    signals, _ = await src.fetch_since(None)
    assert signals == []
    assert "格式" in src.fetch_note
    await src.close()


@pytest.mark.asyncio
async def test_budget_exhausted_skips_search(monkeypatch):
    src, client = _make_source(monkeypatch, [ITEMS_JSON],
                               topic="x", source_name="t", daily_budget=0)
    signals, _ = await src.fetch_since(None)
    assert signals == []
    assert client.calls == 0
    assert "预算" in src.fetch_note
    await src.close()


@pytest.mark.asyncio
async def test_recent_titles_filtered(monkeypatch):
    src, _ = _make_source(monkeypatch, [ITEMS_JSON],
                          topic="x", source_name="t",
                          recent_titles=lambda name: {"高盛超配A股"})
    signals, _ = await src.fetch_since(None)
    assert [s.title for s in signals] == ["高盛资金流入预测"]
    await src.close()


@pytest.mark.asyncio
async def test_empty_items_not_an_error(monkeypatch):
    src, _ = _make_source(monkeypatch, ['{"items": []}'], topic="x", source_name="t")
    signals, _ = await src.fetch_since(None)
    assert signals == []
    assert src.fetch_note == ""  # genuinely nothing new — not a failure
    await src.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/signals/test_topic_source.py -q`
Expected: collection error（模块不存在）

- [ ] **Step 3: 实现**

3a. `src/signals/ai_triage.py` 末尾追加共享解析函数：

```python
def parse_items_json(text: str, max_items: int) -> Optional[list]:
    """Extract an {"items": [...]} array from model output; None if unparseable.

    Shared by webpage/topic sources. Each item becomes {title, summary, url} —
    url is kept only when it is an http(s) link, else None.
    """
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
    for it in items[:max_items]:
        if isinstance(it, dict) and it.get("title"):
            url = str(it.get("url") or "").strip()
            result.append({
                "title": str(it["title"]).strip()[:120],
                "summary": str(it.get("summary") or "").strip()[:300],
                "url": url if url.startswith(("http://", "https://")) else None,
            })
    return result
```

3b. `src/signals/webpage_source.py`：删 `_parse_items`，改用共享函数（保持行为一致——webpage 不用 item 的 url 字段）：

```python
from src.signals.ai_triage import CRITERIA, DailyBudget, parse_items_json
```

`fetch_since` 里 `items = await self._extract_items(text)` 之后不变；`_extract_items` 末尾：

```python
        out = "".join(b.text for b in resp.content if hasattr(b, "text"))
        items = parse_items_json(out, MAX_ITEMS)
        if items is None:
            logger.warning("Webpage extraction unparseable for %s: %.200s", self.source_name, out)
            self.fetch_note = "AI 返回格式异常，本次跳过该网页"
        return items
```

（注意：原 `_parse_items` 返回的 dict 没有 url 键，webpage 构造 Signal 时用 `it["title"]/it["summary"]`，共享函数多返回 url 键不影响。）

3c. 创建 `src/signals/topic_source.py`：

```python
"""Topic-type custom source: the LLM searches the web itself (gateway
web_search server tool) for a user-defined topic and organizes what it finds.

No deterministic fallback exists without the LLM, and there is no page to
hash — every run searches once. Cost control: a daily LLM-call budget
(ai_topic_count_*) plus a max_searches cap per run. Cross-day dedup relies on
recent_titles (same as webpage sources). AI failures degrade to
"no items + fetch_note" (yellow triage_note in the pipeline).
"""
import logging
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from src.signals.ai_triage import CRITERIA, DailyBudget, parse_items_json
from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

MAX_ITEMS = 8
MAX_TOKENS = 8192  # web_search runs multiple rounds before answering
DEFAULT_DAILY_BUDGET = 10
DEFAULT_MAX_SEARCHES = 3


class TopicSource:
    """One search topic + gateway web_search → AI-organized signals."""

    def __init__(
        self,
        topic: str,
        source_name: str,
        filter_policy: str = "gs_only",
        llm_config: Optional[dict] = None,
        get_setting: Callable[[str, str], str] = lambda k, d="": d,
        set_setting: Callable[[str, str], None] = lambda k, v: None,
        daily_budget: int = DEFAULT_DAILY_BUDGET,
        recent_titles: Optional[Callable[[str], set]] = None,
        max_searches: int = DEFAULT_MAX_SEARCHES,
    ) -> None:
        self.topic = topic
        self.source_name = source_name
        self.filter_policy = filter_policy
        self.llm_config = llm_config or {}
        self.budget = DailyBudget("ai_topic_count", daily_budget, get_setting, set_setting)
        self._recent_titles = recent_titles or (lambda name: set())
        self.max_searches = max_searches
        self.fetch_note = ""  # AI degradation reason; read by the pipeline
        self._llm_client = None  # lazy anthropic.AsyncAnthropic

    async def close(self) -> None:
        """No HTTP client of our own — protocol no-op."""

    async def fetch(self, quarter: str) -> List[Signal]:
        signals, _ = await self.fetch_since(None)
        return signals

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]:
        self.fetch_note = ""
        items = await self._search_items()
        if items is None:
            return [], None  # degraded (fetch_note set)
        seen = self._recent_titles(self.source_name)
        items = [it for it in items if it["title"] not in seen]
        if not items:
            return [], None

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
                url=it["url"],
            )
            for it in items
        ]
        return signals, None

    def _build_prompt(self) -> str:
        criteria = CRITERIA.get(self.filter_policy, CRITERIA["gs_only"])
        return (
            "你是投资情报搜集助手。用户是中国 A 股个人投资者，关注高盛观点以判断市场趋势。\n\n"
            f"搜索主题：{self.topic}\n"
            f"筛选标准：{criteria}\n\n"
            f"请用 web_search 搜索（最多 {self.max_searches} 次），整理出最新、最相关的条目。\n"
            '最后只输出 JSON，不要输出其他内容：{"items": [{"title": "条目标题", "summary": "150字内摘要", "url": "来源链接"}]}，'
            f"最多 {MAX_ITEMS} 条；没有符合要求的内容则输出空数组。"
        )

    def _get_llm_client(self):
        if self._llm_client is None:
            import anthropic

            self._llm_client = anthropic.AsyncAnthropic(
                api_key=self.llm_config.get("api_key"),
                auth_token=self.llm_config.get("auth_token"),
                base_url=self.llm_config.get("base_url"),
                timeout=120.0,
            )
        return self._llm_client

    async def _search_items(self) -> Optional[list]:
        """LLM web_search extraction; None means degraded (fetch_note explains)."""
        if not (self.llm_config.get("api_key") or self.llm_config.get("auth_token")):
            self.fetch_note = "未配置大模型，主题搜索源无法工作"
            return None
        if self.budget.exhausted():
            self.fetch_note = "主题搜索 AI 预算已用完，明日自动恢复"
            return None
        try:
            resp = await self._get_llm_client().messages.create(
                model=self.llm_config["model"],
                max_tokens=MAX_TOKENS,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": self.max_searches,
                }],
                messages=[{"role": "user", "content": self._build_prompt()}],
            )
            self.budget.increment()
        except Exception as exc:
            logger.warning("Topic search failed for %s: %s", self.source_name, exc)
            self.fetch_note = "AI 搜索失败，本次跳过该主题"
            return None
        out = "".join(b.text for b in resp.content if hasattr(b, "text"))
        items = parse_items_json(out, MAX_ITEMS)
        if items is None:
            logger.warning("Topic search unparseable for %s: %.200s", self.source_name, out)
            self.fetch_note = "AI 返回格式异常，本次跳过该主题"
        return items
```

注意：`test_no_llm_config_degrades_with_note` 等构造时没传 llm client——`_search_items` 在无凭证时先返回，不会触碰 client。`close()` 是 no-op。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/signals/test_topic_source.py tests/signals/test_webpage_source.py -q`
Expected: 19 passed（9 新 + 10 原有）

- [ ] **Step 5: Commit**

```bash
git add src/signals/topic_source.py src/signals/webpage_source.py src/signals/ai_triage.py tests/signals/test_topic_source.py
git commit -m "feat(sources): TopicSource — LLM web_search per user topic + shared items parser"
```

---

### Task 2: 流水线集成

**Files:**
- Modify: `src/main.py`（`_build_daily_sources`）
- Test: `tests/test_main.py`

**Interfaces:**
- topic 分支：`entry["instruction"]` 作为 topic 传入；无 url 要求

- [ ] **Step 1: 写失败测试**

`tests/test_main.py` 的 `TestDailyIntel` 内追加：

```python
    @pytest.mark.asyncio
    async def test_build_daily_sources_includes_topic(self, monkeypatch):
        """topic-type custom entries become TopicSource instances (no url needed)."""
        monkeypatch.setattr("src.main.RSS_FEEDS", [])
        config = json.dumps([
            {"name": "news", "enabled": True, "builtin": True},
            {"name": "gs_china_view", "label": "高盛中国观点", "type": "topic",
             "url": "", "instruction": "高盛对中国股市的最新观点",
             "filter_policy": "gs_only", "enabled": True, "builtin": False},
        ])
        with patch("src.main.get_setting", return_value=config), \
             patch("src.main.TopicSource") as MockTopic, \
             patch("src.main.NewsSource"), \
             patch("src.main.ThirteenDGSource"), \
             patch("src.main.Sec8kSource"), \
             patch("src.main.ResearchViewSource"), \
             patch("src.main.get_default_llm_model", return_value=None):
            from src.main import _build_daily_sources

            _build_daily_sources()

        topic_call = MockTopic.call_args_list[0]
        assert topic_call.kwargs["topic"] == "高盛对中国股市的最新观点"
        assert topic_call.kwargs["source_name"] == "gs_china_view"
        assert topic_call.kwargs["filter_policy"] == "gs_only"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_main.py -q -k topic`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/main.py`：
1. import 增加 `from src.signals.topic_source import TopicSource`
2. 自定义源循环改为（注意 url 检查只对 rss/webpage）：

```python
    # Custom sources from the settings page (one instance per source)
    for entry in _custom_source_configs():
        if entry.get("name") not in enabled:
            continue
        if entry.get("type") == "rss" and entry.get("url"):
            sources.append((
                entry["name"],
                NewsSource(
                    rss_urls=[entry["url"]],
                    source_name=entry["name"],
                    filter_policy=entry.get("filter_policy", "gs_only"),
                ),
            ))
        elif entry.get("type") == "webpage" and entry.get("url"):
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
        elif entry.get("type") == "topic" and entry.get("instruction"):
            sources.append((
                entry["name"],
                TopicSource(
                    topic=entry["instruction"],
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
    return sources
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_main.py -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_main.py
git commit -m "feat(pipeline): wire topic sources into daily intel"
```

---

### Task 3: 设置 API — topic 型 + url 放宽

**Files:**
- Modify: `src/web.py`（`_validate_custom_payload`、PUT 一致性校验、test 端点）
- Test: `tests/test_web.py`

**Interfaces:**
- `type` 增加 `"topic"`；topic 时 url 可空、instruction（主题）必填 ≤100 字；非空 url 仍须 http(s)
- test 端点支持 topic（真实搜索预览，消耗预算）

- [ ] **Step 1: 写失败测试**

`tests/test_web.py` 追加：

```python
def test_topic_source_crud(signals_db):
    payload = _custom_payload(name="gs_china_view", type="topic", url="",
                              instruction="高盛对中国股市的最新观点")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201

    sources = client.get("/api/settings/sources").json()
    entry = [s for s in sources if s["name"] == "gs_china_view"][0]
    assert entry["type"] == "topic"
    assert entry["url"] == ""
    assert entry["instruction"] == "高盛对中国股市的最新观点"


def test_topic_source_requires_topic(signals_db):
    resp = client.post(
        "/api/settings/sources/custom",
        json=_custom_payload(type="topic", url="", instruction=""),
    )
    assert resp.status_code == 422


def test_topic_source_rejects_bad_url(signals_db):
    resp = client.post(
        "/api/settings/sources/custom",
        json=_custom_payload(type="topic", url="ftp://x", instruction="主题"),
    )
    assert resp.status_code == 422


def test_topic_edit_cannot_drop_instruction(signals_db):
    payload = _custom_payload(name="tp", type="topic", url="", instruction="主题")
    assert client.post("/api/settings/sources/custom", json=payload).status_code == 201
    resp = client.put("/api/settings/sources/custom/tp", json={"instruction": " "})
    assert resp.status_code == 422


def test_test_source_topic_preview(signals_db, monkeypatch, make_signal):
    """Topic test runs a real search + triage preview with per-item keep flags."""
    class _FakeTopicSource:
        def __init__(self, **kwargs):
            self.fetch_note = ""

        async def fetch(self, quarter):
            return [make_signal(id="t1", title="要点一"), make_signal(id="t2", title="要点二")]

        async def close(self):
            pass

    class _FakeTriage:
        def __init__(self, *a, **kw):
            pass

        async def triage(self, items, label, policy):
            from src.signals.ai_triage import TriageResult
            return TriageResult(kept_indices=[1], fallback_used=False, note="")

    monkeypatch.setattr("src.signals.topic_source.TopicSource", _FakeTopicSource)
    monkeypatch.setattr("src.web.AiTriage", _FakeTriage)
    monkeypatch.setattr("src.web.resolve_llm_config",
                        lambda m: {"api_key": None, "auth_token": "t", "base_url": "u", "model": "m"})

    resp = client.post("/api/settings/sources/test", json={
        "type": "topic", "instruction": "高盛对中国股市的最新观点", "filter_policy": "gs_only",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["ai_used"] is True
    assert data["items"] == [{"title": "要点一", "kept": False}, {"title": "要点二", "kept": True}]


def test_test_source_topic_requires_instruction(signals_db):
    resp = client.post("/api/settings/sources/test", json={"type": "topic"})
    assert resp.status_code == 422
```

（`_custom_payload` 默认 url="https://example.com/rss"，topic 测试显式传 url=""。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/pytest tests/test_web.py -q -k topic`
Expected: FAIL

- [ ] **Step 3: 实现**

`src/web.py`：

1. `_validate_custom_payload`：url 校验放宽 + type 接受 topic：

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
    if source_type not in ("rss", "webpage", "topic"):
        raise HTTPException(status_code=422, detail="type 必须是 rss、webpage 或 topic")
    if source_type in ("rss", "webpage") and not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
    if source_type == "topic":
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
        url = ""  # topics don't use a url
    if source_type in ("webpage", "topic") and not instruction:
        detail = "网页型源必须填写提取说明" if source_type == "webpage" else "主题搜索源必须填写搜索主题"
        raise HTTPException(status_code=422, detail=detail)
    if filter_policy not in ("gs_only", "all"):
        raise HTTPException(status_code=422, detail="filter_policy 必须是 gs_only 或 all")
    if len(instruction) > 100:
        raise HTTPException(status_code=422, detail="提取说明不超过 100 字")
    return name, label, url, filter_policy, source_type, instruction
```

2. PUT 端点：`type` 白名单加 `"topic"`；一致性校验改为：

```python
    if "type" in config:
        if config["type"] not in ("rss", "webpage", "topic"):
            raise HTTPException(status_code=422, detail="type 必须是 rss、webpage 或 topic")
        entry["type"] = config["type"]
    if "instruction" in config:
        instruction = (config.get("instruction") or "").strip()
        if len(instruction) > 100:
            raise HTTPException(status_code=422, detail="提取说明不超过 100 字")
        entry["instruction"] = instruction
    if "url" in config:
        url = (config.get("url") or "").strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")
        entry["url"] = url
    if entry.get("type") in ("webpage", "topic") and not (entry.get("instruction") or "").strip():
        raise HTTPException(status_code=422, detail="该类型源必须填写说明/主题")
    if entry.get("type") == "topic":
        entry["url"] = ""
```

（原有 `if "url" in config` 块按上面新版替换——要求 http(s) 仅当非空。）

3. test 端点：url 校验放宽 + topic 分支：

```python
    url = (config.get("url") or "").strip()
    source_type = config.get("type") or "rss"
    filter_policy = config.get("filter_policy") or "gs_only"
    instruction = (config.get("instruction") or "").strip()
    label = (config.get("label") or "").strip() or url or instruction
    if source_type not in ("rss", "webpage", "topic"):
        raise HTTPException(status_code=422, detail="type 必须是 rss、webpage 或 topic")
    if source_type in ("rss", "webpage") and not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="地址必须是 http(s) 链接")

    if source_type == "topic":
        if not instruction:
            raise HTTPException(status_code=422, detail="主题搜索源必须填写搜索主题")
        from src.signals.topic_source import TopicSource

        source = TopicSource(
            topic=instruction, source_name="_test",
            filter_policy=filter_policy,
            llm_config=resolve_llm_config(get_default_llm_model()),
            get_setting=get_setting, set_setting=set_setting,
        )
    elif source_type == "webpage":
        ...（不变）
    else:
        ...（不变）
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/pytest tests/test_web.py -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add src/web.py tests/test_web.py
git commit -m "feat(settings-api): topic type, optional url, topic search preview"
```

---

### Task 4: 设置页 UI

**Files:**
- Modify: `templates/dashboard.html`

**Interfaces:**
- 类型下拉启用"主题搜索"；选 topic 时隐藏 URL 框、说明框 placeholder 变为搜索主题
- 列表类型标签加 `topic: '主题'`

- [ ] **Step 1: 表单与 JS**

1. csType 的禁用项启用：`<option value="topic">主题搜索</option>`
2. `onCsTypeChange()` 升级：

```js
function onCsTypeChange() {
    const t = document.getElementById('csType').value;
    document.getElementById('csInstruction').style.display = (t === 'rss') ? 'none' : '';
    document.getElementById('csUrl').style.display = (t === 'topic') ? 'none' : '';
    document.getElementById('csInstruction').placeholder =
        t === 'topic' ? '搜索主题（如：高盛对中国股市的最新观点）'
                      : '提取说明（如：提取页面中高盛的市场观点与目标价）';
}
```

3. 类型标签映射加 topic：`({rss:'RSS',webpage:'网页',topic:'主题'})[s.type] || esc(s.type)`
4. `testCustomSource()` 已有 type/instruction 直传，url 为空时后端放宽——无需改；但 `if (!url)` 前置检查要按类型放宽：

```js
    const t = document.getElementById('csType').value;
    if (t !== 'topic' && !url) { box.textContent = '请先填写地址'; return; }
    if (t === 'topic' && !document.getElementById('csInstruction').value.trim()) { box.textContent = '请先填写搜索主题'; return; }
```

5. `saveCustomSource()` 同样：topic 时不要求 url（前端不拦，后端校验兜底）

- [ ] **Step 2: 浏览器验证**

1. 类型选"主题搜索" → URL 框隐藏、说明框 placeholder 变为搜索主题
2. 填主题"高盛对中国股市的最新观点" → 🔍 测试源 → 显示真实搜索结果预览（✅/❌）
3. 保存 → 列表 [主题] 标签 → 编辑回填 → 切回 RSS 类型时 URL 框恢复

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(settings-ui): topic type with search-theme form + preview"
```

---

### Task 5: 全量回归 + e2e + 部署

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/pytest -q`
Expected: 270+ passed

- [ ] **Step 2: 本地 e2e**

真实主题源（高盛对中国股市的最新观点）跑完整每日情报 SSE：主题源出信号、预筛、入库、前端展示。更新 spec 阶段表 P3 为已实施。

- [ ] **Step 3: 部署**

```bash
git push origin main
gh run list --limit 1   # completed + success
curl -s -o /dev/null -w "%{http_code}" http://111.228.23.109/api/health   # 401 = 在线
```
