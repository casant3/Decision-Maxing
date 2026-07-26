"""Core case-file schemas.

The CaseFile is the single source of truth for a decision. User-confirmed
facts, externally verified evidence and system inferences are kept in
separate collections by design — never merge them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


def _now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class FactOrigin(str, Enum):
    USER_CONFIRMED = "user_confirmed"
    EXTERNALLY_VERIFIED = "externally_verified"
    SYSTEM_INFERENCE = "system_inference"


class Fact(BaseModel):
    id: str = Field(default_factory=lambda: new_id("fact"))
    statement: str
    origin: FactOrigin
    # Subjective assessment, not a calibrated probability.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=_now)


class ConstraintKind(str, Enum):
    BUDGET = "budget"
    TIME = "time"
    DEADLINE = "deadline"
    SKILL = "skill"
    LEGAL = "legal"
    PERSONAL = "personal"
    OTHER = "other"


class Constraint(BaseModel):
    id: str = Field(default_factory=lambda: new_id("con"))
    kind: ConstraintKind
    description: str
    value: str | None = None  # e.g. "5000 USD", "10 h/week"
    hard: bool = True


class Preference(BaseModel):
    id: str = Field(default_factory=lambda: new_id("pref"))
    description: str
    strength: str = "moderate"  # weak | moderate | strong


class Assumption(BaseModel):
    id: str = Field(default_factory=lambda: new_id("asm"))
    statement: str
    basis: str = ""
    risk_if_wrong: str = ""


class QuestionCategory(str, Enum):
    DECISION_CRITICAL = "decision_critical"
    RESEARCHABLE = "researchable"
    INFERABLE = "inferable"


class OpenQuestion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    question: str
    category: QuestionCategory
    status: str = "open"  # open | answered | assumed
    answer: str | None = None


class StakeLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class StakesAssessment(BaseModel):
    financial: StakeLevel = StakeLevel.LOW
    reversibility: StakeLevel = StakeLevel.LOW  # high = hard to reverse
    legal_or_regulatory: StakeLevel = StakeLevel.LOW
    personal_impact: StakeLevel = StakeLevel.LOW
    uncertainty: StakeLevel = StakeLevel.LOW
    urgency: StakeLevel = StakeLevel.LOW
    needs_current_information: bool = False
    external_actions_required: bool = False
    overall: StakeLevel = StakeLevel.LOW
    rationale: str = ""


class Route(str, Enum):
    DIRECT = "direct"
    RESEARCH_ASSISTED = "research_assisted"
    LIGHTWEIGHT_COUNCIL = "lightweight_council"
    FULL_COUNCIL = "full_council"


class RoutingDecision(BaseModel):
    route: Route
    # Machine-readable explanation: factor -> why it pushed toward this route.
    factor_explanations: dict[str, str] = Field(default_factory=dict)
    rationale: str = ""
    advisor_roles: list[str] = Field(default_factory=list)
    stakes: StakesAssessment = Field(default_factory=StakesAssessment)


class ConversationTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = Field(default_factory=_now)


class CaseStatus(str, Enum):
    INTAKE = "intake"
    READY = "ready"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    COMPLETE = "complete"
    FAILED = "failed"


class DecisionCriterion(BaseModel):
    name: str
    weight: float = Field(ge=0.0, le=1.0)
    description: str = ""


DEFAULT_DECISION_CRITERIA: list[DecisionCriterion] = [
    DecisionCriterion(name="objective_alignment", weight=0.2, description="Alignment with the user's objective"),
    DecisionCriterion(name="evidence_quality", weight=0.15, description="Quality of supporting evidence"),
    DecisionCriterion(name="reasoning_quality", weight=0.1, description="Quality of causal reasoning"),
    DecisionCriterion(name="feasibility", weight=0.15, description="Practical feasibility under constraints"),
    DecisionCriterion(name="upside_potential", weight=0.1, description="Upside potential"),
    DecisionCriterion(name="downside_protection", weight=0.1, description="Downside protection"),
    DecisionCriterion(name="speed_of_learning", weight=0.1, description="How fast the user learns whether it works"),
    DecisionCriterion(name="constraint_fit", weight=0.1, description="Fit with user constraints"),
]
