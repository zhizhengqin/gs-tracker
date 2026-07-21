"""Compliance guardrail — prevent unattributed investment advice.

The red line: "产品自己给出买卖建议" is illegal in China without a
证券投资咨询牌照. "带归因地转述高盛观点" is legal information aggregation.

This module provides runtime content checks so that even if the LLM
drifts and produces unattributed advice, it is caught before storage
or push.
"""
import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Phrases that indicate the PRODUCT is giving advice, not attributing to GS.
# Match even when embedded in longer Chinese sentences.
BANNED_PATTERNS: List[re.Pattern] = [
    re.compile(r"我们建议"),
    re.compile(r"本\s*[Tt]racker\s*建议"),
    re.compile(r"建议买入"),
    re.compile(r"建议卖出"),
    re.compile(r"建议持有"),
    re.compile(r"建议做多"),
    re.compile(r"建议做空"),
    re.compile(r"建议减仓"),
    re.compile(r"建议加仓"),
    re.compile(r"建议清仓"),
    re.compile(r"推荐买入"),
    re.compile(r"推荐卖出"),
    re.compile(r"目标价看至"),  # without attribution
    re.compile(r"强力买入"),
    re.compile(r"强烈建议"),
]

# Phrases that indicate legitimate attribution — NOT banned.
# These must be checked first; if present, the content is allowed even
# if a banned pattern also matches (e.g. "高盛建议买入" is allowed).
ATTRIBUTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"高盛[^\n]{0,20}(建议|评级|目标价|维持|上调|下调|看好|看空)"),
    re.compile(r"高盛[^\n]{0,10}(buy|sell|hold|overweight|underweight|neutral)", re.IGNORECASE),
]


def check_content(text: str) -> Tuple[bool, List[str]]:
    """Check whether *text* violates the unattributed-advice policy.

    Returns (passed, violations):
    - passed=True  → content is clean or properly attributed
    - passed=False → violations list contains the matched banned phrases

    Proper attribution (e.g. "高盛维持英伟达买入评级，目标价200美元")
    is checked FIRST — if any attribution pattern matches, the text passes
    regardless of banned-pattern matches.
    """
    if not text or not text.strip():
        return True, []

    # Attribution check first: if the text names Goldman as the source,
    # it passes regardless — this is the "转述 vs 自荐" distinction.
    for pattern in ATTRIBUTION_PATTERNS:
        if pattern.search(text):
            return True, []

    violations: List[str] = []
    for pattern in BANNED_PATTERNS:
        match = pattern.search(text)
        if match:
            violations.append(match.group())

    return len(violations) == 0, violations


def filter_for_report(text: str) -> Tuple[str, List[str]]:
    """Sanitize *text* for inclusion in reports.

    Returns (sanitized_text, violations_found). Violated phrases are
    replaced with a脱敏 placeholder and logged as alerts.
    """
    if not text:
        return text, []

    # If properly attributed, return as-is
    passed, violations = check_content(text)
    if passed:
        return text, []

    sanitized = text
    for pattern in BANNED_PATTERNS:
        sanitized = pattern.sub("[合规脱敏-无归因建议已移除]", sanitized)

    logger.warning(
        "Compliance filter triggered: %d violations sanitized. Original: %s...",
        len(violations), text[:200],
    )
    return sanitized, violations


def filter_signal_summaries(signals: list) -> list:
    """Apply compliance filter to all signals' summaries. Mutates in place."""
    violations_total = 0
    for sig in signals:
        if hasattr(sig, 'summary') and sig.summary:
            sig.summary, v = filter_for_report(sig.summary)
            violations_total += len(v)
        if hasattr(sig, 'title') and sig.title:
            sig.title, v = filter_for_report(sig.title)
            violations_total += len(v)
    if violations_total:
        logger.warning("Compliance: %d total violations across %d signals",
                       violations_total, len(signals))
    return signals
