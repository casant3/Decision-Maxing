# Decision Council

A multi-model AI decision council. You describe a decision; a Chief of Staff
asks only the questions that would change the recommendation; independent
advisors (different model families, different analytical lenses) analyse the
same structured brief in parallel; a Chairman scores the options against
weighted criteria; an independent Auditor stress-tests the draft; an Executor
turns the final decision into a budget-checked action plan.

It behaves like a controlled decision process, not a role-play between AI
personalities: shared evidence, independent interpretation, preserved dissent,
audited output.

```
USER ⇄ Chief of Staff ⇄ Context Gate            (intake, ≤3 clarification rounds)
        │ ready
        ▼
  Decision Router → direct | research-assisted | lightweight (3) | full council (5)
        ▼
  Context & Task Compiler → Research Router → Evidence Ledger (structured claims)
        ▼
  5 advisors in parallel (anonymised, isolated) → Argument Mapper
        ▼
  Chairman draft → Decision Auditor (pre-mortem) → Chairman revision
        ▼
  Executor → Constraint Validator (deterministic; loops back to the offending stage)
        ▼
  User-facing response (composed in code) + expandable Council Room
```

## Quick start (no API keys needed)

The system runs fully offline on a deterministic mock provider.

```bash
# backend — http://localhost:8000 (OpenAPI docs at /docs)
cd backend
uv sync
uv run alembic upgrade head          # or skip: tables auto-create on startup
uv run uvicorn app.main:app --port 8000

# frontend — http://localhost:3000
cd frontend
npm install
npm run dev
```

Open http://localhost:3000, describe a decision, answer the follow-up, and
convene the council.

### Real providers

```bash
cd backend && cp .env.example .env
# set USE_MOCK_PROVIDERS=false and add the API keys you have
```

Roles fall back per-role: a role whose provider has no key uses the mock, and
every structured call has a configured fallback model. Model↔role assignment
lives in `app/config.py` (`DEFAULT_ROLES`) and can be overridden with a JSON
file via `ROLE_CONFIG_PATH` — assignments are hypotheses, not code.

## Tests

```bash
cd backend
uv run pytest        # 74 tests
uv run ruff check app tests eval
```

Coverage includes: routing rules, clarification budget, stage invalidation and
selective rerun, the structured repair→retry→fallback ladder, HTTP-mocked
provider adapters (retry, circuit breaker), prompt-injection containment,
budget degradation, partial provider failure, resume-after-failure, and the
guard preventing the Executor from silently dropping the Chairman's strategy.

## Evaluation harness

Does the council actually beat one strong model? That is measurable:

```bash
cd backend
uv run python -m eval.harness                      # all 7 benchmark cases × 4 modes
uv run python -m eval.harness --modes direct,full --cases bench_career_decision
```

Each benchmark case runs as `direct`, `research_assisted`, `lightweight` and
`full`, then a judge model scores the output on a five-dimension rubric;
cost, model calls and latency are reported alongside. Results land in
`backend/eval/results/`. With mock providers the scores are placeholders —
point it at real keys for meaningful comparisons.

## Key design decisions

- **Versioned case file.** Every state change writes a full JSON snapshot
  (`case_versions`) plus an append-only event log. User-confirmed facts,
  externally verified evidence and system inferences are separate collections
  — never merged.
- **Hand-rolled state machine, no LangGraph.** The pipeline is a linear stage
  list with one audit loop and field-based invalidation; ~200 lines, fully
  typed, resumable. Framework complexity wasn't justified at this branching
  level.
- **Selective reruns.** Changing the budget invalidates compile→advisors→…→plan
  but *keeps research*; changing the objective invalidates research too
  (`app/workflow/rerun.py`).
- **Deterministic where possible.** Routing rules, the constraint validator and
  the user-facing response composer are plain code — testable, explainable,
  and immune to model drift.
- **Anonymised advisors.** Provider/model identity is logged for evaluation but
  stripped before the Chairman sees responses; advisor order is shuffled
  (seeded per case version).
- **Budgets with graceful degradation.** Between stages the engine can shrink
  the council 5→3, skip the audit, downgrade research, or adopt the draft as
  final — before hard-stopping.
- **Injection defence.** Research output is normalised into structured claims,
  rendered inside delimited data blocks, and every agent prompt carries a
  shared, versioned safety preamble (`app/prompts/shared.py`).

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
[docs/API.md](docs/API.md) · [docs/LIMITATIONS.md](docs/LIMITATIONS.md)

## Repository layout

```
backend/
  app/
    config.py        role↔model assignments, budgets, price table
    schemas/         Pydantic schemas (case file, evidence, agents, workflow)
    providers/       adapter interface + anthropic/openai/xai/perplexity/gemini/mock
    agents/          structured-call core, intake, research, advisors, council, validator
    prompts/         versioned templates + shared safety rules
    workflow/        engine, routing rules, budget, selective rerun, presenter
    api/             REST routes
  alembic/           migrations
  tests/             74 tests
  eval/              benchmark cases + comparison harness
frontend/            Next.js app (intake, progress, result, Council Room)
docs/                architecture, API, limitations, checklist
```
