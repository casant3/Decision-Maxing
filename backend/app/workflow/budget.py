"""Workflow budget enforcement with graceful degradation signals."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.config import WorkflowBudget
from app.providers.base import Usage
from app.schemas.evidence import ResearchMode
from app.schemas.workflow import BudgetUsage


class BudgetExceededError(Exception):
    def __init__(self, limit: str, detail: str = ""):
        super().__init__(f"workflow budget exceeded: {limit} {detail}".strip())
        self.limit = limit


class BudgetTracker:
    """Wraps the persisted BudgetUsage; the engine consults degradation
    signals between stages so the workflow degrades before it dies."""

    def __init__(self, budget: WorkflowBudget, usage: BudgetUsage):
        self.budget = budget
        self.usage = usage
        if self.usage.started_at is None:
            self.usage.started_at = datetime.now(UTC)

    # ---------------------------------------------------------- accounting

    def add(self, usage: Usage) -> None:
        self.usage.model_calls += 1
        self.usage.input_tokens += usage.input_tokens
        self.usage.output_tokens += usage.output_tokens
        self.usage.cost_usd = round(self.usage.cost_usd + usage.cost_usd, 6)

    def add_research_query(self) -> None:
        self.usage.research_queries += 1

    def add_clarification_round(self) -> None:
        self.usage.clarification_rounds += 1

    # ---------------------------------------------------------- hard limits

    def elapsed_s(self) -> float:
        started = self.usage.started_at
        if started is None:
            return 0.0
        return (datetime.now(UTC) - started).total_seconds()

    def check_hard_limits(self) -> None:
        b, u = self.budget, self.usage
        if u.model_calls >= b.max_model_calls:
            raise BudgetExceededError("max_model_calls", f"{u.model_calls}/{b.max_model_calls}")
        if u.cost_usd >= b.max_cost_usd:
            raise BudgetExceededError("max_cost_usd", f"{u.cost_usd:.2f}/{b.max_cost_usd}")
        if u.input_tokens >= b.max_input_tokens:
            raise BudgetExceededError("max_input_tokens")
        if u.output_tokens >= b.max_output_tokens:
            raise BudgetExceededError("max_output_tokens")
        if self.elapsed_s() >= b.max_duration_s:
            raise BudgetExceededError("max_duration_s")

    # ---------------------------------------------------------- degradation

    @property
    def cost_fraction(self) -> float:
        return self.usage.cost_usd / self.budget.max_cost_usd if self.budget.max_cost_usd else 0.0

    @property
    def calls_fraction(self) -> float:
        return self.usage.model_calls / self.budget.max_model_calls if self.budget.max_model_calls else 0.0

    def should_reduce_council(self) -> bool:
        return max(self.cost_fraction, self.calls_fraction) >= 0.6

    def should_skip_audit(self) -> bool:
        return max(self.cost_fraction, self.calls_fraction) >= 0.8

    def clarification_rounds_left(self) -> int:
        return max(0, self.budget.max_clarification_rounds - self.usage.clarification_rounds)

    def cap_research_mode(self, requested: ResearchMode) -> ResearchMode:
        if requested == ResearchMode.NONE:
            return requested
        queries_left = self.budget.max_research_queries - self.usage.research_queries
        if queries_left <= 0:
            return ResearchMode.NONE
        if requested == ResearchMode.DEEP and (self.cost_fraction >= 0.5 or queries_left < 4):
            return ResearchMode.STANDARD
        if requested == ResearchMode.STANDARD and queries_left < 2:
            return ResearchMode.TARGETED
        return requested


def timer_ms() -> float:
    return time.monotonic() * 1000
