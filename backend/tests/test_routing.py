"""Unit tests for deterministic routing rules."""

from __future__ import annotations

from app.schemas.agents import RouterAssessment
from app.schemas.case_file import Route, StakeLevel, StakesAssessment
from app.schemas.evidence import ResearchMode
from app.workflow.routing import decide_research_mode, decide_route


def assessment(**stakes) -> RouterAssessment:
    return RouterAssessment(stakes=StakesAssessment(**stakes))


def test_low_stakes_well_defined_goes_direct():
    d = decide_route(assessment())
    assert d.route == Route.DIRECT
    assert d.advisor_roles == []
    assert "low_stakes" in d.factor_explanations


def test_factual_uncertainty_goes_research_assisted():
    d = decide_route(assessment(needs_current_information=True))
    assert d.route == Route.RESEARCH_ASSISTED


def test_moderate_stakes_goes_lightweight():
    d = decide_route(assessment(overall=StakeLevel.MEDIUM))
    assert d.route == Route.LIGHTWEIGHT_COUNCIL
    assert len(d.advisor_roles) == 3


def test_high_uncertainty_goes_lightweight():
    d = decide_route(assessment(uncertainty=StakeLevel.HIGH))
    assert d.route == Route.LIGHTWEIGHT_COUNCIL


def test_high_overall_goes_full():
    d = decide_route(assessment(overall=StakeLevel.HIGH))
    assert d.route == Route.FULL_COUNCIL
    assert len(d.advisor_roles) == 5


def test_legal_risk_forces_full_council():
    d = decide_route(assessment(legal_or_regulatory=StakeLevel.MEDIUM))
    assert d.route == Route.FULL_COUNCIL
    assert "legal_or_regulatory" in d.factor_explanations


def test_irreversible_with_money_forces_full_council():
    d = decide_route(assessment(reversibility=StakeLevel.HIGH, financial=StakeLevel.MEDIUM))
    assert d.route == Route.FULL_COUNCIL


def test_two_high_dimensions_force_full_council():
    d = decide_route(assessment(financial=StakeLevel.HIGH, personal_impact=StakeLevel.HIGH))
    assert d.route == Route.FULL_COUNCIL
    assert "multi_dimensional" in d.factor_explanations


def test_explanations_are_machine_readable():
    d = decide_route(assessment(overall=StakeLevel.HIGH))
    assert isinstance(d.factor_explanations, dict)
    assert all(isinstance(v, str) for v in d.factor_explanations.values())


def test_no_research_when_not_needed():
    a = assessment()
    assert decide_research_mode(decide_route(a), a) == ResearchMode.NONE


def test_deep_research_only_for_full_council_high_uncertainty():
    a = assessment(overall=StakeLevel.HIGH, uncertainty=StakeLevel.HIGH,
                   needs_current_information=True)
    assert decide_research_mode(decide_route(a), a) == ResearchMode.DEEP

    a2 = assessment(overall=StakeLevel.HIGH, needs_current_information=True)
    assert decide_research_mode(decide_route(a2), a2) == ResearchMode.STANDARD


def test_research_assisted_uses_targeted():
    a = assessment(needs_current_information=True)
    assert decide_research_mode(decide_route(a), a) == ResearchMode.TARGETED
