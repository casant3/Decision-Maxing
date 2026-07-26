"""Schema validation tests: strict models must reject malformed data."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.agents import (
    AdvisorResponse,
    AdvisorRole,
    ChiefOfStaffReply,
    CriterionScore,
    GateResult,
    OptionScore,
)
from app.schemas.aggregate import CaseFile
from app.schemas.case_file import Fact, FactOrigin


def test_chief_of_staff_caps_questions_at_three():
    reply = ChiefOfStaffReply(questions=["a?", "b?", "c?", "d?", "e?"])
    assert len(reply.questions) == 3


def test_gate_readiness_bounds():
    with pytest.raises(ValidationError):
        GateResult(readiness_score=140, status="ready")
    with pytest.raises(ValidationError):
        GateResult(readiness_score=-5, status="ready")


def test_advisor_requires_two_separate_confidences():
    r = AdvisorResponse(role=AdvisorRole.CONTRARIAN, problem_interpretation="x",
                        recommendation="y", causal_reasoning="z",
                        evidence_confidence=0.3, reasoning_confidence=0.8)
    assert r.evidence_confidence != r.reasoning_confidence
    with pytest.raises(ValidationError):
        AdvisorResponse(role=AdvisorRole.CONTRARIAN, problem_interpretation="x",
                        recommendation="y", causal_reasoning="z", evidence_confidence=1.4)


def test_advisor_rejects_unknown_role():
    with pytest.raises(ValidationError):
        AdvisorResponse(role="devil_advocate", problem_interpretation="x",
                        recommendation="y", causal_reasoning="z")


def test_weighted_option_score():
    score = OptionScore(option_id="a", scores=[
        CriterionScore(criterion="c1", weight=0.5, score=8),
        CriterionScore(criterion="c2", weight=0.5, score=4),
    ])
    assert score.weighted_total == 6.0


def test_fact_origins_stay_separated():
    case = CaseFile(original_request="x")
    case.add_fact(Fact(statement="user said", origin=FactOrigin.USER_CONFIRMED))
    case.add_fact(Fact(statement="we inferred", origin=FactOrigin.SYSTEM_INFERENCE))
    case.add_fact(Fact(statement="web verified", origin=FactOrigin.EXTERNALLY_VERIFIED))
    assert len(case.user_facts) == 1
    assert len(case.inferences) == 1
    assert len(case.verified_facts) == 1


def test_case_file_round_trips_through_json():
    case = CaseFile(original_request="round trip")
    data = case.model_dump_json()
    restored = CaseFile.model_validate_json(data)
    assert restored.case_id == case.case_id
    assert restored.status == case.status
