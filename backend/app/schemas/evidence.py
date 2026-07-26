"""Evidence ledger: research normalised into individual, citable claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class EvidenceStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    OUTDATED = "outdated"
    OPINION = "opinion"
    PROJECTION = "projection"


class SourceType(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    USER_SUPPLIED = "user_supplied"


class ResearchMode(str, Enum):
    NONE = "none"
    TARGETED = "targeted"
    STANDARD = "standard"
    DEEP = "deep"


class EvidenceItem(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:10]}")
    claim: str
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    source_title: str = ""
    source_url: str = ""
    publisher: str = ""
    publication_date: str = ""  # ISO date string when known, else ""
    accessed_date: datetime = Field(default_factory=_now)
    source_type: SourceType = SourceType.SECONDARY
    # Subjective assessment, not a calibrated probability.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    limitations: str = ""
    excerpt: str = ""
    conflicts_with: list[str] = Field(default_factory=list)  # other claim_ids


class ResearchQuery(BaseModel):
    query: str
    executed_at: datetime = Field(default_factory=_now)
    provider: str = ""
    cost_usd: float = 0.0


class EvidenceLedger(BaseModel):
    mode: ResearchMode = ResearchMode.NONE
    items: list[EvidenceItem] = Field(default_factory=list)
    queries: list[ResearchQuery] = Field(default_factory=list)
    notes: str = ""

    def by_id(self, claim_id: str) -> EvidenceItem | None:
        return next((i for i in self.items if i.claim_id == claim_id), None)
