"""Research router + evidence ledger construction.

The research provider gathers findings; a normaliser turns them into
individual structured claims. Research gathers evidence — it never makes
the decision."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.compiler import TaskPackage
from app.agents.structured import AgentCaller
from app.prompts.templates import evidence_extraction_prompt, research_queries
from app.providers.registry import ProviderRegistry
from app.schemas.evidence import EvidenceItem, EvidenceLedger, ResearchMode, ResearchQuery
from app.workflow.budget import BudgetTracker

MODE_QUERY_LIMIT = {
    ResearchMode.NONE: 0,
    ResearchMode.TARGETED: 1,
    ResearchMode.STANDARD: 3,
    ResearchMode.DEEP: 5,
}


class EvidenceExtraction(BaseModel):
    items: list[EvidenceItem] = Field(default_factory=list)
    notes: str = ""


async def run_research(
    pkg: TaskPackage,
    mode: ResearchMode,
    registry: ProviderRegistry,
    caller: AgentCaller,
    budget: BudgetTracker,
    researcher_role: str = "researcher",
) -> EvidenceLedger:
    ledger = EvidenceLedger(mode=mode)
    if mode == ResearchMode.NONE:
        return ledger

    provider_name = caller.roles[researcher_role].provider
    research_provider = registry.get_research(provider_name)
    queries = research_queries(pkg, MODE_QUERY_LIMIT[mode])

    for query in queries:
        if budget.usage.research_queries >= budget.budget.max_research_queries:
            ledger.notes += " Research stopped early: query budget reached."
            break
        budget.check_hard_limits()
        result = await research_provider.research(query, mode.value)
        budget.add(result.usage)
        budget.add_research_query()
        ledger.queries.append(
            ResearchQuery(query=query, provider=provider_name, cost_usd=result.usage.cost_usd)
        )
        system, prompt = evidence_extraction_prompt(result.text, query)
        extraction, _ = await caller.structured(researcher_role, EvidenceExtraction, system, prompt)
        ledger.items.extend(extraction.items)
        if extraction.notes:
            ledger.notes = (ledger.notes + " " + extraction.notes).strip()
    return ledger
