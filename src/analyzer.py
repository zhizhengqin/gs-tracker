"""AI analysis engine using Claude API."""
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, List, Optional

import anthropic
import pandas as pd

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_BACKOFF_BASE,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MAX_RETRIES,
    GS_LLM_MODEL,
)

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Structured AI analysis output."""

    summary: str
    concentration_analysis: str
    top_holdings_analysis: str
    sector_preference: str
    trading_signals: str
    risk_warnings: str
    retail_insights: str
    key_tickers: List[str]
    sentiment: str
    confidence: float


class GSAnalyzer:
    """Analyze holdings and multi-source signals via an Anthropic-compatible API.

    Works with the official Anthropic API (ANTHROPIC_API_KEY) or any
    Anthropic-compatible gateway such as Kimi (ANTHROPIC_BASE_URL +
    ANTHROPIC_AUTH_TOKEN). Empty config values become None so the SDK's
    own environment fallback chain still applies.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        auth_token: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key or ANTHROPIC_API_KEY or None,
            auth_token=auth_token or ANTHROPIC_AUTH_TOKEN or None,
            base_url=base_url or ANTHROPIC_BASE_URL or None,
        )
        self.model = model or GS_LLM_MODEL

    def _build_prompt(
        self,
        holdings_df: pd.DataFrame,
        previous_df: Optional[pd.DataFrame] = None,
    ) -> str:
        """Build a Chinese prompt asking Claude to analyze Goldman Sachs 13F holdings."""
        if holdings_df.empty:
            holdings_summary = "本期无持仓数据。"
        else:
            value_col = "value" if "value" in holdings_df.columns else None
            if value_col:
                sorted_df = holdings_df.sort_values(value_col, ascending=False)
                top_holdings = sorted_df.head(10)
            else:
                top_holdings = holdings_df.head(10)

            lines: List[str] = []
            for _, row in top_holdings.iterrows():
                name = row.get("name_of_issuer") or row.get("cusip") or "Unknown"
                value = row.get("value", 0) or 0
                shares = row.get("shares", 0) or 0
                lines.append(f"- {name}: 持仓价值 {value:,.0f} 美元，股数 {shares:,.0f}")
            holdings_summary = "\n".join(lines)

        previous_hint = ""
        if previous_df is not None and not previous_df.empty:
            previous_hint = "同时提供了上一季度持仓数据，请结合进行环比分析。"

        prompt = (
            "你是一位资深对冲基金持仓分析师。请基于以下高盛(Goldman Sachs)最新 13F "
            "持仓数据，生成一份面向普通投资者的中文分析报告。\n\n"
            f"{previous_hint}\n"
            "持仓汇总（按价值排序前 10）：\n"
            f"{holdings_summary}\n\n"
            "请从以下维度给出分析，每个维度用一段话简述：\n"
            "1. 总体摘要\n"
            "2. 持仓集中度分析\n"
            "3. 前十大重仓股分析\n"
            "4. 行业偏好\n"
            "5. 交易信号\n"
            "6. 风险提示\n"
            "7. 散户可借鉴的投资思路\n\n"
            "最后，请严格按以下 JSON 格式输出分析结果（不要包含 markdown 代码块标记）：\n"
            '{\n'
            '  "summary": "总体摘要",\n'
            '  "concentration_analysis": "集中度分析",\n'
            '  "top_holdings_analysis": "前十大重仓股分析",\n'
            '  "sector_preference": "行业偏好",\n'
            '  "trading_signals": "交易信号",\n'
            '  "risk_warnings": "风险提示",\n'
            '  "retail_insights": "散户可借鉴的投资思路",\n'
            '  "sentiment": "bullish|bearish|neutral",\n'
            '  "confidence": 0.75\n'
            '}\n'
            "输出保持中文，JSON 必须有效。"
        )
        return prompt

    def _extract_top_tickers(self, holdings_df: pd.DataFrame) -> List[str]:
        """Extract the top holdings identifiers to surface as key tickers."""
        if holdings_df.empty:
            return []
        ticker_col: str
        if "ticker" in holdings_df.columns:
            ticker_col = "ticker"
        elif "name_of_issuer" in holdings_df.columns:
            ticker_col = "name_of_issuer"
        elif "cusip" in holdings_df.columns:
            ticker_col = "cusip"
        else:
            return []

        value_col = "value" if "value" in holdings_df.columns else None
        if value_col:
            top = holdings_df.sort_values(value_col, ascending=False).head(10)
        else:
            top = holdings_df.head(10)
        return top[ticker_col].astype(str).tolist()

    @staticmethod
    def _parse_analysis_json(text: str) -> Optional[dict[str, Any]]:
        """Extract and validate JSON analysis from Claude response text."""
        text = text.strip()
        if not text:
            return None

        # Remove markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        # Extract the outermost JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

        required = {
            "summary",
            "concentration_analysis",
            "top_holdings_analysis",
            "sector_preference",
            "trading_signals",
            "risk_warnings",
            "retail_insights",
            "sentiment",
            "confidence",
        }
        if not required.issubset(data.keys()):
            return None

        # Type coercion / validation
        for key in required - {"sentiment", "confidence"}:
            if not isinstance(data[key], str):
                data[key] = str(data[key])

        try:
            data["confidence"] = float(data["confidence"])
        except (TypeError, ValueError):
            data["confidence"] = 0.5

        if data["sentiment"] not in {"bullish", "bearish", "neutral"}:
            data["sentiment"] = "neutral"

        return data

    def _placeholder_analysis(self, holdings_df: pd.DataFrame) -> AnalysisResult:
        """Return a Chinese placeholder when the Claude API is unavailable."""
        key_tickers = self._extract_top_tickers(holdings_df)
        return AnalysisResult(
            summary="AI 分析服务暂不可用，请稍后重试。",
            concentration_analysis="由于 AI 服务异常，无法生成集中度分析。",
            top_holdings_analysis="由于 AI 服务异常，无法生成重仓股分析。",
            sector_preference="由于 AI 服务异常，无法生成行业偏好分析。",
            trading_signals="由于 AI 服务异常，无法生成交易信号。",
            risk_warnings="AI 服务异常，建议关注后续官方披露。",
            retail_insights="由于 AI 服务异常，无法生成散户投资思路。",
            key_tickers=key_tickers,
            sentiment="neutral",
            confidence=0.0,
        )

    async def analyze_holdings(
        self,
        holdings_df: pd.DataFrame,
        previous_df: Optional[pd.DataFrame] = None,
    ) -> AnalysisResult:
        """Generate an AI analysis for a single quarter holdings report."""
        prompt = self._build_prompt(holdings_df, previous_df)
        analysis_text = ""

        retriable_errors = (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.OverloadedError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        )

        for attempt in range(ANTHROPIC_MAX_RETRIES):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    messages=[{"role": "user", "content": prompt}],
                )
                if response.content:
                    # Thinking models (e.g. Kimi) return ThinkingBlocks before the
                    # TextBlock; collect text only from blocks that carry it.
                    analysis_text = "".join(
                        block.text for block in response.content if getattr(block, "text", None)
                    )
                break
            except retriable_errors as exc:
                logger.warning("Claude API call failed on attempt %d: %s", attempt + 1, exc)
                if attempt < ANTHROPIC_MAX_RETRIES - 1:
                    await asyncio.sleep(ANTHROPIC_BACKOFF_BASE * (2 ** attempt))
            except anthropic.APIError as exc:
                # Non-retriable (auth failure, unknown model, bad request, ...):
                # retrying cannot help, so degrade to placeholder immediately
                # instead of crashing the whole pipeline run.
                logger.error("LLM API returned a non-retriable error: %s", exc)
                return self._placeholder_analysis(holdings_df)
        else:
            logger.error(
                "Claude API failed after %d attempts; returning placeholder analysis",
                ANTHROPIC_MAX_RETRIES,
            )
            return self._placeholder_analysis(holdings_df)

        if not analysis_text:
            logger.warning("Claude returned empty analysis text")

        parsed = self._parse_analysis_json(analysis_text)
        if parsed is None:
            logger.warning("Failed to parse structured analysis JSON; using raw text fallback")
            parsed = {
                "summary": analysis_text,
                "concentration_analysis": analysis_text,
                "top_holdings_analysis": analysis_text,
                "sector_preference": analysis_text,
                "trading_signals": analysis_text,
                "risk_warnings": analysis_text,
                "retail_insights": analysis_text,
                "sentiment": "neutral",
                "confidence": 0.5,
            }

        key_tickers = self._extract_top_tickers(holdings_df)
        return AnalysisResult(
            summary=parsed["summary"],
            concentration_analysis=parsed["concentration_analysis"],
            top_holdings_analysis=parsed["top_holdings_analysis"],
            sector_preference=parsed["sector_preference"],
            trading_signals=parsed["trading_signals"],
            risk_warnings=parsed["risk_warnings"],
            retail_insights=parsed["retail_insights"],
            key_tickers=key_tickers,
            sentiment=parsed["sentiment"],
            confidence=parsed["confidence"],
        )

    async def compare_quarters(
        self,
        current_df: pd.DataFrame,
        previous_df: pd.DataFrame,
    ) -> str:
        """Generate a quarter-over-quarter comparison narrative."""
        raise NotImplementedError("TODO: implement quarter comparison narrative")

    async def generate_multi_source_analysis(
        self,
        holdings_df: pd.DataFrame,
        research_views: List[dict],
        macro_views: List[dict],
        trading_signals: List[dict],
    ) -> str:
        """Aggregate multiple indirect signals into a directional view."""
        raise NotImplementedError("TODO: implement multi-source analysis")
