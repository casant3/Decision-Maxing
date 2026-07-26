"""Strategic advisors: independent, parallel, anonymised.

No advisor sees another advisor's response. Provider/model identity is
recorded for logging/eval only and never forwarded to the Chairman.
Order is randomised (seeded per case+version for reproducibility) before
anonymous ids are assigned."""

from __future__ import annotations

import asyncio
import random

from app.agents.compiler import TaskPackage
from app.agents.structured import AgentCaller, StructuredCallError
from app.prompts.templates import advisor_prompt
from app.schemas.agents import AdvisorResponse, AdvisorRole
from app.schemas.aggregate import AdvisorRun
from app.workflow.budget import BudgetExceededError

# Council routes stay useful with a quorum of 2 — below that the run fails.
MIN_ADVISORS = 2


class CouncilQuorumError(Exception):
    pass


async def run_advisors(
    pkg: TaskPackage,
    roles: list[AdvisorRole],
    caller: AgentCaller,
    seed: str,
) -> list[AdvisorRun]:
    async def one(role: AdvisorRole) -> AdvisorRun:
        system, prompt = advisor_prompt(role, pkg)
        try:
            response, meta = await caller.structured(role.value, AdvisorResponse, system, prompt)
            # The model sometimes echoes the wrong role; pin it to the assigned lens.
            response.role = role
            return AdvisorRun(anonymous_id="", response=response,
                              provider=meta.provider, model=meta.model)
        except (StructuredCallError, BudgetExceededError) as e:
            # Continue without the failed advisor (recorded, not silent).
            return AdvisorRun(
                anonymous_id="",
                response=AdvisorResponse(role=role, problem_interpretation="", recommendation="",
                                         causal_reasoning=""),
                failed=True,
                failure_reason=str(e)[:300],
            )

    runs = list(await asyncio.gather(*(one(r) for r in roles)))

    succeeded = [r for r in runs if not r.failed]
    if len(succeeded) < MIN_ADVISORS:
        reasons = "; ".join(r.failure_reason for r in runs if r.failed)
        raise CouncilQuorumError(f"only {len(succeeded)} advisors succeeded: {reasons}")

    rng = random.Random(seed)
    rng.shuffle(runs)
    for i, run in enumerate(runs, start=1):
        run.anonymous_id = f"advisor_{i}"
    return runs
