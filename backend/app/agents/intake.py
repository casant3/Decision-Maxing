"""Chief of Staff intake + Context Gate."""

from __future__ import annotations

from app.agents.structured import AgentCaller, CallMeta
from app.prompts.templates import chief_of_staff_prompt, gate_prompt
from app.schemas.agents import CaseUpdate, ChiefOfStaffReply, GateResult
from app.schemas.aggregate import CaseFile
from app.schemas.case_file import Fact, FactOrigin


def apply_case_update(case: CaseFile, update: CaseUpdate) -> None:
    if update.objective:
        case.objective = update.objective
    if update.decision_required:
        case.decision_required = update.decision_required
    if update.conversation_summary:
        case.conversation_summary = update.conversation_summary

    existing_statements = {f.statement.strip().lower() for f in case.fact_index().values()}
    for fact in update.new_facts:
        if fact.statement.strip().lower() in existing_statements:
            continue
        # The Chief of Staff may only assert user-confirmed facts or inferences;
        # externally-verified facts come exclusively from the evidence pipeline.
        if fact.origin == FactOrigin.EXTERNALLY_VERIFIED:
            fact = Fact(statement=fact.statement, origin=FactOrigin.SYSTEM_INFERENCE)
        case.add_fact(fact)

    existing_cons = {c.description.strip().lower() for c in case.constraints}
    case.constraints.extend(
        c for c in update.new_constraints if c.description.strip().lower() not in existing_cons
    )
    existing_prefs = {p.description.strip().lower() for p in case.preferences}
    case.preferences.extend(
        p for p in update.new_preferences if p.description.strip().lower() not in existing_prefs
    )
    existing_asm = {a.statement.strip().lower() for a in case.assumptions}
    case.assumptions.extend(
        a for a in update.new_assumptions if a.statement.strip().lower() not in existing_asm
    )
    case.open_questions.extend(update.new_open_questions)
    for qid in update.answered_question_ids:
        for q in case.open_questions:
            if q.id == qid:
                q.status = "answered"


async def run_chief_of_staff(case: CaseFile, caller: AgentCaller) -> tuple[ChiefOfStaffReply, CallMeta]:
    system, prompt = chief_of_staff_prompt(case)
    reply, meta = await caller.structured("chief_of_staff", ChiefOfStaffReply, system, prompt)
    apply_case_update(case, reply.update)
    return reply, meta


async def run_gate(case: CaseFile, caller: AgentCaller) -> tuple[GateResult, CallMeta]:
    system, prompt = gate_prompt(case)
    result, meta = await caller.structured("context_gate", GateResult, system, prompt)
    case.gate_result = result
    return result, meta
