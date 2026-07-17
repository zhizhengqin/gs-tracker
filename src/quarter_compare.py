"""Quarter-over-quarter holdings comparison."""
from dataclasses import dataclass
from typing import List

import pandas as pd


@dataclass
class QuarterComparison:
    """Result of comparing two quarterly holdings reports."""

    quarter_current: str
    quarter_previous: str
    new_positions: pd.DataFrame
    sold_positions: pd.DataFrame
    increased_positions: pd.DataFrame
    decreased_positions: pd.DataFrame
    concentration_change: float


class QuarterComparator:
    """Compare 13F holdings between two quarters."""

    def __init__(self, value_threshold: float = 0.2) -> None:
        self.value_threshold = value_threshold

    def compare(
        self,
        current_df: pd.DataFrame,
        previous_df: pd.DataFrame,
        quarter_current: str,
        quarter_previous: str,
    ) -> QuarterComparison:
        """Compare current and previous quarter holdings."""
        raise NotImplementedError("TODO: implement quarter comparison")

    def _compute_hhi(self, df: pd.DataFrame) -> float:
        """Compute Herfindahl-Hirschman Index for concentration."""
        raise NotImplementedError("TODO: implement HHI")
