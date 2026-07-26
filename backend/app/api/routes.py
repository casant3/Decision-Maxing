"""REST API. The council pipeline runs as a background task; the client
polls /status for meaningful progress states (no chain-of-thought)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session, session_factory
from app.providers.registry import ProviderRegistry
from app.repo import CaseRepository
from app.schemas.aggregate import CaseFile, OutcomeReview
from app.schemas.case_file import CaseStatus, Constraint
from app.schemas.workflow import Stage, StageStatus
from app.workflow.engine import WorkflowEngine
from app.workflow.presenter import build_response
from app.workflow.rerun import apply_constraint_change

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# User-facing progress labels — no internal jargon, no hidden reasoning.
STAGE_LABELS: dict[str, str] = {
    Stage.ROUTE.value: "Checking what information matters",
    Stage.COMPILE.value: "Preparing the decision brief",
    Stage.RESEARCH.value: "Researching current evidence",
    Stage.ADVISORS.value: "Advisors reviewing the options",
    Stage.ARGUMENT_MAP.value: "Mapping agreements and disagreements",
    Stage.CHAIRMAN_DRAFT.value: "Chairman weighing the options",
    Stage.AUDIT.value: "Stress-testing the recommendation",
    Stage.CHAIRMAN_FINAL.value: "Finalising the decision",
    Stage.EXECUTOR.value: "Building your action plan",
    Stage.VALIDATE.value: "Checking the plan against your constraints",
    Stage.DIRECT.value: "Preparing your answer",
    Stage.PRESENT.value: "Preparing the summary",
}

_background_tasks: set[asyncio.Task] = set()


def _engine(session: AsyncSession) -> WorkflowEngine:
    settings = get_settings()
    return WorkflowEngine(CaseRepository(session), ProviderRegistry(settings), settings)


async def _load_case(session: AsyncSession, case_id: str) -> CaseFile:
    case = await CaseRepository(session).load(case_id)
    if case is None:
        raise HTTPException(404, "case not found")
    return case


# ------------------------------------------------------------- payloads

class NewCaseIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class ConstraintChangeIn(BaseModel):
    constraint: Constraint


class CaseSummaryOut(BaseModel):
    case_id: str
    title: str
    status: str
    version: int
    updated_at: str


class IntakeOut(BaseModel):
    case_id: str
    status: str
    assistant_message: str
    version: int


# ------------------------------------------------------------- routes

@router.post("/cases", response_model=IntakeOut)
async def create_case(body: NewCaseIn, session: AsyncSession = Depends(get_session)):
    engine = _engine(session)
    case = await engine.create_case(body.message)
    return IntakeOut(case_id=case.case_id, status=case.status.value,
                     assistant_message=case.conversation[-1].content, version=case.version)


@router.post("/cases/{case_id}/messages", response_model=IntakeOut)
async def post_message(case_id: str, body: MessageIn, session: AsyncSession = Depends(get_session)):
    case = await _load_case(session, case_id)
    if case.status not in (CaseStatus.INTAKE, CaseStatus.READY, CaseStatus.NEEDS_INPUT):
        raise HTTPException(409, f"case is {case.status.value}; intake is closed")
    engine = _engine(session)
    case = await engine.handle_user_message(case, body.message)
    return IntakeOut(case_id=case.case_id, status=case.status.value,
                     assistant_message=case.conversation[-1].content, version=case.version)


async def _run_pipeline_bg(case_id: str) -> None:
    # Background task uses its own session — request sessions close on return.
    async with session_factory()() as session:
        engine = _engine(session)
        case = await CaseRepository(session).load(case_id)
        if case is None:
            return
        try:
            await engine.run_pipeline(case)
        except Exception:  # noqa: BLE001 — background task must not crash the app
            logger.exception("pipeline failed for %s", case_id)


@router.post("/cases/{case_id}/run")
async def run_case(case_id: str, session: AsyncSession = Depends(get_session)):
    case = await _load_case(session, case_id)
    if case.status == CaseStatus.RUNNING:
        return {"status": "running"}
    if case.status not in (CaseStatus.READY, CaseStatus.COMPLETE, CaseStatus.FAILED):
        raise HTTPException(409, f"case not ready (status={case.status.value})")
    task = asyncio.create_task(_run_pipeline_bg(case_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "started"}


@router.get("/cases/{case_id}/status")
async def case_status(case_id: str, session: AsyncSession = Depends(get_session)):
    case = await _load_case(session, case_id)
    stages: list[dict[str, Any]] = []
    if case.routing:
        from app.workflow.engine import PIPELINES

        for stage in [Stage.ROUTE, *PIPELINES[case.routing.route]]:
            rec = case.workflow.stages.get(stage.value)
            stages.append({
                "stage": stage.value,
                "label": STAGE_LABELS.get(stage.value, stage.value),
                "status": rec.status.value if rec else StageStatus.PENDING.value,
            })
    return {
        "case_id": case.case_id,
        "status": case.status.value,
        "version": case.version,
        "route": case.routing.route.value if case.routing else None,
        "stages": stages,
        "cost_usd": case.workflow.usage.cost_usd,
        "degradations": case.workflow.degradations,
    }


@router.get("/cases/{case_id}/result")
async def case_result(case_id: str, session: AsyncSession = Depends(get_session)):
    case = await _load_case(session, case_id)
    if case.status != CaseStatus.COMPLETE:
        raise HTTPException(409, f"case not complete (status={case.status.value})")
    response = build_response(case)
    return {
        "case_id": case.case_id,
        "response": response.model_dump(),
        "validation": case.validation.model_dump() if case.validation else None,
    }


@router.get("/cases/{case_id}")
async def case_detail(case_id: str, session: AsyncSession = Depends(get_session)):
    """Full case file for the Council Room view. Provider/model metadata is
    included here for transparency — it was still hidden from the Chairman
    during deliberation."""
    case = await _load_case(session, case_id)
    return case.model_dump(mode="json")


@router.get("/cases", response_model=list[CaseSummaryOut])
async def list_cases(session: AsyncSession = Depends(get_session)):
    rows = await CaseRepository(session).list_cases()
    return [CaseSummaryOut(case_id=r.id, title=r.title, status=r.status,
                           version=r.current_version, updated_at=r.updated_at.isoformat())
            for r in rows]


@router.post("/cases/{case_id}/constraints")
async def change_constraint(case_id: str, body: ConstraintChangeIn,
                            session: AsyncSession = Depends(get_session)):
    """Change a constraint and selectively rerun only affected stages."""
    case = await _load_case(session, case_id)
    if case.status == CaseStatus.RUNNING:
        raise HTTPException(409, "case is running; wait for completion")
    repo = CaseRepository(session)
    invalidated = apply_constraint_change(case, body.constraint)
    case.status = CaseStatus.READY
    await repo.save(case, f"constraint changed: {body.constraint.description[:80]}")
    await repo.log_event(case_id, "constraint_changed", {
        "constraint": body.constraint.model_dump(),
        "invalidated_stages": [s.value for s in invalidated],
    })
    task = asyncio.create_task(_run_pipeline_bg(case_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "rerunning", "invalidated_stages": [s.value for s in invalidated]}


@router.post("/cases/{case_id}/outcome")
async def record_outcome(case_id: str, review: OutcomeReview,
                         session: AsyncSession = Depends(get_session)):
    case = await _load_case(session, case_id)
    repo = CaseRepository(session)
    case.outcome = review
    await repo.save(case, "outcome recorded")
    await repo.save_outcome(case.case_id, review)
    return {"status": "recorded"}


@router.get("/health")
async def health():
    settings = get_settings()
    registry = ProviderRegistry(settings)
    return {"status": "ok", "mock_mode": settings.use_mock_providers,
            "providers": await registry.health()}
