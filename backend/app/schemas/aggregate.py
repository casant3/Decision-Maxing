"""The versioned CaseFile aggregate — single source of truth for a decision."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from app.schemas.agents import (
    AdvisorResponse,
    ArgumentMap,
    AuditReport,
    ChairmanDecision,
    DirectAnswer,
    ExecutionPlan,
    GateResult,
    ValidationResult,
)
from app.schemas.case_file import (
    SCHEMA_VERSION,
    Assumption,
    CaseStatus,
    Constraint,
    ConversationTurn,
    DecisionCriterion,
    Fact,
    FactOrigin,
    OpenQuestion,
    Preference,
    RoutingDecision,
    new_id,
)
from app.schemas.evidence import EvidenceLedger
from app.schemas.workflow import WorkflowState


def _now() -> datetime:
    return datetime.now(UTC)


class AdvisorRun(BaseModel):
    """An advisor's response plus anonymisation metadata. The anonymous_id is
    what the Chairman sees; provider/model identity is never forwarded."""

    anonymous_id: str  # e.g. "advisor_1" (order randomised before Chairman review)
    response: AdvisorResponse
    provider: str = ""  # for logging/eval only — never shown to the Chairman
    model: str = ""
    failed: bool = False
    failure_reason: str = ""


class OutcomeReview(BaseModel):
    review_date: str = ""
    user_reported_outcome: str = ""
    usefulness_rating: int | None = Field(default=None, ge=1, le=5)
    constraint_adherence_score: int | None = Field(default=None, ge=1, le=5)
    factual_accuracy_score: int | None = Field(default=None, ge=1, le=5)
    actionability_score: int | None = Field(default=None, ge=1, le=5)
    decision_clarity_score: int | None = Field(default=None, ge=1, le=5)
    notes: str = ""


class CaseFile(BaseModel):
    schema_version: str = SCHEMA_VERSION
    case_id: str = Field(default_factory=lambda: new_id("case"))
    version: int = 1
    status: CaseStatus = CaseStatus.INTAKE
    title: str = ""

    # --- intake / source of truth -------------------------------------
    original_request: str = ""
    conversation: list[ConversationTurn] = Field(default_factory=list)
    conversation_summary: str = ""
    objective: str = ""
    decision_required: str = ""

    # Kept separate by design — never merged into one "facts" collection.
    user_facts: list[Fact] = Field(default_factory=list)
    verified_facts: list[Fact] = Field(default_factory=list)
    inferences: list[Fact] = Field(default_factory=list)

    preferences: list[Preference] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)

    decision_criteria: list[DecisionCriterion] = Field(default_factory=list)

    # --- workflow artefacts -------------------------------------------
    gate_result: GateResult | None = None
    routing: RoutingDecision | None = None
    evidence: EvidenceLedger = Field(default_factory=EvidenceLedger)
    advisor_runs: list[AdvisorRun] = Field(default_factory=list)
    argument_map: ArgumentMap | None = None
    chairman_draft: ChairmanDecision | None = None
    audit: AuditReport | None = None
    chairman_final: ChairmanDecision | None = None
    execution_plan: ExecutionPlan | None = None
    validation: ValidationResult | None = None
    direct_answer: DirectAnswer | None = None  # direct / research_assisted routes

    workflow: WorkflowState = Field(default_factory=WorkflowState)
    outcome: OutcomeReview | None = None

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    # ------------------------------------------------------------------
    def fact_index(self) -> dict[str, Fact]:
        return {f.id: f for f in [*self.user_facts, *self.verified_facts, *self.inferences]}

    def add_fact(self, fact: Fact) -> None:
        bucket = {
            FactOrigin.USER_CONFIRMED: self.user_facts,
            FactOrigin.EXTERNALLY_VERIFIED: self.verified_facts,
            FactOrigin.SYSTEM_INFERENCE: self.inferences,
        }[fact.origin]
        bucket.append(fact)

    def touch(self) -> None:
        self.updated_at = _now()
