"""Base types for the signal aggregation system."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional, Protocol, Tuple


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
    cross_refs: List[str] = field(default_factory=list)
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
