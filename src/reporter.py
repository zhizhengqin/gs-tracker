"""HTML report generator."""
import logging
from pathlib import Path
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")  # noqa: E402
import matplotlib.pyplot as plt
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.config import PROJECT_ROOT, REPORT_OUTPUT_DIR

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate HTML intelligence board reports."""

    def __init__(self, template_dir: Optional[Path] = None) -> None:
        self.template_dir = template_dir or (PROJECT_ROOT / "templates")
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def generate_report(
        self,
        quarter: str,
        holdings_df: pd.DataFrame,
        analysis_text: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Render a single quarter HTML report."""
        raise NotImplementedError("TODO: implement report generation")

    def generate_index(self, reports: List[dict]) -> Path:
        """Render the report listing page."""
        raise NotImplementedError("TODO: implement index generation")

    def _plot_top_holdings(self, holdings_df: pd.DataFrame, limit: int = 15) -> str:
        """Return base64-encoded bar chart of top holdings."""
        raise NotImplementedError("TODO: implement chart plotting")
