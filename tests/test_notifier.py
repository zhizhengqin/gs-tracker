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
