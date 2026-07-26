"""Compose the user-facing response deterministically from structured
stage outputs. No LLM call — the presented answer cannot drift from the
audited decision."""

from __future__ import annotations

from app.schemas.aggregate import CaseFile
from app.schemas.case_file import Route
from app.schemas.presentation import UserFacingResponse

CONFIDENCE_DISCLAIMER = (
    "Confidence values are the council's subjective assessments, not calibrated probabilities."
)


def _confidence_words(x: float) -> str:
    if x >= 0.75:
        return "high"
    if x >= 0.5:
        return "moderate"
    return "low"


def build_response(case: CaseFile) -> UserFacingResponse:
    route = case.routing.route if case.routing else Route.DIRECT
    if route in (Route.DIRECT, Route.RESEARCH_ASSISTED):
        return _from_direct(case)
    return _from_council(case)


def _from_direct(case: CaseFile) -> UserFacingResponse:
    d = case.direct_answer
    assert d is not None
    plan = case.execution_plan
    return UserFacingResponse(
        recommendation=d.recommendation,
        why_this_won=d.reasoning,
        council_disagreements=[],
        immediate_next_action=d.immediate_next_step,
        seven_day_plan=[a.title for a in plan.seven_day_plan] if plan else [],
        test_and_success_criteria=plan.success_criteria if plan else [],
        main_risks=d.main_risks,
        assumptions_and_unknowns=d.assumptions,
        confidence_explanation=(
            f"Confidence {_confidence_words(d.confidence)} ({d.confidence:.0%}). "
            + CONFIDENCE_DISCLAIMER
        ),
    )


def _from_council(case: CaseFile) -> UserFacingResponse:
    final = case.chairman_final
    assert final is not None
    plan = case.execution_plan
    amap = case.argument_map

    why = final.reasoning
    if final.rejected_options:
        rejected = "; ".join(f"{r.option_id}: {r.reason}" for r in final.rejected_options)
        why += f"\n\nRejected alternatives — {rejected}"

    assumptions = list(dict.fromkeys([
        *final.critical_assumptions,
        *(a.statement for a in case.assumptions),
        *(q.question for q in case.open_questions if q.status == "open"),
    ]))

    return UserFacingResponse(
        recommendation=final.one_sentence_decision or final.decision,
        why_this_won=why,
        council_disagreements=amap.disagreements if amap else [],
        immediate_next_action=final.immediate_next_step
        or (plan.immediate_actions[0].title if plan and plan.immediate_actions else ""),
        seven_day_plan=[a.title for a in [*plan.immediate_actions, *plan.seven_day_plan]] if plan else [],
        test_and_success_criteria=[*final.success_criteria,
                                   *(f"Stop if: {s}" for s in final.stop_criteria)],
        main_risks=final.key_risks,
        assumptions_and_unknowns=assumptions[:10],
        confidence_explanation=(
            f"Decision confidence {_confidence_words(final.decision_confidence)} "
            f"({final.decision_confidence:.0%}); evidence confidence "
            f"{_confidence_words(final.evidence_confidence)} ({final.evidence_confidence:.0%}). "
            f"Evidence that would reverse this: {final.evidence_that_would_reverse or 'not stated'}. "
            + CONFIDENCE_DISCLAIMER
        ),
    )
