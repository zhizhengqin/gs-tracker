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

# Only the largest positions are embedded in the static HTML report; the
# full list (10k+ rows, multi-MB) is served on demand via /api/holdings.
HOLDINGS_PREVIEW_LIMIT = 100


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
        institution_id: str = "gs",
        institution_label: str = "高盛",
    ) -> Path:
        """Render a single quarter HTML report.

        GS reports keep the legacy flat path (2026-Q1.html); other
        institutions go into a per-institution subdirectory so
        /api/reports can list them independently.
        """
        if output_path is None:
            if institution_id == "gs":
                output_path = REPORT_OUTPUT_DIR / f"{quarter}.html"
            else:
                output_path = REPORT_OUTPUT_DIR / institution_id / f"{quarter}.html"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        template = self.env.get_template("report.html")
        holdings_total = len(holdings_df)
        preview_df = holdings_df.sort_values(
            "value", ascending=False, na_position="last"
        ).head(HOLDINGS_PREVIEW_LIMIT)
        rendered = template.render(
            quarter=quarter,
            institution_label=institution_label,
            holdings=preview_df.to_dict(orient="records"),
            holdings_total=holdings_total,
            analysis=analysis,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
