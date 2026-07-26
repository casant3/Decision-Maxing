# Implementation checklist

## Phase 1 — Architecture
- [x] System architecture, workflow graph, data model (docs/ARCHITECTURE.md)
- [x] Agent schemas (app/schemas/agents.py)
- [x] Provider abstraction design (app/providers/base.py)
- [x] API design (docs/API.md)
- [x] Security considerations, MVP vs deferred scope, directory structure

## Phase 2 — Backend foundation
- [x] FastAPI app factory + CORS + lifespan DB init
- [x] Settings with role/model config, budgets, price table, retention setting
- [x] Async SQLAlchemy (SQLite default, Postgres via DATABASE_URL)
- [x] Versioned CaseFile aggregate; separated fact origins
- [x] Workflow state models (stages, records, budget usage)
- [x] Provider interface + deterministic mock provider
- [x] Append-only event logging

## Phase 3 — Core workflow (mock-first)
- [x] Chief of Staff (question-only-when-decision-changing, ≤3 questions)
- [x] Context Gate (readiness score/status, safe assumptions, next question)
- [x] Decision Router (LLM stakes assessment + deterministic route rules)
- [x] Context & Task Compiler (structured package, original request verbatim)
- [x] Research router (none/targeted/standard/deep) + evidence ledger
- [x] Five advisors, parallel, isolated, anonymised, order randomised
- [x] Argument Mapper (options/agreements/conflicts/convergence; no decision)
- [x] Chairman draft (weighted criteria scoring, no majority vote)
- [x] Decision Auditor (defect list + pre-mortem, no alternative answer)
- [x] Chairman revision (draft preserved alongside final)
- [x] Executor (now/7-day/30-day, dependencies, costs, milestones)
- [x] Constraint Validator (deterministic; stage-targeted repair loops)
- [x] User-facing response composed in code; Council Room detail endpoint
- [x] Budgets with graceful degradation (5→3 advisors, skip audit, cap research)
- [x] Idempotent stages, resume-after-failure, selective reruns

## Phase 4 — Providers
- [x] Anthropic adapter (Messages API)
- [x] OpenAI-compatible adapter (OpenAI, xAI, Perplexity)
- [x] Gemini adapter (generateContent)
- [x] Perplexity research capability
- [x] Retries w/ backoff, timeouts, circuit breaker, cost/token accounting
- [x] Structured repair → reduced retry → fallback model → skip-if-safe ladder
- [ ] Live-API verification with real keys (blocked in this environment)

## Phase 5 — Frontend
- [x] New decision + conversational intake + clarification state
- [x] Research/council progress states (no chain-of-thought)
- [x] Final recommendation (nine sections)
- [x] Council Room (advisors, scores, evidence, disagreements, audit)
- [x] Decision history, constraint-change rerun, outcome review
- [x] Headless-browser end-to-end verification

## Phase 6 — Evaluation & hardening
- [x] 74-test suite (routing, state, schemas, adapters, injection, budgets,
      partial failure, rerun, executor guard)
- [x] Alembic initial migration
- [x] Benchmark dataset (7 representative cases)
- [x] Harness comparing direct / research-assisted / lightweight / full
- [x] Cost & latency reporting per run and per stage
- [ ] Real-outcome feedback loop dashboard (deferred — see LIMITATIONS.md)
- [ ] Retention purge job (deferred)
