# Decision Council — Architecture

## 1. What currently exists

Nothing. The repository contained only a one-line README. Everything described
here is built from scratch in this MVP.

## 2. Architectural assessment (pre-implementation)

### Largest technical risks

| Risk | Mitigation chosen |
|---|---|
| **Structured-output fragility** — 10+ agent stages each requiring valid JSON from LLMs; one malformed response can wedge the pipeline | Strict Pydantic schemas + a uniform repair chain (repair prompt → reduced retry → fallback model → skip-if-safe), centralised in one place (`agents/structured.py`), never per-agent |
| **Provider coupling** — five providers with different APIs | Single `ProviderAdapter` interface; all real adapters are thin HTTP translations; everything above the adapter sees only `ProviderResult`. Mock provider implements the same interface, so the entire workflow is testable offline |
| **Workflow state loss / non-resumability** — long pipelines fail mid-run | Every stage is idempotent and persisted: stage results live in the versioned case file; the engine skips completed stages on re-entry and resumes from the first incomplete/invalidated stage |
| **Cost blowout** — a full council run is ~10 LLM calls + research | `BudgetTracker` enforced between stages with graceful degradation (5→3 advisors, skip audit on low stakes, downgrade research) before hard-stopping |
| **Prompt injection via research results** | Evidence is normalised to structured claims and rendered inside a clearly-delimited data block; a shared safety preamble (versioned, one place) is prepended to every agent prompt |
| **Framework lock-in** | No LangGraph. The pipeline is a linear list of stages with one loop (audit → revision) and field-based invalidation for reruns. A hand-rolled engine (~200 lines) is simpler, fully typed and testable. LangGraph can be adopted later if branching grows |

### Largest product risks

1. **The council may not beat one strong model.** This is an empirical question,
   which is why the eval harness (direct vs research-assisted vs lightweight vs
   full) is part of the MVP, not an afterthought.
2. **Over-questioning during intake** kills the experience. The Context Gate +
   "two plausible answers → different recommendations" rule and a hard
   clarification-round budget address this.
3. **Latency.** A full council run is minutes, not seconds. The UX therefore
   treats the run as a background job with meaningful progress states.

### MVP scope vs deferred

**In MVP:** full 13-stage workflow, versioned case file, 4 routes, 5 providers
behind adapters, mock-first testing, selective reruns, budgets and degradation,
eval harness with 7 benchmark cases, Next.js UI with Council Room, alembic
migrations, outcome capture.

**Deferred (documented in README):** authentication/multi-tenant, streaming
token output, real-time websockets (polling instead), LangGraph, deep-research
multi-hop chains, file uploads, human-in-the-loop payment/publishing actions,
calibration of confidence numbers, production observability stack (a structured
event log table is the MVP substitute).

### Simplifications made before coding

- **Database**: SQLAlchemy 2 async ORM. SQLite (aiosqlite) is the default so the
  system runs with zero infrastructure; PostgreSQL (asyncpg) is a
  `DATABASE_URL` switch. The alembic migration and the models use
  portable JSON types so both work.
- **User-facing response** is composed deterministically in code from
  structured stage outputs — no extra LLM call, no drift from the audited
  decision.
