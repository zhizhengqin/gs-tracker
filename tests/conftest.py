"""Shared pytest configuration and fixtures."""
import pytest


@pytest.fixture
def sample_holdings_df():
    """Return a minimal sample holdings DataFrame."""
    import pandas as pd

    return pd.DataFrame(
        {
            "cusip": ["123456789", "987654321"],
            "name_of_issuer": ["Example Corp", "Another Inc"],
            "title_of_class": ["COM", "COM"],
            "value": [1000000.0, 500000.0],
            "shares": [10000, 5000],
            "investment_discretion": ["SOLE", "SOLE"],
        }
    )
