"""Structured output schemas for every agent. All model outputs are
validated against these — malformed data is never silently accepted."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.case_file import (
    Assumption,
    Constraint,
    Fact,
    OpenQuestion,
    Preference,
    StakesAssessment,
)

# ---------------------------------------------------------------- Chief of Staff


class CaseUpdate(BaseModel):
    """What the Chief of Staff extracted from the latest user message."""

    objective: str | None = None
    decision_required: str | None = None
    new_facts: list[Fact] = Field(default_factory=list)
    new_constraints: list[Constraint] = Field(default_factory=list)
    new_preferences: list[Preference] = Field(default_factory=list)
    new_assumptions: list[Assumption] = Field(default_factory=list)
    new_open_questions: list[OpenQuestion] = Field(default_factory=list)
    answered_question_ids: list[str] = Field(default_factory=list)
    conversation_summary: str = ""


class ChiefOfStaffReply(BaseModel):
    update: CaseUpdate = Field(default_factory=CaseUpdate)
    message_to_user: str = ""
    # Questions only when two plausible answers would change the recommendation.
    questions: list[str] = Field(default_factory=list)
    ready_to_proceed: bool = False

    @field_validator("questions")
    @classmethod
    def max_three_questions(cls, v: list[str]) -> list[str]:
        return v[:3]


# ---------------------------------------------------------------- Context Gate


class ReadinessStatus(str, Enum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    BLOCKED = "blocked"


class GateResult(BaseModel):
    # Heuristic score 0-100; explicitly not a scientific probability.
    readiness_score: int = Field(ge=0, le=100)
    status: ReadinessStatus
    critical_missing: list[str] = Field(default_factory=list)
    safe_assumptions: list[Assumption] = Field(default_factory=list)
    next_question: str | None = None
    rationale: str = ""


# ---------------------------------------------------------------- Router

class RouterAssessment(BaseModel):
    """Model-produced stakes assessment; the route itself is derived by
    deterministic, unit-tested rules in workflow/routing.py."""

    stakes: StakesAssessment = Field(default_factory=StakesAssessment)
    research_needed: bool = False
    research_rationale: str = ""


# ---------------------------------------------------------------- Advisors


class AdvisorRole(str, Enum):
    CONTRARIAN = "contrarian"
    FIRST_PRINCIPLES = "first_principles"
    EXPANSIONIST = "expansionist"
    OUTSIDER = "outsider"
    CUSTOMER_ADVOCATE = "customer_advocate"


class AdvisorResponse(BaseModel):
    role: AdvisorRole
    problem_interpretation: str
    recommendation: str
    causal_reasoning: str
    evidence_claim_ids: list[str] = Field(default_factory=list)
    user_fact_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    main_risks: list[str] = Field(default_factory=list)
    strongest_counterargument: str = ""
    cheapest_useful_test: str = ""
    evidence_that_would_change_recommendation: str = ""
    # Two separate subjective confidences — never one generic score, and
    # never to be read as calibrated probabilities.
    evidence_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------- Argument Mapper


class StrategicOption(BaseModel):
    option_id: str
    label: str
    summary: str
    supporting_advisors: list[str] = Field(default_factory=list)  # anonymised ids
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class ConvergenceNote(BaseModel):
    conclusion: str
    advisors: list[str] = Field(default_factory=list)
    independent_reasoning: bool = False
    note: str = ""


class ArgumentMap(BaseModel):
    options: list[StrategicOption] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    unique_insights: list[str] = Field(default_factory=list)
    critical_assumptions: list[str] = Field(default_factory=list)
    unresolved_research_gaps: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    incompatible_recommendations: list[str] = Field(default_factory=list)
    convergence: list[ConvergenceNote] = Field(default_factory=list)


# ---------------------------------------------------------------- Chairman


class ChairmanAction(str, Enum):
    SELECT = "select"
    COMBINE = "combine"
    REJECT_ALL = "reject_all"
    REVERSIBLE_EXPERIMENT = "reversible_experiment"
    REQUEST_RESEARCH = "request_research"


class CriterionScore(BaseModel):
    criterion: str
    weight: float = Field(ge=0.0, le=1.0)
    score: float = Field(ge=0.0, le=10.0)
    note: str = ""


class OptionScore(BaseModel):
    option_id: str
    scores: list[CriterionScore] = Field(default_factory=list)

    @property
    def weighted_total(self) -> float:
        return round(sum(s.weight * s.score for s in self.scores), 3)


class RejectedOption(BaseModel):
    option_id: str
    reason: str


class ChairmanDecision(BaseModel):
    action: ChairmanAction
    one_sentence_decision: str
    decision: str
    reasoning: str
    option_scores: list[OptionScore] = Field(default_factory=list)
    adopted_components: list[str] = Field(default_factory=list)
    rejected_options: list[RejectedOption] = Field(default_factory=list)
    critical_assumptions: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    evidence_claim_ids: list[str] = Field(default_factory=list)
    immediate_next_step: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    stop_criteria: list[str] = Field(default_factory=list)
    evidence_that_would_reverse: str = ""
    evidence_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    decision_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------- Auditor


class DefectSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class AuditDefect(BaseModel):
    severity: DefectSeverity
    description: str
    required_correction: str


class PreMortem(BaseModel):
    most_likely_failure_cause: str
    earliest_warning_signs: list[str] = Field(default_factory=list)
    preventable_failures: list[str] = Field(default_factory=list)
    mitigations: list[str] = Field(default_factory=list)
    still_worth_attempting: bool = True
    note: str = ""


class AuditReport(BaseModel):
    matches_user_objective: bool = True
    constraint_violations: list[str] = Field(default_factory=list)
    unsupported_conclusions: list[str] = Field(default_factory=list)
    misrepresented_sources: list[str] = Field(default_factory=list)
    unfairly_rejected_alternatives: list[str] = Field(default_factory=list)
    assumptions_treated_as_facts: list[str] = Field(default_factory=list)
    uncertainty_adequately_explained: bool = True
    next_step_reversible: bool = True
    criteria_measurable: bool = True
    unnecessary_downside_exposure: list[str] = Field(default_factory=list)
    premortem: PreMortem
    defects: list[AuditDefect] = Field(default_factory=list)
    verdict: str = "pass"  # pass | revise


# ---------------------------------------------------------------- Executor


class ActionItem(BaseModel):
    id: str
    title: str
    description: str = ""
    owner: str = "user"
    effort_hours: float = 0.0
    cost_estimate_usd: float = 0.0
    dependencies: list[str] = Field(default_factory=list)  # other action ids


class Milestone(BaseModel):
    title: str
    due: str = ""  # e.g. "day 7"
    measure: str = ""


class ExecutionPlan(BaseModel):
    immediate_actions: list[ActionItem] = Field(default_factory=list)
    seven_day_plan: list[ActionItem] = Field(default_factory=list)
    thirty_day_plan: list[ActionItem] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    failure_criteria: list[str] = Field(default_factory=list)
    review_criteria: list[str] = Field(default_factory=list)
    total_cost_estimate_usd: float = 0.0
    total_effort_hours: float = 0.0
    notes: str = ""

    @property
    def all_actions(self) -> list[ActionItem]:
        return [*self.immediate_actions, *self.seven_day_plan, *self.thirty_day_plan]


# ---------------------------------------------------------------- Constraint Validator


class ValidationDefect(BaseModel):
    code: str  # e.g. over_budget, over_time, inconsistent_deadline
    description: str
    stage_to_fix: str  # workflow stage name to rerun


class ValidationResult(BaseModel):
    valid: bool
    defects: list[ValidationDefect] = Field(default_factory=list)


# ---------------------------------------------------------------- Direct/synthesis answer


class DirectAnswer(BaseModel):
    """Used by the direct and research_assisted routes."""

    recommendation: str
    reasoning: str
    assumptions: list[str] = Field(default_factory=list)
    main_risks: list[str] = Field(default_factory=list)
    immediate_next_step: str = ""
    evidence_claim_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
