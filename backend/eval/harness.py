"""Offline evaluation harness.

Runs each benchmark case through four workflow modes —
  direct            one strong model answers directly
  research_assisted research then a single model
  lightweight       3-advisor council
  full              5-advisor council with audit
— and scores the outputs with a judge model, so the added agents must
justify their cost and latency with measurably better results.

Usage:
    uv run python -m eval.harness [--modes direct,full] [--cases bench_career_decision]

Runs with mock providers by default (USE_MOCK_PROVIDERS=true); point it
at real providers via the normal environment variables to produce
meaningful comparisons.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.models import Base
from app.providers.registry import ProviderRegistry
from app.repo import CaseRepository
from app.schemas.aggregate import CaseFile
from app.schemas.case_file import CaseStatus, Route, RoutingDecision, StakesAssessment
from app.schemas.workflow import Stage, StageStatus
from app.workflow.engine import WorkflowEngine
from app.workflow.presenter import build_response
from app.workflow.routing import FULL_COUNCIL_ROLES, LIGHTWEIGHT_ROLES

MODES: dict[str, Route] = {
    "direct": Route.DIRECT,
    "research_assisted": Route.RESEARCH_ASSISTED,
    "lightweight": Route.LIGHTWEIGHT_COUNCIL,
    "full": Route.FULL_COUNCIL,
}

RESULTS_DIR = Path(__file__).parent / "results"


class JudgeScores(BaseModel):
    """Rubric scores are 1-5 subjective assessments by the judge model."""

    constraint_adherence: int = Field(ge=1, le=5)
    factual_grounding: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    decision_clarity: int = Field(ge=1, le=5)
    risk_awareness: int = Field(ge=1, le=5)
    rationale: str = ""


JUDGE_SYSTEM = """\
You are an impartial evaluator of decision recommendations. Score the
recommendation 1-5 on each rubric dimension. Judge only what is written —
do not reward length. Scores are subjective assessments."""


def force_route(case: CaseFile, route: Route) -> None:
    """Pin the route so every mode is comparable on the same case."""
    roles = {
        Route.DIRECT: [],
        Route.RESEARCH_ASSISTED: [],
        Route.LIGHTWEIGHT_COUNCIL: LIGHTWEIGHT_ROLES,
        Route.FULL_COUNCIL: FULL_COUNCIL_ROLES,
    }[route]
    case.routing = RoutingDecision(
        route=route,
        factor_explanations={"forced": f"evaluation harness pinned route to {route.value}"},
        rationale="evaluation harness",
        advisor_roles=[r.value for r in roles],
        stakes=StakesAssessment(),
    )
    rec = case.workflow.record(Stage.ROUTE)
    rec.status = StageStatus.COMPLETE
    from app.schemas.evidence import ResearchMode

    case.evidence.mode = ResearchMode.NONE if route == Route.DIRECT else ResearchMode.TARGETED


async def run_case_in_mode(bench: dict, mode: str, settings: Settings) -> dict:
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(db, expire_on_commit=False)
    async with factory() as session:
        repo = CaseRepository(session)
        registry = ProviderRegistry(settings)
        engine = WorkflowEngine(repo, registry, settings)

        start = time.monotonic()
        case = await engine.create_case(bench["initial_message"])
        for followup in bench["followups"]:
            if case.status != CaseStatus.INTAKE:
                break
            case = await engine.handle_user_message(case, followup)
        if case.status != CaseStatus.READY:
            case.status = CaseStatus.READY  # harness always proceeds

        force_route(case, MODES[mode])
        await repo.save(case, f"eval: forced route {mode}")
        case = await engine.run_pipeline(case)
        elapsed = time.monotonic() - start

        record: dict = {
            "benchmark_id": bench["id"],
            "category": bench["category"],
            "mode": mode,
            "status": case.status.value,
            "cost_usd": case.workflow.usage.cost_usd,
            "model_calls": case.workflow.usage.model_calls,
            "latency_s": round(elapsed, 2),
            "degradations": case.workflow.degradations,
        }
        if case.status == CaseStatus.COMPLETE:
            response = build_response(case)
            record["recommendation"] = response.recommendation
            record["scores"] = (await judge(bench, response.model_dump(), engine)).model_dump()
            # Advisor usefulness: which advisors' options the chairman adopted.
            if case.chairman_final:
                record["adopted_components"] = case.chairman_final.adopted_components
        await db.dispose()
        return record


async def judge(bench: dict, response: dict, engine: WorkflowEngine) -> JudgeScores:
    caller, _ = engine._caller(CaseFile(original_request="judge"))
    prompt = (
        f"DECISION CASE:\n{bench['initial_message']}\n"
        f"Extra context: {' '.join(bench['followups'])}\n\n"
        f"RECOMMENDATION TO SCORE:\n{json.dumps(response, indent=1)}\n\nScore it."
    )
    scores, _ = await caller.structured("auditor", JudgeScores, JUDGE_SYSTEM, prompt)
    return scores


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", default="direct,research_assisted,lightweight,full")
    parser.add_argument("--cases", default="")
    args = parser.parse_args()

    settings = get_settings()
    data = json.loads((Path(__file__).parent / "benchmark_cases.json").read_text())
    wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
    cases = [c for c in data["cases"] if not wanted or c["id"] in wanted]
    modes = [m.strip() for m in args.modes.split(",") if m.strip() in MODES]

    records = []
    for bench in cases:
        for mode in modes:
            print(f"running {bench['id']} in mode {mode}...")
            records.append(await run_case_in_mode(bench, mode, settings))

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"report_{int(time.time())}.json"
    out.write_text(json.dumps(records, indent=1))

    print(f"\n{'case':<32}{'mode':<20}{'cost $':>8}{'calls':>7}{'lat s':>7}{'score':>7}")
    for r in records:
        score = "-"
        if "scores" in r:
            s = r["scores"]
            score = f"{sum(v for k, v in s.items() if isinstance(v, int)) / 5:.1f}"
        print(f"{r['benchmark_id']:<32}{r['mode']:<20}{r['cost_usd']:>8.3f}"
              f"{r['model_calls']:>7}{r['latency_s']:>7.1f}{score:>7}")
    print(f"\nreport written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
