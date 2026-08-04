"""Base types for the signal aggregation system."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Protocol, Tuple


SUMMARY_MAX_LEN = 400

_SENT_END_CHARS = "。！？!?；;."


def smart_truncate(text: str, max_len: int = SUMMARY_MAX_LEN) -> str:
    """Truncate text to ~max_len chars without cutting mid-sentence.

    Prefers to end at the last sentence-ending punctuation in the back half
    of the window; falls back to a hard cut when no usable boundary exists.
    Appends '…' whenever content was dropped.
    """
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    window = text[:max_len]
    cut = max(window.rfind(ch) for ch in _SENT_END_CHARS)
    if cut >= max_len // 2:
        return window[: cut + 1].rstrip() + "…"
    return window.rstrip() + "…"


INSTITUTION_DISPLAY_NAMES = {
    "gs": "高盛",
    "jpm": "摩根大通",
    "all": "外资",
}


def institution_display(institution_id: str) -> str:
    """Return the Chinese display name for an institution id."""
    return INSTITUTION_DISPLAY_NAMES.get(institution_id, institution_id)


class SignalStrength(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Signal:
    """Unified signal format across all data sources."""

    title: str
    source: str
    published_at: datetime
    summary: str
    companies: List[str]
    strength: SignalStrength
    url: Optional[str] = None
    institution_id: str = "gs"
    cross_refs: List[str] = field(default_factory=list)
    cross_institutional: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    @property
    def dedupe_key(self) -> Tuple[str, str]:
        """Key for identifying duplicate signals across sources."""
        return (self.source, self.title)


class SignalSource(Protocol):
    """Protocol documenting expected signal source interface.

    This is a documentation annotation, not enforced at runtime.

    Required:
        source_name: str — unique identifier used by scorer and storage.
        fetch(quarter) → List[Signal] — quarterly/backward-compat fetch.
        close() → None — release HTTP client resources.

    Optional (daily intel):
        fetch_since(watermark: str | None) → (List[Signal], str | None)
            Incremental fetch — returns only signals newer than *watermark*
            plus the new watermark to persist. When watermark is None,
            fetches all available (subject to internal limits).
            Implement this for sources that produce accumulating data
            (13D/G, news RSS, macro observations). Not needed for sources
            whose backend already returns only the latest (8-K submissions).
    """

    source_name: str

    async def fetch(self, quarter: str) -> List[Signal]: ...

    async def fetch_since(
        self, watermark: Optional[str] = None
    ) -> Tuple[List[Signal], Optional[str]]: ...

    async def close(self) -> None: ...
