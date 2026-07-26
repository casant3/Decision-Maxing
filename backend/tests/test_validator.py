"""Deterministic constraint-validator tests."""

from __future__ import annotations

from app.agents.validator import parse_hours_per_week, parse_money, validate_plan
from app.schemas.agents import (
    ActionItem,
    ChairmanAction,
    ChairmanDecision,
    ExecutionPlan,
    Milestone,
)
from app.schemas.aggregate import CaseFile
from app.schemas.case_file import Constraint, ConstraintKind
from app.schemas.evidence import EvidenceItem


def decision(**kw) -> ChairmanDecision:
    defaults = dict(action=ChairmanAction.SELECT, one_sentence_decision="do X",
                    decision="do X carefully", reasoning="because")
    defaults.update(kw)
    return ChairmanDecision(**defaults)


def plan(**kw) -> ExecutionPlan:
    defaults = dict(
        immediate_actions=[ActionItem(id="a1", title="Run pilot test", effort_hours=2,
                                      cost_estimate_usd=100)],
        success_criteria=["≥5% conversion"],
        failure_criteria=["<1% conversion"],
        total_cost_estimate_usd=100,
    )
    defaults.update(kw)
    return ExecutionPlan(**defaults)


def case_with(constraints=None, evidence=None) -> CaseFile:
    case = CaseFile(original_request="x")
    case.constraints = constraints or []
    if evidence:
        case.evidence.items = evidence
    return case


def test_valid_plan_passes():
    result = validate_plan(case_with(), plan(), decision())
    assert result.valid


def test_over_budget_flagged_to_executor():
    c = case_with([Constraint(kind=ConstraintKind.BUDGET, description="budget", value="$500")])
    result = validate_plan(c, plan(total_cost_estimate_usd=900), decision())
    assert not result.valid
    assert result.defects[0].code == "over_budget"
    assert result.defects[0].stage_to_fix == "executor"


def test_within_budget_passes():
    c = case_with([Constraint(kind=ConstraintKind.BUDGET, description="budget", value="5k USD")])
    assert validate_plan(c, plan(total_cost_estimate_usd=4000), decision()).valid


def test_over_weekly_time_flagged():
    c = case_with([Constraint(kind=ConstraintKind.TIME, description="time", value="5 hours/week")])
    p = plan(seven_day_plan=[ActionItem(id="a2", title="Test grind", effort_hours=20)])
    result = validate_plan(c, p, decision())
    assert any(d.code == "over_time_week1" for d in result.defects)


def test_unknown_dependency_flagged():
    p = plan(immediate_actions=[
        ActionItem(id="a1", title="Test step", dependencies=["ghost"], effort_hours=1)])
    result = validate_plan(case_with(), p, decision())
    assert any(d.code == "unknown_dependency" for d in result.defects)


def test_milestones_out_of_order_flagged():
    p = plan(milestones=[Milestone(title="late", due="day 20"), Milestone(title="early", due="day 3")])
    result = validate_plan(case_with(), p, decision())
    assert any(d.code == "inconsistent_deadlines" for d in result.defects)


def test_unmeasurable_criteria_flagged():
    p = plan(success_criteria=["it feels right"], failure_criteria=["it feels wrong"])
    result = validate_plan(case_with(), p, decision())
    assert any(d.code == "not_measurable" for d in result.defects)


def test_executor_cannot_silently_drop_the_experiment():
    """Chairman ordered a reversible experiment; a plan without any
    test/experiment action must be rejected and routed back to the executor."""
    d = decision(action=ChairmanAction.REVERSIBLE_EXPERIMENT,
                 decision="Run a two-week validation experiment")
    p = plan(immediate_actions=[
        ActionItem(id="a1", title="Sign long-term lease", effort_hours=2, cost_estimate_usd=50)])
    result = validate_plan(case_with(), p, d)
    defect = next(d for d in result.defects if d.code == "plan_contradicts_decision")
    assert defect.stage_to_fix == "executor"


def test_unknown_evidence_citation_flagged_to_chairman():
    c = case_with(evidence=[EvidenceItem(claim_id="ev_real", claim="real claim")])
    d = decision(evidence_claim_ids=["ev_real", "ev_hallucinated"])
    result = validate_plan(c, plan(), d)
    defect = next(x for x in result.defects if x.code == "unknown_evidence_cited")
    assert defect.stage_to_fix == "chairman_final"
    assert "ev_hallucinated" in defect.description


def test_money_parsing():
    assert parse_money("$5,000") == 5000
    assert parse_money("5k USD") == 5000
    assert parse_money("about 750 dollars") == 750
    assert parse_money("no numbers") is None


def test_hours_parsing():
    assert parse_hours_per_week("10 hours per week") == 10
    assert parse_hours_per_week("15h/week") == 15
    assert parse_hours_per_week("weekends only") is None
