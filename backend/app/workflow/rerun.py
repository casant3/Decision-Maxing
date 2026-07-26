"""Selective reruns: map a changed case-file field to the stages it can
affect, and invalidate only those. A budget change does NOT rerun research."""

from __future__ import annotations

from app.schemas.aggregate import CaseFile
from app.schemas.case_file import Constraint
from app.schemas.workflow import Stage, StageStatus

# Stages that consume each category of input. Order matters only for
# reporting; the engine reruns whatever is invalidated, in pipeline order.
_COUNCIL_FROM_COMPILE = [
    Stage.COMPILE, Stage.ADVISORS, Stage.ARGUMENT_MAP, Stage.CHAIRMAN_DRAFT,
    Stage.AUDIT, Stage.CHAIRMAN_FINAL, Stage.EXECUTOR, Stage.VALIDATE,
    Stage.PRESENT, Stage.DIRECT,
]

FIELD_STAGE_IMPACT: dict[str, list[Stage]] = {
    # Constraint/preference changes affect analysis and planning, not the
    # factual evidence base.
    "constraints": _COUNCIL_FROM_COMPILE,
    "preferences": _COUNCIL_FROM_COMPILE,
    "assumptions": _COUNCIL_FROM_COMPILE,
    # Objective changes invalidate everything including routing and research.
    "objective": [Stage.GATE, Stage.ROUTE, Stage.RESEARCH, *_COUNCIL_FROM_COMPILE],
    "decision_required": [Stage.GATE, Stage.ROUTE, Stage.RESEARCH, *_COUNCIL_FROM_COMPILE],
    # New/changed facts may warrant new research.
    "facts": [Stage.RESEARCH, *_COUNCIL_FROM_COMPILE],
}


def invalidate_for_field(case: CaseFile, field: str) -> list[Stage]:
    stages = FIELD_STAGE_IMPACT.get(field, _COUNCIL_FROM_COMPILE)
    invalidated: list[Stage] = []
    for stage in stages:
        rec = case.workflow.stages.get(stage.value)
        if rec and rec.status in (StageStatus.COMPLETE, StageStatus.SKIPPED, StageStatus.FAILED):
            rec.status = StageStatus.INVALIDATED
            rec.notes.append(f"invalidated by change to '{field}'")
            invalidated.append(stage)
    return invalidated


def apply_constraint_change(case: CaseFile, constraint: Constraint) -> list[Stage]:
    """Update (by id) or add a constraint, then invalidate affected stages."""
    for i, existing in enumerate(case.constraints):
        if existing.id == constraint.id:
            case.constraints[i] = constraint
            break
    else:
        case.constraints.append(constraint)
    return invalidate_for_field(case, "constraints")
