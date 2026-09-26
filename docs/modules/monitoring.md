# Monitoring and real-time evidence

**What it does.** Times every request, counts errors, and serves the numbers from
an endpoint in both applications — plus the model metrics and the data summary, so
one call answers "is this healthy and is the model still the one you published".

**Where it lives.** `packages/pyshared/telemetry.py` (~110 lines), installed as
FastAPI middleware by each application's `main.py`, exposed as
`GET /api/monitoring` in both.

**Why it matters.** "Real-time decisions" and "process of monitoring" are both on
the judging list, and both are far easier to claim than to show. This is how we
show them: the panel can watch the counters move while they click.

---

## What it measures

Per endpoint, in a 200-entry ring buffer:

| | |
|---|---|
| `requests` | count |
| `errors` | responses with status ≥ 500 |
| `last_status` | the most recent status code |
| `p50_ms`, `p95_ms`, `max_ms` | latency percentiles |

Plus, across the process: `uptime_seconds`, total `requests`, total `errors` and
`error_rate`.

Every response also carries an **`X-Response-Time-Ms`** header, which is the
cheapest possible proof that a number was produced now rather than cached.

Static files (`/shared`, `/js`, `/css`, `/pages`, `/`) are deliberately excluded.
They would swamp the numbers and tell nobody anything about how fast a plan
solves.

## What else the endpoint returns

`/api/monitoring` is one call that answers three questions:

| Block | Answers |
|---|---|
| `application` | Is it healthy and fast? |
| `models` | Is the model that is serving the one we published — and did it pass its gate? |
| `data` | What is it planning over? |

For SupplyGuard, the `models` block reports the delay model's PR-AUC and ROC-AUC
against baseline, and **`label_sufficient` for all three targets** — so the same
endpoint that proves the app is up also states that two of the three risk models
are not good enough to use. For TrendWear it reports forecast WAPE against
seasonal naive, the cold-start method chosen, the achieved service level, and the
elasticity's `source` field (`"assumed"`).

That pairing is the design decision worth explaining: health and honesty in one
payload, because an application that reports 200 OK while serving a model that
failed its own gate is not actually healthy.

---

## Why it is this small

No Prometheus, no OpenTelemetry collector, no persistence — a ring buffer and a
lock. Three reasons, in order of honesty:

1. **We can explain all of it.** A hackathon prototype that shipped a monitoring
   stack nobody on the team could walk through would be worse than a hundred lines
   that four people understand.
2. **It has to work offline.** The demo runs from a laptop with the network off.
   An exporter with nowhere to export to is a dependency and a failure mode.
3. **It is enough to answer the question.** The criterion is whether we thought
   about monitoring, and per-endpoint p95 with an error rate is a real answer.

## What is missing, and costed

Said plainly, because this is the module where it would be easiest to overclaim:

| Missing | Why it matters | Cost |
|---|---|---|
| **Persistence** | Counters reset on restart, so there is no history and no trend | small |
| **Input and prediction drift** | The delay model's features will shift as the supply base changes, and nothing here would notice | 8 person-days |
| **Alerting** | Nobody is paged when live precision falls below the published 0.414 | in the same 8 |
| **Model registry and rollback** | Artifacts are joblib files in a folder; there is no version to roll back to | 12 person-days |
| **Business-metric monitoring** | Latency is easy; "is the plan still cheaper than what buyers do" is the number that actually matters, and it needs the shadow-running loop in Phase 1 | Phase 1 |

All of it is in [../estimate-and-roadmap.md](../estimate-and-roadmap.md).

---

## Solve times, which are the other half

The criterion is "real-time decisions", so the timings a panel actually sees
matter as much as the middleware:

| Operation | Time |
|---|---|
| Supplier allocation, one plant / two weeks | **0.30 s** (0.28–0.41 over 5 runs) |
| Supplier allocation, all eight plants | **9.1 s** |
| Production LP, 3 plants / 13 weeks | **0.2 s** |
| Cockpit KPIs | **0.03 s** (was 7.9 s before warming at startup) |
| Application startup | 10–15 s, loading tables and warming figures |

Every optimiser and planner response carries `solve_seconds`, and the screens print
it beside the result. That was a deliberate choice: a number with its own solve
time attached is visibly a decision made now, not a figure baked into a slide.

The cockpit is worth mentioning in the interview. It took 7.9 seconds because it
recomputed the full eight-plant plan on every request. An `lru_cache` plus a
`state.warm()` call at startup took it to 0.03 — the same answer, computed once.

## Tests

`tests/test_telemetry.py` — six tests: the snapshot counts a request, records a
duration, p95 is at least p50, an endpoint that raises increments the error count,
static paths are excluded, and both applications expose the endpoint.
