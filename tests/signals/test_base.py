"""Tests for src.signals.base."""
from datetime import datetime, timezone


from src.signals.base import Signal, SignalStrength, smart_truncate


class TestSmartTruncate:
    def test_short_text_unchanged(self):
        text = "高盛增持 Apple，持仓市值上升。"
        assert smart_truncate(text) == text

    def test_empty_and_none(self):
        assert smart_truncate("") == ""
        assert smart_truncate(None) == ""

    def test_long_text_cut_at_sentence_boundary(self):
        # 300 chars of first sentence + second sentence that overflows.
        first = "甲" * 298 + "。"
        rest = "乙" * 300
        out = smart_truncate(first + rest, max_len=400)
        assert out == first + "…"

    def test_boundary_too_early_falls_back_to_hard_cut(self):
        # Sentence ends at char 10 (< max_len // 2), rest has no punctuation.
        text = "短句。" + "长" * 500
        out = smart_truncate(text, max_len=400)
        assert out.endswith("…")
        assert not out.endswith("。…")
        assert len(out) == 401  # 400 chars + ellipsis

    def test_no_punctuation_hard_cut(self):
        text = "字" * 600
        out = smart_truncate(text, max_len=400)
        assert out == "字" * 400 + "…"

    def test_english_sentence_boundary(self):
        first = "word " * 69 + "end. "  # boundary lands in the back half
        rest = "tail " * 100
        out = smart_truncate(first + rest, max_len=400)
        assert out == first.rstrip() + "…"

    def test_exact_length_unchanged(self):
        text = "字" * 400
        assert smart_truncate(text, max_len=400) == text


class TestSignal:
    def test_signal_creation_with_required_fields(self):
        s = Signal(
            title="高盛增持 Apple 5%",
            source="13F",
            published_at=datetime(2026, 3, 31, tzinfo=timezone.utc),
            summary="高盛在 2026-Q1 增持 Apple 5%，持仓市值达到 $10B",
            companies=["AAPL"],
            strength=SignalStrength.HIGH,
        )
        assert s.title == "高盛增持 Apple 5%"
        assert s.source == "13F"
        assert s.companies == ["AAPL"]
        assert s.strength == SignalStrength.HIGH
        assert s.url is None
        assert s.cross_refs == []

    def test_signal_creation_with_all_fields(self):
        s = Signal(
            title="NVDA Q2 Earnings Beat",
            source="news",
            published_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            summary="NVIDIA Q2 财报超预期，营收同比增长 120%",
            companies=["NVDA"],
            strength=SignalStrength.HIGH,
            url="https://example.com/nvda-q2",
            cross_refs=["sig-001"],
        )
        assert s.url == "https://example.com/nvda-q2"
        assert s.cross_refs == ["sig-001"]

    def test_signal_equality_by_id(self):
        s1 = Signal(
            title="Same Title",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["AAPL"],
            strength=SignalStrength.LOW,
        )
        s2 = Signal(
            title="Same Title",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["AAPL"],
            strength=SignalStrength.LOW,
        )
        assert s1.id != s2.id

    def test_signal_strength_enum_values(self):
        assert SignalStrength.HIGH.value == "high"
        assert SignalStrength.MEDIUM.value == "medium"
        assert SignalStrength.LOW.value == "low"

    def test_signal_dedupe_key(self):
        s = Signal(
            title="Test",
            source="news",
            published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            summary="Summary",
            companies=["TEST"],
            strength=SignalStrength.LOW,
        )
        assert s.dedupe_key == ("news", "Test")
