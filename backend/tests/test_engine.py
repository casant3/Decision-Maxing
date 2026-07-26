"""Workflow-engine integration tests (full runs on the mock provider)."""

from __future__ import annotations

from collections.abc import Callable

from app.prompts.templates import _anonymised_responses
from app.providers.base import ProviderError, ProviderRequest
from app.providers.mock import MockProvider
from app.providers.registry import ProviderRegistry
from app.schemas.agents import AdvisorResponse, AdvisorRole
from app.schemas.aggregate import AdvisorRun
from app.schemas.case_file import CaseStatus, Constraint, ConstraintKind, Route
from app.schemas.workflow import Stage
from app.workflow.engine import WorkflowEngine
from app.workflow.rerun import apply_constraint_change
from tests.conftest import make_ready_case, tight_budget

HIGH_STAKES = {
    "stakes": {"financial": "high", "reversibility": "high", "legal_or_regulatory": "low",
               "personal_impact": "high", "uncertainty": "high", "urgency": "low",
               "needs_current_information": True, "external_actions_required": False,
               "overall": "high", "rationale": "big irreversible bet"},
    "research_needed": True, "research_rationale": "need current data",
}


class SelectiveFailMock(MockProvider):
    """Fails deterministically for requests matching a predicate."""

    def __init__(self, fail_when: Callable[[ProviderRequest], bool]):
        super().__init__()
        self.fail_when = fail_when

    async def _call(self, req: ProviderRequest):
        if self.fail_when(req):
            raise ProviderError("injected failure", retryable=False)
        return await super()._call(req)


def build_engine(repo, settings, mock) -> WorkflowEngine:
    return WorkflowEngine(repo, ProviderRegistry(settings, mock), settings)


# ------------------------------------------------------------- intake

async def test_intake_asks_question_then_proceeds(engine):
    case = await engine.create_case("Should I start a meal-prep business?")
    assert case.status == CaseStatus.INTAKE
    assert "?" in case.conversation[-1].content  # one clarifying question
    case = await engine.handle_user_message(case, "I have $5000 and 10 hours/week")
    assert case.status == CaseStatus.READY
    assert case.workflow.usage.clarification_rounds == 1


async def test_clarification_budget_forces_progress(repo, mock_provider):
    settings = tight_budget(max_clarification_rounds=1)
    engine = build_engine(repo, settings, mock_provider)
    # Gate never satisfied, Chief of Staff never ready...
    for _ in range(3):
        mock_provider.queue_response("GateResult", {
            "readiness_score": 30, "status": "needs_clarification",
            "critical_missing": ["everything"], "safe_assumptions": [],
            "next_question": "More detail?", "rationale": "vague"})
        mock_provider.queue_response("ChiefOfStaffReply", {
            "update": {}, "message_to_user": "Tell me more", "questions": ["More?"],
            "ready_to_proceed": False})
    case = await engine.create_case("vague request")
    assert case.status == CaseStatus.INTAKE
    # ...but the round budget forces progress on labelled assumptions.
    case = await engine.handle_user_message(case, "still vague")
    assert case.status == CaseStatus.READY
    assert any("clarification budget" in d for d in case.workflow.degradations)


# ------------------------------------------------------------- full runs

async def test_lightweight_council_run_completes(engine):
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    assert case.routing.route == Route.LIGHTWEIGHT_COUNCIL
    assert len([r for r in case.advisor_runs if not r.failed]) == 3
    # Draft and final are both preserved for debugging/evaluation.
    assert case.chairman_draft is not None
    assert case.chairman_final is not None
    assert case.audit is not None
    assert case.execution_plan is not None
    assert case.validation.valid
    assert case.version > 1  # every stage produced an auditable version


async def test_full_council_runs_five_advisors(engine, mock_provider):
    mock_provider.queue_response("RouterAssessment", HIGH_STAKES)
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    assert case.routing.route == Route.FULL_COUNCIL
    assert len(case.advisor_runs) == 5
    ids = sorted(r.anonymous_id for r in case.advisor_runs)
    assert ids == [f"advisor_{i}" for i in range(1, 6)]
    lenses = {r.response.role for r in case.advisor_runs}
    assert lenses == set(AdvisorRole)


async def test_chairman_never_sees_provider_identity():
    runs = [AdvisorRun(anonymous_id="advisor_1",
                       response=AdvisorResponse(role=AdvisorRole.CONTRARIAN,
                                                problem_interpretation="i",
                                                recommendation="r", causal_reasoning="c"),
                       provider="xai", model="grok-4")]
    rendered = _anonymised_responses(runs)
    assert "xai" not in rendered
    assert "grok-4" not in rendered
    assert "advisor_1" in rendered


# ------------------------------------------------------------- failures

async def test_partial_provider_failure_continues(repo, settings):
    mock = SelectiveFailMock(
        lambda req: "as the contrarian advisor" in req.prompt.lower())
    engine = build_engine(repo, settings, mock)
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    failed = [r for r in case.advisor_runs if r.failed]
    assert len(failed) == 1
    assert failed[0].response.role == AdvisorRole.CONTRARIAN
    assert any("contrarian" in f for f in case.workflow.failures)  # recorded, not silent


