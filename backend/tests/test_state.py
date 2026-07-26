"""State transitions, invalidation and the selective-rerun map."""

from __future__ import annotations

from app.schemas.aggregate import CaseFile
from app.schemas.case_file import Constraint, ConstraintKind
from app.schemas.workflow import FULL_PIPELINE, Stage, StageStatus, WorkflowState
from app.workflow.rerun import apply_constraint_change, invalidate_for_field


def completed_state(stages: list[Stage]) -> WorkflowState:
    ws = WorkflowState()
    for s in stages:
        ws.record(s).status = StageStatus.COMPLETE
    return ws


def test_invalidate_from_cascades_downstream_only():
    ws = completed_state(FULL_PIPELINE)
    invalidated = ws.invalidate_from(Stage.CHAIRMAN_DRAFT, FULL_PIPELINE)
    assert Stage.CHAIRMAN_DRAFT in invalidated
    assert Stage.EXECUTOR in invalidated
    assert ws.stages[Stage.RESEARCH.value].status == StageStatus.COMPLETE
    assert ws.stages[Stage.ADVISORS.value].status == StageStatus.COMPLETE
    assert ws.stages[Stage.AUDIT.value].status == StageStatus.INVALIDATED


def test_budget_change_does_not_invalidate_research():
    case = CaseFile(original_request="x")
    for s in FULL_PIPELINE:
        case.workflow.record(s).status = StageStatus.COMPLETE
    invalidated = invalidate_for_field(case, "constraints")
    assert Stage.RESEARCH not in invalidated
    assert case.workflow.stages[Stage.RESEARCH.value].status == StageStatus.COMPLETE
    assert Stage.ADVISORS in invalidated
    assert Stage.EXECUTOR in invalidated


def test_objective_change_invalidates_research_too():
    case = CaseFile(original_request="x")
    for s in FULL_PIPELINE:
        case.workflow.record(s).status = StageStatus.COMPLETE
    invalidated = invalidate_for_field(case, "objective")
    assert Stage.RESEARCH in invalidated


def test_constraint_change_updates_existing_by_id():
    case = CaseFile(original_request="x")
    original = Constraint(kind=ConstraintKind.BUDGET, description="budget", value="5000 USD")
    case.constraints.append(original)
    changed = original.model_copy(update={"value": "2000 USD"})
    apply_constraint_change(case, changed)
    assert len(case.constraints) == 1
    assert case.constraints[0].value == "2000 USD"


def test_constraint_change_adds_new():
    case = CaseFile(original_request="x")
    apply_constraint_change(
        case, Constraint(kind=ConstraintKind.TIME, description="time", value="10 h/week"))
    assert len(case.constraints) == 1


def test_stage_records_track_notes_on_invalidation():
    case = CaseFile(original_request="x")
    case.workflow.record(Stage.ADVISORS).status = StageStatus.COMPLETE
    invalidate_for_field(case, "constraints")
    assert any("constraints" in n for n in case.workflow.stages[Stage.ADVISORS.value].notes)
