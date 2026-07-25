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
