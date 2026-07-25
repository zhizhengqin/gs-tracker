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
    assert src._llm_client.calls == 1
    signals2, wm2 = await src.fetch_since(wm)
    assert signals2 == [] and wm2 is None
    assert src._llm_client.calls == 1  # unchanged page made no second LLM call
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
    assert src._llm_client is None or src._llm_client.calls == 0
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
