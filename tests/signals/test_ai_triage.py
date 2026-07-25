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
    # 批内 1 基索引：第二批（仅 5 条）的 "1" 对应全局第 20 条
    client = _patch_client(monkeypatch, ['{"keep": [1]}', '{"keep": [1]}'])
    triage = AiTriage(LLM_CFG, gs, ss)
    result = await triage.triage(_items(25), "测试源", "all")
    assert client.calls == 2
    assert result.kept_indices == [0, 20]


@pytest.mark.asyncio
async def test_truncated_reason_still_uses_keep_array(monkeypatch):
    """Model blew the token budget mid-reason: JSON tail is cut off, but the
    keep array closed cleanly and must still be honored (no fallback)."""
    store, gs, ss = _store()
    truncated = '{"keep": [1, 9], "reason": "第1条直接引用高盛交易主管报告及其对反身性风险'
    _patch_client(monkeypatch, [truncated])
    triage = AiTriage(LLM_CFG, gs, ss)
    result = await triage.triage(_items(10), "测试源", "gs_only")
    assert result.kept_indices == [0, 8]
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_truncated_inside_keep_array_falls_back(monkeypatch):
    """Truncation inside the keep array itself → boundary unknown → keep-all."""
    store, gs, ss = _store()
    _patch_client(monkeypatch, ['{"keep": [1, 9'])
    triage = AiTriage(LLM_CFG, gs, ss)
    result = await triage.triage(_items(2), "测试源", "gs_only")
    assert result.kept_indices == [0, 1]
    assert result.fallback_used is True


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
    assert today in triage.budget._key()


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