- **Argument Mapper convergence detection** ("same conclusion via same vs
  independent reasoning") is asked of the model and stored, not proven.
- **Progress**: polling `GET /cases/{id}/status`, not SSE.

## 3. System architecture

```
frontend (Next.js) ── REST ──> backend (FastAPI)
                                   │
                        ┌──────────┴──────────┐
                        │  Workflow Engine     │  linear stage list, idempotent
                        │  (state machine)     │  stages, budget checks between
                        └──────────┬──────────┘  stages, selective invalidation
                                   │
                 ┌────────┬────────┼─────────┬──────────┐
              agents   prompts  schemas   evidence   budget
                 │
                        ProviderRegistry
              ┌──────┬──────┬──────┬──────┬──────┬──────┐
           anthropic openai gemini  xai  perplexity  mock
                                   │
                          PostgreSQL / SQLite
              cases · case_versions · events · outcomes
```

### Workflow graph

```
USER ⇄ CHIEF OF STAFF ⇄ CONTEXT GATE          (intake loop, ≤ N rounds)
            │ ready
            ▼
     DECISION ROUTER ──► route ∈ {direct, research_assisted,
            │                     lightweight_council, full_council}
            ▼
  CONTEXT & TASK COMPILER  (structured task package, no paraphrase chains)
            ▼
     RESEARCH ROUTER ──► {none, targeted, standard, deep} ──► EVIDENCE LEDGER
            ▼
   ADVISORS (parallel, isolated, anonymised, order randomised)
     contrarian · first_principles · expansionist · outsider · customer_advocate
            ▼
     ARGUMENT MAPPER  (extracts options/agreements/conflicts; does not decide)
            ▼
       CHAIRMAN (draft)  — weighted criteria scoring, no majority vote
            ▼
     DECISION AUDITOR  — defects + pre-mortem, no alternative answer
            ▼
    CHAIRMAN REVISION  — final decision (draft preserved)
            ▼
        EXECUTOR  — now/7-day/30-day plan; cannot reopen strategy
            ▼
   CONSTRAINT VALIDATOR ──invalid──► route back to the offending stage only
            ▼ valid
    USER-FACING RESPONSE (composed in code) + Council Room detail
```

Route shortcuts: `direct` skips research+advisors+mapper+audit (single answer
stage); `research_assisted` runs research then a single synthesis;
`lightweight_council` runs 3 advisors and keeps the audit only for
medium/high stakes.

## 4. Data model

- **cases** — id, title, status, current_version, timestamps.
- **case_versions** — full JSON snapshot of the `CaseFile` per version, with a
  `reason` string. Every state change = new version (auditable, supports
  debugging and evaluation).
- **events** — append-only log: stage started/finished, provider calls, cost,
  latency, failures, degradations.
- **outcomes** — user-reported outcome reviews + rubric scores for evaluation.

The `CaseFile` (Pydantic) is the single source of truth and keeps
**user-confirmed facts, externally verified evidence and system inferences in
separate collections** — they are never merged.

## 5. Provider abstraction

```python
class ProviderAdapter(Protocol):
    name: str
    async def generate_text(req)        -> ProviderResult
    async def generate_structured(req)  -> ProviderResult   # JSON mode
    async def health_check()            -> bool
    # research() exists only on ResearchProvider (Perplexity, Mock)
```

Retries with exponential backoff, timeouts, a per-provider circuit breaker and
token/cost accounting live in the shared base class. Model↔role assignment is
configuration (`RoleConfig`: provider, model, fallback provider/model, timeout,
max retries, cost limit, context limit) — not code.

## 6. API design

| Method & path | Purpose |
|---|---|
| `POST /api/cases` | create case from first user message → CoS reply |
| `POST /api/cases/{id}/messages` | continue intake conversation |
| `POST /api/cases/{id}/run` | start the council pipeline (background) |
| `GET  /api/cases/{id}/status` | lightweight progress for polling |
| `GET  /api/cases/{id}` | full case file (council room data) |
| `GET  /api/cases/{id}/result` | user-facing response |
| `POST /api/cases/{id}/constraints` | change a constraint → selective rerun |
| `POST /api/cases/{id}/outcome` | record outcome review |
| `GET  /api/cases` | decision history |
| `GET  /api/health` | provider + app health |

## 7. Security posture (MVP)

API keys server-side via env vars only; never sent to the client. No secrets in
logs (event payloads are schema'd). Retrieved web content is treated as data:
structured claims, delimited evidence blocks, shared anti-injection preamble on
every agent. Frontend renders text through React escaping only (no
`dangerouslySetInnerHTML`). Data retention window configurable
(`RETENTION_DAYS`). Any future paid/destructive/external action requires an
explicit confirmation gate (the enum exists; no such actions in MVP).

## 8. Directory structure

```
backend/
  app/
    main.py            FastAPI app factory
    config.py          settings, role/model config, budgets, prices
    db.py              async engine/session
    models.py          ORM tables
    repo.py            case repository (versioning, events)
    schemas/           case_file, evidence, agents, workflow, presentation
    providers/         base, mock, anthropic, openai_compat, gemini, registry
    agents/            structured-call core + one module per agent
    prompts/           versioned templates + shared safety rules
    workflow/          engine, stages, routing rules, budget, rerun map
    api/               routes
  alembic/             migrations
  tests/
  eval/                harness + benchmark cases
frontend/              Next.js (app router, TS)
docs/
```
