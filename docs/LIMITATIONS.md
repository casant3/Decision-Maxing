# Known limitations & next stage

## Known limitations (MVP)

1. **Real-provider paths are integration-tested only against mocked HTTP.**
   The five adapters follow each provider's documented wire format, but no
   live-API test ran in this environment (no keys). First run with real keys
   should start with `GET /api/health` and one `direct`-route case.
2. **Confidence numbers are subjective.** They are labelled as such everywhere,
   but nothing calibrates them against outcomes yet.
3. **Judge-based evaluation is weak under mock providers** — rubric scores are
   placeholders until real models fill both the council and the judge seats.
4. **Contradiction detection between plan and decision is heuristic**
   (keyword-based "experiment-style decision needs experiment-style actions").
   A semantic check via a small model call is the natural upgrade.
5. **Single user, no auth.** Cases are not scoped to accounts; the API trusts
   its caller. Do not expose publicly as-is.
6. **Polling, not streaming.** Progress arrives via 1.5 s polls; no SSE/WebSocket.
7. **Research depth is bounded**: "deep" mode means more Perplexity queries
   (and the deep-research model), not multi-hop agentic research.
8. **Data retention is a setting without an enforcement job** — `RETENTION_DAYS`
   exists but no scheduled purge runs in the MVP.
9. **The clarification loop is capped at 3 rounds** and the intake mock
   playbook is two-turn; real-model intake quality needs prompt iteration with
   transcripts.
10. **Cost tracking uses a static price table** (`app/config.py`); prices drift
    and should be reviewed when models change.

## Recommended next development stage

In order of expected value:

1. **Live-provider hardening.** Run the benchmark with real keys, fix wire
   quirks (especially Gemini JSON mode and Perplexity citations), and record
   real cost/latency baselines per route.
2. **Evaluation round-trip.** Wire `outcomes` + `eval_records` into a simple
   dashboard; start answering "does the full council beat direct?" with real
   scores — routing thresholds should then be tuned from data.
3. **Streaming progress + intake UX polish** (SSE, optimistic UI, editable
   case-file sidebar so users can correct extracted facts).
4. **Semantic constraint validator** (small-model check for plan/decision
   contradiction and unsupported-claim detection).
5. **Auth + multi-tenancy + retention job**, prerequisite for anything public.
6. **Confirmation gate for external actions** — the enum and workflow hooks
   exist; build the approval UI before adding any tool that spends money or
   publishes.
