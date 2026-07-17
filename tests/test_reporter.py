"""Tests for src.reporter."""
from src.reporter import ReportGenerator


def test_report_generator_loads_templates():
    gen = ReportGenerator()
    assert gen.env is not None
