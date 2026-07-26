# API

Interactive OpenAPI docs: `http://localhost:8000/docs` when the backend is
running. Summary below.

## Intake

### `POST /api/cases`
Create a case from the user's first message. Runs the Chief of Staff and
Context Gate; returns the assistant's reply (a clarifying question or
readiness confirmation).

```json
// request
{ "message": "Should I quit my job to start a meal-prep business?" }
// response
{ "case_id": "case_ab12...", "status": "intake", "assistant_message": "...", "version": 3 }
```

`status` is `intake` (answer the question) or `ready` (run the council).

### `POST /api/cases/{id}/messages`
Continue the intake conversation. Same response shape. 409 once intake is
closed.

## Running

### `POST /api/cases/{id}/run`
Start the pipeline as a background task. Also used to **resume** a `failed`
run — completed stages are never re-executed.

### `GET /api/cases/{id}/status`
Lightweight polling payload: overall status, route, per-stage progress with
user-facing labels, running cost, and any degradations (e.g. "audit skipped
(budget)"). No chain-of-thought is ever exposed.

### `GET /api/cases/{id}/result`
The nine-section user-facing response (recommendation, why it won,
disagreements, next action, seven-day plan, criteria, risks, assumptions,
confidence explanation) plus constraint-validation results. 409 until the
case is `complete`.

### `GET /api/cases/{id}`
Full case file (Council Room view): advisor responses, argument map, chairman
draft **and** final, audit, execution plan, evidence ledger, workflow state,
cost/latency metadata, model versions. Provider identity appears here for
transparency — it was hidden from the Chairman during deliberation.

## Revision & history

### `POST /api/cases/{id}/constraints`
Change one constraint; only the stages that constraint affects are
invalidated and rerun (research is preserved for budget/time changes).

```json
{ "constraint": { "kind": "budget", "description": "total budget", "value": "2000 USD", "hard": true } }
```

### `POST /api/cases/{id}/outcome`
Record an outcome review (`user_reported_outcome`, `usefulness_rating` 1-5,
optional rubric scores). Feeds the evaluation loop.

### `GET /api/cases`
Decision history (newest first).

### `GET /api/health`
App + provider health; reports whether mock mode is active.
