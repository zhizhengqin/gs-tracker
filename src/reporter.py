"""HTML report generator."""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import matplotlib
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.analyzer import AnalysisResult
from src.config import PROJECT_ROOT, REPORT_OUTPUT_DIR

matplotlib.use("Agg")

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
        analysis: AnalysisResult,
        output_path: Optional[Path] = None,
        signals: Optional[list] = None,
        signal_errors: Optional[list] = None,
        source_status: Optional[dict] = None,
    ) -> Path:
        """Render a single quarter HTML report."""
        if output_path is None:
            output_path = REPORT_OUTPUT_DIR / f"{quarter}.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = self.env.get_template("report.html")
        rendered = template.render(
            quarter=quarter,
            holdings=holdings_df.to_dict(orient="records"),
            analysis=analysis,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            signals=signals or [],
            signal_errors=signal_errors or [],
            source_status=source_status or {},
        )
        output_path.write_text(rendered, encoding="utf-8")
        logger.info("Report generated at %s", output_path)
        return output_path

    def generate_index(self, reports: List[dict]) -> Path:
        """Render the report listing page."""
        raise NotImplementedError("TODO: implement index generation")

    def _plot_top_holdings(self, holdings_df: pd.DataFrame, limit: int = 15) -> str:
        """Return base64-encoded bar chart of top holdings."""
        raise NotImplementedError("TODO: implement chart plotting")
