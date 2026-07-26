"""Constraint Validator — deterministic (no LLM call).

Checks the execution plan against the user's constraints and the
Chairman's final decision. Returns valid, or defects each tagged with the
single stage to rerun — never the whole council."""

from __future__ import annotations

import re

from app.schemas.agents import (
    ChairmanAction,
    ChairmanDecision,
    ExecutionPlan,
    ValidationDefect,
    ValidationResult,
)
from app.schemas.aggregate import CaseFile
from app.schemas.case_file import ConstraintKind
from app.schemas.workflow import Stage

_EXPERIMENT_WORDS = re.compile(r"experiment|test|validat|interview|pilot|prototype|smoke", re.I)
_MEASURABLE = re.compile(r"[0-9]|≥|≤|>|<|%")


def parse_money(text: str) -> float | None:
    m = re.search(r"[$€£]?\s*([0-9][0-9,.]*)\s*(k|K)?", text or "")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    if m.group(2):
        value *= 1000
    return value


def parse_hours_per_week(text: str) -> float | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:h|hr|hrs|hours?)\s*(?:/|per\s*)?\s*(?:week|wk|w)\b", text or "", re.I)
    return float(m.group(1)) if m else None


def _milestone_day(due: str) -> int | None:
    m = re.search(r"day\s*([0-9]+)", due or "", re.I)
    return int(m.group(1)) if m else None


def validate_plan(case: CaseFile, plan: ExecutionPlan, final: ChairmanDecision) -> ValidationResult:
    defects: list[ValidationDefect] = []

    # --- budget -------------------------------------------------------
    total_cost = plan.total_cost_estimate_usd or sum(a.cost_estimate_usd for a in plan.all_actions)
    for c in case.constraints:
        if c.kind == ConstraintKind.BUDGET:
            budget = parse_money(c.value or c.description)
            if budget is not None and total_cost > budget:
                defects.append(ValidationDefect(
                    code="over_budget",
                    description=f"Plan cost ${total_cost:.0f} exceeds budget ${budget:.0f} ({c.id})",
                    stage_to_fix=Stage.EXECUTOR.value,
                ))

    # --- time ---------------------------------------------------------
    for c in case.constraints:
        if c.kind == ConstraintKind.TIME:
            weekly = parse_hours_per_week(c.value or c.description)
            if weekly is None:
                continue
            week1 = sum(a.effort_hours for a in [*plan.immediate_actions, *plan.seven_day_plan])
            month = week1 + sum(a.effort_hours for a in plan.thirty_day_plan)
            if week1 > weekly * 1.2:  # 20% tolerance on a single week
                defects.append(ValidationDefect(
                    code="over_time_week1",
                    description=f"First-week effort {week1:.0f}h exceeds available {weekly:.0f}h/week ({c.id})",
                    stage_to_fix=Stage.EXECUTOR.value,
                ))
            if month > weekly * 4.5:
                defects.append(ValidationDefect(
                    code="over_time_month",
                    description=f"30-day effort {month:.0f}h exceeds ~{weekly * 4:.0f}h available ({c.id})",
                    stage_to_fix=Stage.EXECUTOR.value,
                ))

    # --- internal consistency ----------------------------------------
    action_ids = {a.id for a in plan.all_actions}
    for a in plan.all_actions:
        for dep in a.dependencies:
            if dep not in action_ids:
                defects.append(ValidationDefect(
                    code="unknown_dependency",
                    description=f"Action {a.id} depends on unknown action '{dep}'",
                    stage_to_fix=Stage.EXECUTOR.value,
                ))
    days = [d for d in (_milestone_day(m.due) for m in plan.milestones) if d is not None]
    if days != sorted(days):
        defects.append(ValidationDefect(
            code="inconsistent_deadlines",
            description="Milestone days are not in chronological order",
            stage_to_fix=Stage.EXECUTOR.value,
        ))

    # --- measurability ------------------------------------------------
    criteria = [*plan.success_criteria, *plan.failure_criteria]
    if not criteria or not any(_MEASURABLE.search(x) for x in criteria):
        defects.append(ValidationDefect(
            code="not_measurable",
            description="Success/failure criteria contain no measurable thresholds",
            stage_to_fix=Stage.EXECUTOR.value,
        ))

    # --- plan must not contradict the Chairman's decision -------------
    # Heuristic: an experiment-style decision requires at least one
    # experiment-style action in the plan.
    decision_is_experiment = (
        final.action == ChairmanAction.REVERSIBLE_EXPERIMENT
        or _EXPERIMENT_WORDS.search(final.decision or "")
    )
    plan_text = " ".join(f"{a.title} {a.description}" for a in plan.all_actions)
    if decision_is_experiment and not _EXPERIMENT_WORDS.search(plan_text):
        defects.append(ValidationDefect(
            code="plan_contradicts_decision",
            description="Chairman decided on a validation experiment but the plan contains no experiment/test actions",
            stage_to_fix=Stage.EXECUTOR.value,
        ))

    # --- unsupported claims cited as facts ----------------------------
    known_claims = {i.claim_id for i in case.evidence.items}
    bogus = [cid for cid in final.evidence_claim_ids if cid not in known_claims]
    if bogus:
        defects.append(ValidationDefect(
            code="unknown_evidence_cited",
            description=f"Decision cites evidence ids not in the ledger: {bogus}",
            stage_to_fix=Stage.CHAIRMAN_FINAL.value,
        ))

    return ValidationResult(valid=not defects, defects=defects)
