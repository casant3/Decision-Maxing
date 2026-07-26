"""Argument Mapper, Chairman (draft + revision), Auditor, Executor, and the
direct/research-assisted answer agent."""

from __future__ import annotations

from app.agents.compiler import TaskPackage
from app.agents.structured import AgentCaller, CallMeta
from app.prompts.templates import (
    auditor_prompt,
    chairman_prompt,
    chairman_revision_prompt,
    direct_answer_prompt,
    executor_prompt,
    mapper_prompt,
)
from app.schemas.agents import (
    ArgumentMap,
    AuditReport,
    ChairmanDecision,
    DirectAnswer,
    ExecutionPlan,
)
from app.schemas.aggregate import AdvisorRun


async def run_argument_mapper(pkg: TaskPackage, runs: list[AdvisorRun],
                              caller: AgentCaller) -> tuple[ArgumentMap, CallMeta]:
    system, prompt = mapper_prompt(pkg, runs)
    return await caller.structured("argument_mapper", ArgumentMap, system, prompt)


async def run_chairman_draft(pkg: TaskPackage, runs: list[AdvisorRun], argument_map: ArgumentMap,
                             caller: AgentCaller) -> tuple[ChairmanDecision, CallMeta]:
    system, prompt = chairman_prompt(pkg, runs, argument_map.model_dump_json(indent=1))
    return await caller.structured("chairman", ChairmanDecision, system, prompt)


async def run_auditor(pkg: TaskPackage, draft: ChairmanDecision,
                      caller: AgentCaller) -> tuple[AuditReport, CallMeta]:
    system, prompt = auditor_prompt(pkg, draft.model_dump_json(indent=1))
    return await caller.structured("auditor", AuditReport, system, prompt)


async def run_chairman_revision(pkg: TaskPackage, draft: ChairmanDecision, audit: AuditReport,
                                caller: AgentCaller) -> tuple[ChairmanDecision, CallMeta]:
    system, prompt = chairman_revision_prompt(
        pkg, draft.model_dump_json(indent=1), audit.model_dump_json(indent=1)
    )
    return await caller.structured("chairman", ChairmanDecision, system, prompt)


async def run_executor(pkg: TaskPackage, final: ChairmanDecision, caller: AgentCaller,
                       validation_feedback: str = "") -> tuple[ExecutionPlan, CallMeta]:
    system, prompt = executor_prompt(pkg, final.model_dump_json(indent=1))
    if validation_feedback:
        prompt += f"\n\n=== VALIDATION FEEDBACK (fix these in the new plan) ===\n{validation_feedback}"
    return await caller.structured("executor", ExecutionPlan, system, prompt)


async def run_direct_answer(pkg: TaskPackage, caller: AgentCaller) -> tuple[DirectAnswer, CallMeta]:
    system, prompt = direct_answer_prompt(pkg)
    return await caller.structured("direct_answer", DirectAnswer, system, prompt)
