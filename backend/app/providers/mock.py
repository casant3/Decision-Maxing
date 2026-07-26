"""Deterministic mock provider.

Two layers:
1. A playbook of realistic canned responses per agent schema, so the full
   workflow runs end-to-end offline with meaningful demo content.
2. A generic JSON-schema-driven factory as fallback for any other schema.

Tests can queue explicit responses with `queue_response`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from app.providers.base import (
    ProviderAdapter,
    ProviderRequest,
    ProviderResult,
    ResearchProvider,
    Usage,
)

ADVISOR_ROLES = ["contrarian", "first_principles", "expansionist", "outsider", "customer_advocate"]


def _instance_from_schema(schema: dict[str, Any], defs: dict[str, Any] | None = None) -> Any:
    """Build a minimal valid instance from a JSON schema (pydantic v2 output)."""
    defs = defs or schema.get("$defs", {})
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return _instance_from_schema(defs[ref], defs)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "anyOf" in schema:
        # Prefer the non-null branch so required content is present.
        branches = [b for b in schema["anyOf"] if b.get("type") != "null"]
        return _instance_from_schema(branches[0], defs) if branches else None
    t = schema.get("type")
    if t == "object":
        out = {}
        required = set(schema.get("required", []))
        for name, prop in schema.get("properties", {}).items():
            if name in required or "default" not in prop:
                out[name] = _instance_from_schema(prop, defs)
            else:
                out[name] = prop["default"]
        return out
    if t == "string":
        return schema.get("default", "mock value")
    if t == "number":
        lo, hi = schema.get("minimum", 0.0), schema.get("maximum", 1.0)
        return round((lo + hi) / 2, 2)
    if t == "integer":
        lo = schema.get("minimum", 0)
        hi = schema.get("maximum", lo + 10)
        return int((lo + hi) // 2)
    if t == "boolean":
        return schema.get("default", True)
    if t == "array":
        if schema.get("minItems", 0) > 0:
            return [_instance_from_schema(schema.get("items", {}), defs)]
        return []
    if t == "null":
        return None
    return None


def _detect_role(prompt: str) -> str:
    for role in ADVISOR_ROLES:
        if role in prompt.lower():
            return role
    return "contrarian"


class MockProvider(ProviderAdapter, ResearchProvider):
    name = "mock"

    def __init__(self) -> None:
        super().__init__(max_retries=0)
        self.call_counts: dict[str, int] = defaultdict(int)
        self.queued: dict[str, list[dict[str, Any] | Exception]] = defaultdict(list)
        self.calls: list[ProviderRequest] = []  # inspection in tests

    def queue_response(self, schema_name: str, response: dict[str, Any] | Exception) -> None:
        self.queued[schema_name].append(response)

    async def _call(self, req: ProviderRequest) -> ProviderResult:
        self.calls.append(req)
        name = req.schema_name or "text"
        idx = self.call_counts[name]
        self.call_counts[name] += 1

        if self.queued[name]:
            item = self.queued[name].pop(0)
            if isinstance(item, Exception):
                raise item
            payload = item
        elif req.json_schema is not None:
            payload = self._playbook(name, req.prompt, idx) or _instance_from_schema(req.json_schema)
        else:
            payload = None

        text = json.dumps(payload) if payload is not None else f"[mock:{self.name}] plain text answer"
        usage = Usage(input_tokens=len(req.prompt) // 4, output_tokens=len(text) // 4, cost_usd=0.0)
        return ProviderResult(text=text, model=req.model, provider=self.name, usage=usage)

    async def research(self, query: str, mode: str, timeout_s: float = 120.0) -> ProviderResult:
        text = (
            f"Mock research findings for query: {query}\n"
            "1. Market interest in this area grew ~18% year-over-year (Mock Industry Report, 2026). "
            "https://example.com/report\n"
            "2. Typical entrants reach first revenue within 3-6 months (Mock Founder Survey, 2025). "
            "https://example.com/survey\n"
        )
        return ProviderResult(
            text=text, model="mock-model", provider=self.name,
            usage=Usage(input_tokens=50, output_tokens=120, cost_usd=0.0),
        )

    # ------------------------------------------------------------ playbook

    def _playbook(self, name: str, prompt: str, idx: int) -> dict[str, Any] | None:
        if name == "ChiefOfStaffReply":
            if idx == 0:
                return {
                    "update": {
                        "objective": "Reach a sound, actionable decision on the user's request",
                        "decision_required": "Choose the best course of action for the stated goal",
                        "new_facts": [{"statement": "User stated the request in the opening message",
                                       "origin": "user_confirmed"}],
                        "conversation_summary": "User described their decision; intake started.",
                    },
                    "message_to_user": "Got it. One thing that would change my recommendation:",
                    "questions": ["What budget and time can you realistically commit to this?"],
                    "ready_to_proceed": False,
                }
            return {
                "update": {
                    "new_facts": [{"statement": "User provided budget/time commitment details",
                                   "origin": "user_confirmed"}],
                    "conversation_summary": "User clarified constraints; case is ready.",
                },
                "message_to_user": "Thanks — that's everything I need. Convening the council.",
                "questions": [],
                "ready_to_proceed": True,
            }

        if name == "GateResult":
            if idx == 0 and "budget" not in prompt.lower():
                return {
                    "readiness_score": 55, "status": "needs_clarification",
                    "critical_missing": ["budget or time constraints"],
                    "safe_assumptions": [],
                    "next_question": "What budget and time can you commit?",
                    "rationale": "Constraints could materially change the recommendation.",
                }
            return {
                "readiness_score": 82, "status": "ready", "critical_missing": [],
                "safe_assumptions": [{"statement": "User can dedicate consistent weekly time",
                                      "basis": "typical for this decision type",
                                      "risk_if_wrong": "timeline slips"}],
                "next_question": None,
                "rationale": "Objective, decision and constraints are clear enough to proceed.",
            }

        if name == "RouterAssessment":
            return {
                "stakes": {
                    "financial": "medium", "reversibility": "medium",
                    "legal_or_regulatory": "low", "personal_impact": "medium",
                    "uncertainty": "high", "urgency": "low",
                    "needs_current_information": True, "external_actions_required": False,
                    "overall": "medium",
                    "rationale": "Meaningful stakes and high uncertainty; current market data helps.",
                },
                "research_needed": True,
                "research_rationale": "Current market conditions affect the recommendation.",
            }

        if name == "EvidenceExtraction":
            return {
                "items": [
                    {"claim": "Market interest in this area grew ~18% year-over-year",
                     "status": "supported", "source_title": "Mock Industry Report 2026",
                     "source_url": "https://example.com/report", "publisher": "Mock Research Inc",
                     "publication_date": "2026-03-01", "source_type": "secondary",
                     "confidence": 0.7, "limitations": "Single industry report; methodology not public",
                     "excerpt": "Interest grew approximately 18% YoY."},
                    {"claim": "Typical entrants reach first revenue within 3-6 months",
                     "status": "partially_supported", "source_title": "Mock Founder Survey 2025",
                     "source_url": "https://example.com/survey", "publisher": "Mock Surveys",
                     "publication_date": "2025-11-15", "source_type": "secondary",
                     "confidence": 0.55, "limitations": "Self-reported survey data",
                     "excerpt": "Median time to first revenue: 4.5 months."},
                ],
                "notes": "Mock research normalised into two claims.",
            }

        if name == "AdvisorResponse":
            role = _detect_role(prompt)
            per_role = {
                "contrarian": ("The obvious path may overestimate demand.",
                               "Validate demand with a two-week smoke test before committing resources."),
                "first_principles": ("Strip to fundamentals: what must be true for this to work.",
                                     "Start with the smallest version that tests the core value hypothesis."),
                "expansionist": ("There is a larger adjacent opportunity if the core works.",
                                 "Pursue the core first; design it so adjacent segments can be added later."),
                "outsider": ("Subscription-box economics transfer here: retention beats acquisition.",
                             "Borrow a retention-first mechanism from another industry for the launch."),
                "customer_advocate": ("Customers only switch when pain exceeds switching friction.",
                                      "Interview 10 target customers before building anything."),
            }
            interp, rec = per_role[role]
            return {
                "role": role,
                "problem_interpretation": interp,
                "recommendation": rec,
                "causal_reasoning": f"As the {role} lens: {interp} Therefore: {rec}",
                "evidence_claim_ids": [], "user_fact_ids": [],
                "assumptions": [f"{role} assumption: the stated constraints are accurate"],
                "main_risks": ["The cheapest test may produce a false negative"],
                "strongest_counterargument": "Speed of commitment sometimes beats validation.",
                "cheapest_useful_test": "A one-week landing-page or interview test",
                "evidence_that_would_change_recommendation": "Strong pre-orders or verified waitlist demand",
                "evidence_confidence": 0.5, "reasoning_confidence": 0.65,
            }

        if name == "ArgumentMap":
            return {
                "options": [
                    {"option_id": "opt_validate_first", "label": "Validate demand first",
                     "summary": "Run a cheap demand test before committing",
                     "supporting_advisors": ["advisor_1", "advisor_2", "advisor_5"]},
                    {"option_id": "opt_commit_now", "label": "Commit now",
                     "summary": "Move directly to execution to capture timing advantage",
                     "supporting_advisors": ["advisor_3"]},
                ],
                "agreements": ["The core value hypothesis is untested"],
                "disagreements": ["Whether speed matters more than validation"],
                "unique_insights": ["Retention-first mechanics from adjacent industries may apply"],
                "critical_assumptions": ["Stated constraints are accurate"],
                "unresolved_research_gaps": ["Direct competitor pricing"],
                "tradeoffs": ["Validation costs time; commitment costs money"],
                "incompatible_recommendations": ["Full commitment now vs validation gate"],
                "convergence": [{"conclusion": "Test before committing",
                                 "advisors": ["advisor_1", "advisor_2", "advisor_5"],
                                 "independent_reasoning": True,
                                 "note": "Reached via different lenses (risk, fundamentals, customer)"}],
            }

        if name == "ChairmanDecision":
            revised = "audit" in prompt.lower() and "defect" in prompt.lower()
            return {
                "action": "reversible_experiment",
                "one_sentence_decision": "Run a two-week demand validation experiment before committing.",
                "decision": ("Run a tightly-scoped two-week validation experiment "
                             "(landing page + 10 customer interviews), then commit only if "
                             "pre-defined demand signals are met."
                             + (" Revised per audit: added explicit spend cap." if revised else "")),
                "reasoning": "Validation scored highest on downside protection and speed of learning "
                             "while preserving upside; committing now scored higher only on urgency.",
                "option_scores": [
                    {"option_id": "opt_validate_first", "scores": [
                        {"criterion": "objective_alignment", "weight": 0.2, "score": 8},
                        {"criterion": "evidence_quality", "weight": 0.15, "score": 6},
                        {"criterion": "reasoning_quality", "weight": 0.1, "score": 8},
                        {"criterion": "feasibility", "weight": 0.15, "score": 9},
                        {"criterion": "upside_potential", "weight": 0.1, "score": 7},
                        {"criterion": "downside_protection", "weight": 0.1, "score": 9},
                        {"criterion": "speed_of_learning", "weight": 0.1, "score": 9},
                        {"criterion": "constraint_fit", "weight": 0.1, "score": 8}]},
                    {"option_id": "opt_commit_now", "scores": [
                        {"criterion": "objective_alignment", "weight": 0.2, "score": 6},
                        {"criterion": "evidence_quality", "weight": 0.15, "score": 4},
                        {"criterion": "reasoning_quality", "weight": 0.1, "score": 6},
                        {"criterion": "feasibility", "weight": 0.15, "score": 7},
                        {"criterion": "upside_potential", "weight": 0.1, "score": 8},
                        {"criterion": "downside_protection", "weight": 0.1, "score": 3},
                        {"criterion": "speed_of_learning", "weight": 0.1, "score": 5},
                        {"criterion": "constraint_fit", "weight": 0.1, "score": 6}]},
                ],
                "adopted_components": ["Demand smoke test", "Customer interviews", "Pre-defined go/no-go signals"],
                "rejected_options": [{"option_id": "opt_commit_now",
                                      "reason": "Insufficient evidence of demand; poor downside protection"}],
                "critical_assumptions": ["Two weeks is enough to observe a demand signal"],
                "key_risks": ["False negative from a weak test"],
                "evidence_claim_ids": [],
                "immediate_next_step": "Draft the validation experiment with explicit success thresholds",
                "success_criteria": ["≥5% landing-page conversion", "≥3 of 10 interviewees describe active pain"],
                "stop_criteria": ["<1% conversion after 500 visitors", "No interviewee reports the problem"],
                "evidence_that_would_reverse": "Verified strong pre-existing demand (e.g. waitlist, pre-orders)",
                "evidence_confidence": 0.55, "decision_confidence": 0.7,
            }

        if name == "AuditReport":
            return {
                "matches_user_objective": True,
                "constraint_violations": [],
                "unsupported_conclusions": [],
                "misrepresented_sources": [],
                "unfairly_rejected_alternatives": [],
                "assumptions_treated_as_facts": [],
                "uncertainty_adequately_explained": True,
                "next_step_reversible": True,
                "criteria_measurable": True,
                "unnecessary_downside_exposure": [],
                "premortem": {
                    "most_likely_failure_cause": "Validation test measures curiosity, not purchase intent",
                    "earliest_warning_signs": ["High click-through but no email signups"],
                    "preventable_failures": ["Vague success thresholds"],
                    "mitigations": ["Require a costly signal (deposit, calendar booking) in the test"],
                    "still_worth_attempting": True,
                    "note": "Plan is sound if the demand signal is made costly.",
                },
                "defects": [{"severity": "minor",
                             "description": "No explicit spend cap on the validation experiment",
                             "required_correction": "Add a maximum spend for the two-week test"}],
                "verdict": "revise",
            }

        if name == "ExecutionPlan":
            return {
                "immediate_actions": [
                    {"id": "a1", "title": "Define go/no-go thresholds",
                     "description": "Write the exact demand signals and spend cap", "owner": "user",
                     "effort_hours": 2, "cost_estimate_usd": 0, "dependencies": []},
                    {"id": "a2", "title": "Set up landing page",
                     "description": "One-page offer with email capture", "owner": "user",
                     "effort_hours": 6, "cost_estimate_usd": 50, "dependencies": ["a1"]},
                ],
                "seven_day_plan": [
                    {"id": "a3", "title": "Drive 500 targeted visitors",
                     "description": "Small paid campaign within spend cap", "owner": "user",
                     "effort_hours": 5, "cost_estimate_usd": 150, "dependencies": ["a2"]},
                    {"id": "a4", "title": "Book 10 customer interviews",
                     "description": "Recruit from target segment", "owner": "user",
                     "effort_hours": 8, "cost_estimate_usd": 0, "dependencies": ["a1"]},
                ],
                "thirty_day_plan": [
                    {"id": "a5", "title": "Go/no-go review",
                     "description": "Compare results against thresholds; decide commit or stop",
                     "owner": "user", "effort_hours": 3, "cost_estimate_usd": 0,
                     "dependencies": ["a3", "a4"]},
                ],
                "milestones": [{"title": "Landing page live", "due": "day 3", "measure": "page published"},
                               {"title": "Go/no-go decision", "due": "day 21", "measure": "documented decision"}],
                "success_criteria": ["≥5% conversion", "≥3 interviews confirm active pain"],
                "failure_criteria": ["<1% conversion after 500 visitors"],
                "review_criteria": ["Weekly check on spend vs cap"],
                "total_cost_estimate_usd": 200, "total_effort_hours": 24,
                "notes": "All spending stays inside the validation cap.",
            }

        if name == "DirectAnswer":
            return {
                "recommendation": "Proceed with the simplest option that meets your stated goal.",
                "reasoning": "The question is well-defined and low-stakes; no council needed.",
                "assumptions": ["Your stated facts are accurate"],
                "main_risks": ["Minor: preferences may shift"],
                "immediate_next_step": "Take the first concrete step today",
                "evidence_claim_ids": [],
                "confidence": 0.7,
            }

        return None
