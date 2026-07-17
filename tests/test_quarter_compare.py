import pandas as pd
import pytest
from src.quarter_compare import QuarterComparator


def test_compare_new_and_sold_positions():
    current = pd.DataFrame({
        "cusip": ["A", "B"],
        "name_of_issuer": ["Apple", "Banana"],
        "value": [1000000.0, 500000.0],
        "shares": [1000, 500],
    })
    previous = pd.DataFrame({
        "cusip": ["B", "C"],
        "name_of_issuer": ["Banana", "Cherry"],
        "value": [400000.0, 300000.0],
        "shares": [400, 300],
    })
    comp = QuarterComparator()
    result = comp.compare(current, previous, "2026-Q1", "2025-Q4")
    assert len(result.new_positions) == 1
    assert result.new_positions.iloc[0]["cusip"] == "A"
    assert len(result.sold_positions) == 1
    assert result.sold_positions.iloc[0]["cusip"] == "C"
    assert len(result.increased_positions) == 1
    assert result.increased_positions.iloc[0]["cusip"] == "B"
