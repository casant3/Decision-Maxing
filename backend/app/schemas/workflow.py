"""Workflow state: stages, stage records, budget usage."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class Stage(str, Enum):
    INTAKE = "intake"
    GATE = "gate"
    ROUTE = "route"
    COMPILE = "compile"
    RESEARCH = "research"
    ADVISORS = "advisors"
    ARGUMENT_MAP = "argument_map"
    CHAIRMAN_DRAFT = "chairman_draft"
    AUDIT = "audit"
    CHAIRMAN_FINAL = "chairman_final"
    EXECUTOR = "executor"
    VALIDATE = "validate"
    PRESENT = "present"
    DIRECT = "direct_answer"  # single-answer stage for direct / research-assisted routes


# Pipeline order per route. Direct/research-assisted routes use a single
# synthesis stage in place of the council (handled in the engine).
FULL_PIPELINE: list[Stage] = [
    Stage.COMPILE,
    Stage.RESEARCH,
    Stage.ADVISORS,
    Stage.ARGUMENT_MAP,
    Stage.CHAIRMAN_DRAFT,
    Stage.AUDIT,
    Stage.CHAIRMAN_FINAL,
    Stage.EXECUTOR,
    Stage.VALIDATE,
    Stage.PRESENT,
]


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"
    INVALIDATED = "invalidated"


class StageRecord(BaseModel):
    stage: Stage
    status: StageStatus = StageStatus.PENDING
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    # Notes about degradations, skips, fallbacks applied at this stage.
    notes: list[str] = Field(default_factory=list)


class BudgetUsage(BaseModel):
    clarification_rounds: int = 0
    model_calls: int = 0
    research_queries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    started_at: datetime | None = None


class WorkflowState(BaseModel):
    current_stage: Stage | None = None
    stages: dict[str, StageRecord] = Field(default_factory=dict)  # keyed by Stage.value
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    degradations: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)  # role -> model id used

    def record(self, stage: Stage) -> StageRecord:
        rec = self.stages.get(stage.value)
        if rec is None:
            rec = StageRecord(stage=stage)
            self.stages[stage.value] = rec
        return rec

    def invalidate_from(self, stage: Stage, pipeline: list[Stage]) -> list[Stage]:
        """Invalidate a stage and everything after it in the pipeline."""
        if stage not in pipeline:
            return []
        invalidated: list[Stage] = []
        for s in pipeline[pipeline.index(stage):]:
            rec = self.stages.get(s.value)
            if rec and rec.status == StageStatus.COMPLETE:
                rec.status = StageStatus.INVALIDATED
                invalidated.append(s)
        return invalidated
