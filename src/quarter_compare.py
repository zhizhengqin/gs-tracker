"""Quarter-over-quarter holdings comparison."""
from dataclasses import dataclass

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
        current_cusips = current_df["cusip"]
        previous_cusips = previous_df["cusip"]

        new_positions = current_df[~current_cusips.isin(previous_cusips)].copy()
        sold_positions = previous_df[~previous_cusips.isin(current_cusips)].copy()

        merged = current_df.merge(
            previous_df, on="cusip", suffixes=("", "_prev"), how="inner"
        )
        value_change_pct = (merged["value"] - merged["value_prev"]) / merged["value_prev"]

        increased_positions = merged[value_change_pct >= self.value_threshold].copy()
        decreased_positions = merged[value_change_pct <= -self.value_threshold].copy()

        concentration_change = self._compute_hhi(current_df) - self._compute_hhi(previous_df)

        return QuarterComparison(
            quarter_current=quarter_current,
            quarter_previous=quarter_previous,
            new_positions=new_positions,
            sold_positions=sold_positions,
            increased_positions=increased_positions,
            decreased_positions=decreased_positions,
            concentration_change=concentration_change,
        )

    def _compute_hhi(self, df: pd.DataFrame) -> float:
        """Compute Herfindahl-Hirschman Index for concentration."""
        total_value = df["value"].sum()
        if total_value == 0:
            return 0.0
        value_shares = df["value"] / total_value
        return float((value_shares**2).sum())