async def test_quorum_failure_fails_pipeline(repo, settings):
    mock = SelectiveFailMock(lambda req: req.schema_name == "AdvisorResponse")
    engine = build_engine(repo, settings, mock)
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.FAILED
    assert any("advisors succeeded" in f for f in case.workflow.failures)


async def test_failed_run_resumes_without_rerunning_advisors(repo, settings):
    mock = SelectiveFailMock(lambda req: req.schema_name == "ChairmanDecision")
    engine = build_engine(repo, settings, mock)
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.FAILED
    advisor_attempts = case.workflow.stages[Stage.ADVISORS.value].attempts

    mock.fail_when = lambda req: False  # provider recovers
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    # Resumed from the failed stage; advisors were NOT rerun.
    assert case.workflow.stages[Stage.ADVISORS.value].attempts == advisor_attempts


# ------------------------------------------------------------- budgets

async def test_budget_skips_audit_and_degrades_gracefully(repo, mock_provider):
    settings = tight_budget(max_model_calls=12)
    engine = build_engine(repo, settings, mock_provider)
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    assert any("audit skipped" in d for d in case.workflow.degradations)
    assert case.audit is None
    assert case.chairman_final is not None  # draft adopted as final


async def test_budget_exhaustion_without_draft_fails_cleanly(repo, mock_provider):
    settings = tight_budget(max_model_calls=11)
    engine = build_engine(repo, settings, mock_provider)
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.FAILED
    assert any("budget" in f.lower() or "max_model_calls" in f for f in case.workflow.failures)


# ------------------------------------------------------------- selective rerun

async def test_constraint_change_midway_reruns_only_affected_stages(engine, repo):
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    research_attempts = case.workflow.stages[Stage.RESEARCH.value].attempts
    advisor_attempts = case.workflow.stages[Stage.ADVISORS.value].attempts

    apply_constraint_change(case, Constraint(kind=ConstraintKind.BUDGET,
                                             description="total budget", value="$10,000"))
    case.status = CaseStatus.READY
    await repo.save(case, "constraint changed")
    case = await engine.run_pipeline(case)

    assert case.status == CaseStatus.COMPLETE
    assert case.workflow.stages[Stage.RESEARCH.value].attempts == research_attempts  # untouched
    assert case.workflow.stages[Stage.ADVISORS.value].attempts == advisor_attempts + 1


async def test_unresolvable_constraint_surfaces_defects(engine, repo):
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    # Budget far below what any plan costs; the executor's mock plan stays at $200.
    apply_constraint_change(case, Constraint(kind=ConstraintKind.BUDGET,
                                             description="total budget", value="$50"))
    case.status = CaseStatus.READY
    await repo.save(case, "constraint changed")
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE  # finishes, but honestly flagged
    assert case.validation is not None and not case.validation.valid
    assert any("validation defects unresolved" in f for f in case.workflow.failures)


# ------------------------------------------------------------- executor guard

async def test_validator_forces_executor_rerun_on_strategy_drift(engine, mock_provider):
    bad_plan = {
        "immediate_actions": [{"id": "a1", "title": "Sign office lease",
                               "description": "Commit to a 12-month lease",
                               "effort_hours": 2, "cost_estimate_usd": 100}],
        "success_criteria": ["≥5% conversion"],
        "failure_criteria": ["<1% conversion"],
        "total_cost_estimate_usd": 100,
    }
    mock_provider.queue_response("ExecutionPlan", bad_plan)
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    # First plan dropped the experiment -> validator bounced it back to the
    # executor only; the rerun produced a compliant plan.
    assert case.workflow.stages[Stage.EXECUTOR.value].attempts == 2
    assert case.workflow.stages[Stage.ADVISORS.value].attempts == 1
    assert case.validation.valid
    plan_text = " ".join(a.title for a in case.execution_plan.all_actions)
    assert "lease" not in plan_text.lower()


# ------------------------------------------------------------- events & versions

async def test_events_and_versions_are_logged(engine, repo, db_session):
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    events = await repo.events(case.case_id)
    types = {e.event_type for e in events}
    assert {"case_created", "intake_turn", "routed", "pipeline_complete"} <= types
    reloaded = await repo.load(case.case_id)
    assert reloaded.version == case.version
    old = await repo.load(case.case_id, version=1)
    assert old is not None and old.status == CaseStatus.INTAKE


async def test_direct_route_skips_council(engine, mock_provider):
    mock_provider.queue_response("RouterAssessment", {
        "stakes": {"financial": "low", "reversibility": "low", "legal_or_regulatory": "low",
                   "personal_impact": "low", "uncertainty": "low", "urgency": "low",
                   "needs_current_information": False, "external_actions_required": False,
                   "overall": "low", "rationale": "trivial"},
        "research_needed": False, "research_rationale": ""})
    case = await make_ready_case(engine)
    case = await engine.run_pipeline(case)
    assert case.status == CaseStatus.COMPLETE
    assert case.routing.route == Route.DIRECT
    assert case.advisor_runs == []
    assert case.direct_answer is not None
    assert Stage.ADVISORS.value not in case.workflow.stages
