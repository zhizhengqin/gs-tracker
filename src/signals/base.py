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
    Concrete implementations return List[Signal] from fetch().
    """

    source_name: str

    async def fetch(self, quarter: str) -> List[Signal]: ...

    async def close(self) -> None: ...
