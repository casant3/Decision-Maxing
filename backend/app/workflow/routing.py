"""Deterministic routing rules.

The LLM assesses stakes (RouterAssessment); the route itself is derived
here by explicit, unit-tested rules so routing is explainable and stable."""

from __future__ import annotations

from app.schemas.agents import AdvisorRole, RouterAssessment
from app.schemas.case_file import Route, RoutingDecision, StakeLevel
from app.schemas.evidence import ResearchMode

FULL_COUNCIL_ROLES = list(AdvisorRole)
LIGHTWEIGHT_ROLES = [AdvisorRole.CONTRARIAN, AdvisorRole.FIRST_PRINCIPLES, AdvisorRole.CUSTOMER_ADVOCATE]

_LEVEL = {StakeLevel.LOW: 0, StakeLevel.MEDIUM: 1, StakeLevel.HIGH: 2}


def _ge(level: StakeLevel, other: StakeLevel) -> bool:
    return _LEVEL[level] >= _LEVEL[other]


def decide_route(assessment: RouterAssessment) -> RoutingDecision:
    s = assessment.stakes
    explanations: dict[str, str] = {}

    high_dimensions = sum(
        1
        for dim, level in [
            ("financial", s.financial),
            ("reversibility", s.reversibility),
            ("legal_or_regulatory", s.legal_or_regulatory),
            ("personal_impact", s.personal_impact),
            ("uncertainty", s.uncertainty),
        ]
        if level == StakeLevel.HIGH
    )

    if s.overall == StakeLevel.HIGH:
        explanations["overall"] = "overall stakes high -> full council"
    if _ge(s.legal_or_regulatory, StakeLevel.MEDIUM):
        explanations["legal_or_regulatory"] = "legal/regulatory risk >= medium -> full council"
    if s.reversibility == StakeLevel.HIGH and _ge(s.financial, StakeLevel.MEDIUM):
        explanations["reversibility"] = "hard to reverse with financial stakes -> full council"
    if high_dimensions >= 2:
        explanations["multi_dimensional"] = f"{high_dimensions} dimensions high -> full council"

    if explanations:
        route = Route.FULL_COUNCIL
        roles = FULL_COUNCIL_ROLES
    elif s.overall == StakeLevel.MEDIUM or s.uncertainty == StakeLevel.HIGH:
        route = Route.LIGHTWEIGHT_COUNCIL
        roles = LIGHTWEIGHT_ROLES
        explanations["moderate"] = "moderate stakes or high uncertainty -> lightweight council (3 advisors)"
    elif s.needs_current_information or assessment.research_needed:
        route = Route.RESEARCH_ASSISTED
        roles = []
        explanations["factual"] = "main uncertainty is factual -> research-assisted answer"
    else:
        route = Route.DIRECT
        roles = []
        explanations["low_stakes"] = "low-stakes, well-defined, no current info needed -> direct answer"

    return RoutingDecision(
        route=route,
        factor_explanations=explanations,
        rationale=s.rationale or assessment.research_rationale,
        advisor_roles=[r.value for r in roles],
        stakes=s,
    )


def decide_research_mode(routing: RoutingDecision, assessment: RouterAssessment) -> ResearchMode:
    if not (assessment.research_needed or routing.stakes.needs_current_information):
        return ResearchMode.NONE
    if routing.route == Route.RESEARCH_ASSISTED:
        return ResearchMode.TARGETED
    if routing.route == Route.FULL_COUNCIL and routing.stakes.uncertainty == StakeLevel.HIGH:
        # Deep research is never the default — only for full council + high uncertainty.
        return ResearchMode.DEEP
    if routing.route in (Route.FULL_COUNCIL, Route.LIGHTWEIGHT_COUNCIL):
        return ResearchMode.STANDARD
    return ResearchMode.TARGETED
