"""Workflow engine: a hand-rolled, typed state machine.

Design: a linear pipeline per route with idempotent, persisted stages.
The engine re-enters at the first non-complete stage, so runs are
resumable, individual stages can be invalidated for selective reruns,
and one provider failure never restarts the whole workflow.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.agents import council
from app.agents.advisors import CouncilQuorumError, run_advisors
from app.agents.compiler import compile_task_package
from app.agents.intake import run_chief_of_staff, run_gate
from app.agents.research import run_research
from app.agents.structured import AgentCaller, StructuredCallError
from app.agents.validator import validate_plan
from app.config import Settings
from app.prompts.shared import PROMPT_VERSIONS
from app.prompts.templates import router_prompt
from app.providers.registry import ProviderRegistry
from app.repo import CaseRepository
from app.schemas.agents import AdvisorRole, ReadinessStatus, RouterAssessment
from app.schemas.aggregate import CaseFile
from app.schemas.case_file import (
    DEFAULT_DECISION_CRITERIA,
    CaseStatus,
    ConversationTurn,
    Route,
    StakeLevel,
)
from app.schemas.evidence import ResearchMode
from app.schemas.workflow import Stage, StageStatus
from app.workflow.budget import BudgetExceededError, BudgetTracker
from app.workflow.presenter import build_response
from app.workflow.routing import (
    LIGHTWEIGHT_ROLES,
    decide_research_mode,
    decide_route,
)

MAX_VALIDATION_LOOPS = 2
PIPELINE_GUARD = 40  # absolute cap on stage executions per run

PIPELINES: dict[Route, list[Stage]] = {
    Route.DIRECT: [Stage.COMPILE, Stage.DIRECT, Stage.PRESENT],
    Route.RESEARCH_ASSISTED: [Stage.COMPILE, Stage.RESEARCH, Stage.DIRECT, Stage.PRESENT],
    Route.LIGHTWEIGHT_COUNCIL: [
        Stage.COMPILE, Stage.RESEARCH, Stage.ADVISORS, Stage.ARGUMENT_MAP,
        Stage.CHAIRMAN_DRAFT, Stage.AUDIT, Stage.CHAIRMAN_FINAL,
        Stage.EXECUTOR, Stage.VALIDATE, Stage.PRESENT,
    ],
    Route.FULL_COUNCIL: [
        Stage.COMPILE, Stage.RESEARCH, Stage.ADVISORS, Stage.ARGUMENT_MAP,
        Stage.CHAIRMAN_DRAFT, Stage.AUDIT, Stage.CHAIRMAN_FINAL,
        Stage.EXECUTOR, Stage.VALIDATE, Stage.PRESENT,
    ],
}


class StageFailure(Exception):
    def __init__(self, stage: Stage, detail: str):
        super().__init__(f"stage {stage.value} failed: {detail}")
        self.stage = stage


class WorkflowEngine:
    def __init__(self, repo: CaseRepository, registry: ProviderRegistry, settings: Settings):
        self.repo = repo
        self.registry = registry
        self.settings = settings
        self.roles = settings.roles()

    def _caller(self, case: CaseFile) -> tuple[AgentCaller, BudgetTracker]:
        budget = BudgetTracker(self.settings.budget, case.workflow.usage)
        return AgentCaller(self.registry, self.roles, budget), budget

    # ================================================== intake

    async def create_case(self, first_message: str) -> CaseFile:
        case = CaseFile(
            original_request=first_message,
            title=first_message.strip().splitlines()[0][:80],
            decision_criteria=list(DEFAULT_DECISION_CRITERIA),
        )
        case.workflow.prompt_versions = dict(PROMPT_VERSIONS)
        await self.repo.save(case, "case created")
        await self.repo.log_event(case.case_id, "case_created", {"request": first_message[:500]})
        return await self.handle_user_message(case, first_message, first=True)

    async def handle_user_message(self, case: CaseFile, text: str, first: bool = False) -> CaseFile:
        case.conversation.append(ConversationTurn(role="user", content=text))
        caller, budget = self._caller(case)

        reply, cos_meta = await run_chief_of_staff(case, caller)
        gate, gate_meta = await run_gate(case, caller)
        case.workflow.model_versions["chief_of_staff"] = cos_meta.model
        case.workflow.model_versions["context_gate"] = gate_meta.model

        rounds_left = budget.clarification_rounds_left()
        proceed = (
            gate.status == ReadinessStatus.READY
            or reply.ready_to_proceed
            or rounds_left <= 0
        )
        if proceed:
            # Adopt gate-approved safe assumptions, clearly labelled.
            existing = {a.statement.lower() for a in case.assumptions}
            for a in gate.safe_assumptions:
                if a.statement.lower() not in existing:
                    case.assumptions.append(a)
            if rounds_left <= 0 and gate.status != ReadinessStatus.READY:
                case.workflow.degradations.append(
                    "clarification budget exhausted; proceeding on labelled assumptions"
                )
            case.status = CaseStatus.READY
            message = reply.message_to_user or "I have what I need — convening the council."
        else:
            budget.add_clarification_round()
            case.status = CaseStatus.INTAKE
            questions = reply.questions or ([gate.next_question] if gate.next_question else [])
            message = reply.message_to_user
            if questions:
                message = (message + "\n" if message else "") + "\n".join(f"- {q}" for q in questions)

        case.conversation.append(ConversationTurn(role="assistant", content=message))
        await self.repo.save(case, "intake message processed")
        await self.repo.log_event(case.case_id, "intake_turn", {
            "gate_status": gate.status.value, "readiness": gate.readiness_score,
            "proceed": proceed,
        })
        return case

    # ================================================== pipeline

    async def run_pipeline(self, case: CaseFile) -> CaseFile:
        if case.status not in (CaseStatus.READY, CaseStatus.RUNNING, CaseStatus.FAILED,
                               CaseStatus.COMPLETE):
            raise ValueError(f"case not ready to run (status={case.status.value})")
        case.status = CaseStatus.RUNNING
        await self.repo.save(case, "pipeline started")

        caller, budget = self._caller(case)

        try:
            # Routing runs before the pipeline proper (it selects the pipeline).
            await self._ensure_route(case, caller)
            pipeline = PIPELINES[case.routing.route]

            validation_loops = 0
            guard = 0
            while True:
                guard += 1
                if guard > PIPELINE_GUARD:
                    raise StageFailure(Stage.VALIDATE, "pipeline guard tripped (possible loop)")
                stage = self._next_stage(case, pipeline)
                if stage is None:
                    break
                if stage == Stage.VALIDATE:
                    revalidate = await self._run_validate(case, caller, validation_loops)
                    await self.repo.save(case, f"stage {stage.value} finished")
                    if revalidate:
                        validation_loops += 1
                    continue
                await self._run_stage(case, stage, caller, budget)
                await self.repo.save(case, f"stage {stage.value} finished")

            case.status = CaseStatus.COMPLETE
            await self.repo.save(case, "pipeline complete")
            await self.repo.log_event(case.case_id, "pipeline_complete", {
                "cost_usd": case.workflow.usage.cost_usd,
                "model_calls": case.workflow.usage.model_calls,
            })
        except BudgetExceededError as e:
            await self._degrade_on_budget(case, str(e))
        except (StageFailure, CouncilQuorumError, StructuredCallError) as e:
            case.status = CaseStatus.FAILED
            case.workflow.failures.append(str(e))
            await self.repo.save(case, f"pipeline failed: {e}")
            await self.repo.log_event(case.case_id, "pipeline_failed", {"error": str(e)[:500]})
        return case

    def _next_stage(self, case: CaseFile, pipeline: list[Stage]) -> Stage | None:
        for stage in pipeline:
            rec = case.workflow.stages.get(stage.value)
            if rec is None or rec.status in (StageStatus.PENDING, StageStatus.INVALIDATED,
                                             StageStatus.RUNNING, StageStatus.FAILED):
                return stage
        return None

    async def _ensure_route(self, case: CaseFile, caller: AgentCaller) -> None:
        rec = case.workflow.record(Stage.ROUTE)
        if rec.status == StageStatus.COMPLETE and case.routing is not None:
            return
        rec.status = StageStatus.RUNNING
        rec.started_at = datetime.now(UTC)
        system, prompt = router_prompt(case)
        assessment, meta = await caller.structured("router", RouterAssessment, system, prompt)
        case.routing = decide_route(assessment)
        requested_mode = decide_research_mode(case.routing, assessment)
        case.evidence.mode = requested_mode
        case.workflow.model_versions["router"] = meta.model
        rec.status = StageStatus.COMPLETE
        rec.finished_at = datetime.now(UTC)
        rec.cost_usd = meta.cost_usd
        rec.notes.append(f"route={case.routing.route.value} research={requested_mode.value}")
        await self.repo.log_event(case.case_id, "routed", {
            "route": case.routing.route.value,
            "explanations": case.routing.factor_explanations,
        })

    async def _run_stage(self, case: CaseFile, stage: Stage, caller: AgentCaller,
                         budget: BudgetTracker) -> None:
        rec = case.workflow.record(stage)
        rec.status = StageStatus.RUNNING
        rec.attempts += 1
        rec.started_at = datetime.now(UTC)
        case.workflow.current_stage = stage
        cost_before = case.workflow.usage.cost_usd
        tokens_before = (case.workflow.usage.input_tokens, case.workflow.usage.output_tokens)
        try:
            await self._dispatch(case, stage, caller, budget)
        except (BudgetExceededError, CouncilQuorumError):
            rec.status = StageStatus.FAILED
            rec.finished_at = datetime.now(UTC)
            raise
        except StructuredCallError as e:
            rec.status = StageStatus.FAILED
            rec.error = str(e)[:500]
            rec.finished_at = datetime.now(UTC)
            raise StageFailure(stage, str(e)) from e
        if rec.status == StageStatus.RUNNING:  # dispatch may have marked SKIPPED
            rec.status = StageStatus.COMPLETE
        rec.finished_at = datetime.now(UTC)
        rec.cost_usd = round(case.workflow.usage.cost_usd - cost_before, 6)
        rec.input_tokens = case.workflow.usage.input_tokens - tokens_before[0]
        rec.output_tokens = case.workflow.usage.output_tokens - tokens_before[1]
        rec.latency_ms = int((rec.finished_at - rec.started_at).total_seconds() * 1000)

    async def _dispatch(self, case: CaseFile, stage: Stage, caller: AgentCaller,
                        budget: BudgetTracker) -> None:
        pkg = compile_task_package(case)
        rec = case.workflow.record(stage)

        if stage == Stage.COMPILE:
            # Deterministic; recorded for auditability.
            rec.notes.append(f"compiled: {len(pkg.user_facts)} user facts, "
                             f"{len(pkg.constraints)} constraints, {len(pkg.evidence.items)} evidence items")
            return

        if stage == Stage.RESEARCH:
            requested = case.evidence.mode
            capped = budget.cap_research_mode(requested)
            if capped != requested:
                case.workflow.degradations.append(
                    f"research downgraded {requested.value} -> {capped.value} (budget)")
            if capped == ResearchMode.NONE:
                rec.notes.append("no research needed")
                case.evidence.mode = ResearchMode.NONE
                return
            ledger = await run_research(pkg, capped, self.registry, caller, budget)
            # Merge: keep any user-supplied evidence already present.
            ledger.items = [*case.evidence.items, *ledger.items]
            case.evidence = ledger
            rec.notes.append(f"{len(ledger.items)} claims from {len(ledger.queries)} queries")
            return

        if stage == Stage.ADVISORS:
            roles = [AdvisorRole(r) for r in case.routing.advisor_roles]
            if budget.should_reduce_council() and len(roles) > len(LIGHTWEIGHT_ROLES):
                roles = LIGHTWEIGHT_ROLES
                case.workflow.degradations.append("council reduced 5 -> 3 advisors (budget)")
            seed = f"{case.case_id}:{case.version}"
            case.advisor_runs = await run_advisors(pkg, roles, caller, seed)
            for run in case.advisor_runs:
                if not run.failed:
                    case.workflow.model_versions[run.response.role.value] = run.model
                else:
                    case.workflow.failures.append(
                        f"advisor {run.response.role.value} skipped: {run.failure_reason}")
            rec.notes.append(f"{sum(1 for r in case.advisor_runs if not r.failed)}"
                             f"/{len(case.advisor_runs)} advisors succeeded")
            return

        if stage == Stage.ARGUMENT_MAP:
            amap, meta = await council.run_argument_mapper(pkg, case.advisor_runs, caller)
            case.argument_map = amap
            case.workflow.model_versions["argument_mapper"] = meta.model
            return

        if stage == Stage.CHAIRMAN_DRAFT:
            draft, meta = await council.run_chairman_draft(pkg, case.advisor_runs,
                                                           case.argument_map, caller)
            case.chairman_draft = draft
            case.workflow.model_versions["chairman"] = meta.model
            return

        if stage == Stage.AUDIT:
            skip_low_stakes = (
                case.routing.route == Route.LIGHTWEIGHT_COUNCIL
                and case.routing.stakes.overall == StakeLevel.LOW
            )
            if skip_low_stakes or budget.should_skip_audit():
                rec.status = StageStatus.SKIPPED
                reason = "low stakes" if skip_low_stakes else "budget"
                rec.notes.append(f"audit skipped ({reason})")
                case.workflow.degradations.append(f"audit skipped ({reason})")
                return
            audit, meta = await council.run_auditor(pkg, case.chairman_draft, caller)
            case.audit = audit
            case.workflow.model_versions["auditor"] = meta.model
            return

        if stage == Stage.CHAIRMAN_FINAL:
            if case.audit is None:
                # Audit skipped: the draft stands as final, noted for auditability.
                case.chairman_final = case.chairman_draft.model_copy(deep=True)
                rec.notes.append("no audit — draft adopted as final")
                return
            final, meta = await council.run_chairman_revision(pkg, case.chairman_draft,
                                                              case.audit, caller)
            case.chairman_final = final
            case.workflow.model_versions["chairman_revision"] = meta.model
            return

        if stage == Stage.EXECUTOR:
            final = case.chairman_final
            feedback = ""
            if case.validation is not None and not case.validation.valid:
                feedback = "Previous plan failed validation: " + "; ".join(
                    f"{d.code}: {d.description}" for d in case.validation.defects
                    if d.stage_to_fix == Stage.EXECUTOR.value)
            plan, meta = await council.run_executor(pkg, final, caller, feedback)
            case.execution_plan = plan
            case.workflow.model_versions["executor"] = meta.model
            return

        if stage == Stage.DIRECT:
            answer, meta = await council.run_direct_answer(pkg, caller)
            case.direct_answer = answer
            case.workflow.model_versions["direct_answer"] = meta.model
            return

        if stage == Stage.PRESENT:
            # Deterministic composition; stored via the API on demand.
            build_response(case)
            return

        raise StageFailure(stage, "no handler for stage")

    async def _run_validate(self, case: CaseFile, caller: AgentCaller, loops: int) -> bool:
        """Run the constraint validator. Returns True when a repair loop was
        triggered (a stage was invalidated and must rerun)."""
        rec = case.workflow.record(Stage.VALIDATE)
        rec.status = StageStatus.RUNNING
        rec.attempts += 1
        rec.started_at = datetime.now(UTC)
        result = validate_plan(case, case.execution_plan, case.chairman_final)
        case.validation = result
        rec.finished_at = datetime.now(UTC)

        if result.valid or loops >= MAX_VALIDATION_LOOPS:
            rec.status = StageStatus.COMPLETE
            if not result.valid:
                rec.notes.append("validation defects remain after repair loops; surfaced to user")
                case.workflow.failures.append(
                    "validation defects unresolved: "
                    + "; ".join(d.code for d in result.defects))
            return False

        # Route back only to the offending stage(s).
        stages_to_fix = {Stage(d.stage_to_fix) for d in result.defects}
        for stage in stages_to_fix:
            fix_rec = case.workflow.record(stage)
            fix_rec.status = StageStatus.INVALIDATED
            fix_rec.notes.append(
                "invalidated by validator: " + "; ".join(
                    d.code for d in result.defects if d.stage_to_fix == stage.value))
            # Rerunning the chairman must also rerun the executor.
            if stage in (Stage.CHAIRMAN_FINAL, Stage.CHAIRMAN_DRAFT):
                case.workflow.record(Stage.EXECUTOR).status = StageStatus.INVALIDATED
        rec.status = StageStatus.INVALIDATED
        rec.notes.append(f"validation loop {loops + 1}: rerunning "
                         + ", ".join(s.value for s in stages_to_fix))
        await self.repo.log_event(case.case_id, "validation_loop", {
            "defects": [d.model_dump() for d in result.defects]})
        return True

    async def _degrade_on_budget(self, case: CaseFile, reason: str) -> None:
        """Budget exhausted mid-run: keep the best complete artefact rather
        than discarding the run."""
        case.workflow.degradations.append(f"budget limit hit: {reason}")
        if case.chairman_final is None and case.chairman_draft is not None:
            case.chairman_final = case.chairman_draft.model_copy(deep=True)
            case.workflow.record(Stage.CHAIRMAN_FINAL).notes.append(
                "budget exhausted — draft adopted as final without revision")
        if case.chairman_final is not None or case.direct_answer is not None:
            case.workflow.record(Stage.PRESENT).status = StageStatus.COMPLETE
            case.status = CaseStatus.COMPLETE
            await self.repo.save(case, f"completed degraded: {reason}")
        else:
            case.status = CaseStatus.FAILED
            case.workflow.failures.append(reason)
            await self.repo.save(case, f"failed on budget: {reason}")
        await self.repo.log_event(case.case_id, "budget_degradation", {"reason": reason})
