"""User-facing response, composed deterministically in code from structured
stage outputs — never a fresh LLM call, so it cannot drift from the audited
decision."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UserFacingResponse(BaseModel):
    recommendation: str
    why_this_won: str
    council_disagreements: list[str] = Field(default_factory=list)
    immediate_next_action: str = ""
    seven_day_plan: list[str] = Field(default_factory=list)
    test_and_success_criteria: list[str] = Field(default_factory=list)
    main_risks: list[str] = Field(default_factory=list)
    assumptions_and_unknowns: list[str] = Field(default_factory=list)
    confidence_explanation: str = ""
