"""Rule-based signal scoring engine."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.signals.base import Signal, SignalStrength

logger = logging.getLogger(__name__)

STRENGTH_WEIGHT: Dict[SignalStrength, float] = {
    SignalStrength.HIGH: 3.0,
    SignalStrength.MEDIUM: 1.5,
    SignalStrength.LOW: 0.5,
}
SOURCE_CREDIBILITY: Dict[str, float] = {
    "13F": 1.2,
    "8-K": 1.2,
    "13D/13G": 1.1,
    "research_view": 1.0,
    "news": 0.8,
    "macro_view": 0.7,
}
DECAY_HALF_LIFE_DAYS = 14.0
CROSS_SIGNAL_BONUS = 2.0
CROSS_INSTITUTION_BONUS = 3.0
# institution_id values that aggregate many institutions and therefore
# cannot count as one side of a cross-institution collision.
NON_INSTITUTION_IDS = frozenset({"", "all"})
# Tokens that name the tracked institutions themselves. A JPM article
# mentioning "高盛" is coverage *of* GS, not a shared view on a third-party
# company, so these must not create cross-institution consensus.
SELF_COMPANY_TOKENS = frozenset({
    "gs", "jpm", "jpmorgan", "goldman", "goldman sachs", "高盛", "摩根大通",
})
STRENGTH_THRESHOLD_HIGH = 6.0
STRENGTH_THRESHOLD_MEDIUM = 3.0


@dataclass
class ScoredSignal:
    """A Signal with computed relevance score and final strength."""

    signal: Signal
    relevance_score: float
    final_strength: SignalStrength
    cross_refs: List[str] = field(default_factory=list)
    cross_institutional: bool = False


class SignalScorer:
    """Compute relevance scores and cross-source signal detection."""

    def __init__(self, reference_date: Optional[datetime] = None) -> None:
        self.reference_date = reference_date or datetime.now(timezone.utc)

    def score(self, signals: List[Signal]) -> List[ScoredSignal]:
        """Score and rank signals by relevance."""
        if not signals:
            return []

        # Build company → signal index for cross-reference detection
        company_index: Dict[str, List[Signal]] = {}
        # company → set of real institution ids covering it
        company_institutions: Dict[str, set] = {}
        for s in signals:
            inst = getattr(s, "institution_id", "gs")
            for company in s.companies:
                company_lower = company.lower()
                company_index.setdefault(company_lower, []).append(s)
                if (inst not in NON_INSTITUTION_IDS
                        and company_lower not in SELF_COMPANY_TOKENS):
                    company_institutions.setdefault(company_lower, set()).add(inst)

        scored: List[ScoredSignal] = []
        for signal in signals:
            score = self._compute_raw_score(signal)
            cross_refs = self._find_cross_refs(signal, company_index)
            cross_inst = self._is_cross_institutional(signal, company_institutions)

            if cross_refs:
                score += CROSS_SIGNAL_BONUS * len(cross_refs)
            if cross_inst:
                score += CROSS_INSTITUTION_BONUS

            final_strength = self._threshold(score)
            scored.append(ScoredSignal(
                signal=signal,
                relevance_score=round(score, 2),
                final_strength=final_strength,
                cross_refs=cross_refs,
                cross_institutional=cross_inst,
            ))

        scored.sort(key=lambda x: x.relevance_score, reverse=True)
        return scored

    def _compute_raw_score(self, signal: Signal) -> float:
        """Compute base score from time decay + source credibility + strength weight."""
        age_seconds = (self.reference_date - signal.published_at).total_seconds()
        age_days = max(0.0, age_seconds / 86400.0)
        time_factor = 2.0 ** (-age_days / DECAY_HALF_LIFE_DAYS)

        credibility = SOURCE_CREDIBILITY.get(signal.source, 1.0)
        strength_w = STRENGTH_WEIGHT.get(signal.strength, 1.0)

        return time_factor * credibility * strength_w * 3.0

    def _find_cross_refs(
        self, signal: Signal, company_index: Dict[str, List[Signal]]
    ) -> List[str]:
        """Find other signals that mention the same companies (cross-source validation)."""
        refs: set = set()
        for company in signal.companies:
            company_lower = company.lower()
            # An institution mentioning itself (e.g. a GS article tagged
            # "GS") must not pull in that institution's own filings as
            # cross-references -- that is noise, not a shared view.
            if company_lower in SELF_COMPANY_TOKENS:
                continue
            related = company_index.get(company_lower, [])
            for other in related:
                if other.id != signal.id and other.source != signal.source:
                    refs.add(other.id)
        return sorted(refs)

    @staticmethod
    def _is_cross_institutional(
        signal: Signal, company_institutions: Dict[str, set]
    ) -> bool:
        """True when any of the signal's companies is covered by >=2 real
        institutions (aggregate ids like "all" do not count)."""
        return any(
            len(company_institutions.get(company.lower(), set())) >= 2
            for company in signal.companies
        )

    @staticmethod
    def _threshold(score: float) -> SignalStrength:
        if score >= STRENGTH_THRESHOLD_HIGH:
            return SignalStrength.HIGH
        elif score >= STRENGTH_THRESHOLD_MEDIUM:
            return SignalStrength.MEDIUM
        return SignalStrength.LOW
