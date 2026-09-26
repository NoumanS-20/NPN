# Estimation and roadmap

A listed deliverable: what this took, what a production build would additionally
need, and a phased plan with rough timelines.

**How to read the effort column.** These are person-day estimates of the work each
module represents — what a competent team should budget to build the same thing
from the same starting point. They are not a timesheet. The calendar was
compressed: this repository was designed and built over the week ending
28 September 2026, in parallel across the four of us, with long days. Anyone
planning a similar build should use the person-day column and their own team's
capacity, not our calendar.

---

## 1. What the prototype took

### SupplyGuard (PR1)

| Module | Person-days | Notes |
|---|---|---|
| Data acquisition, licence review, provenance | 1.5 | Six Kaggle datasets; verifying which are actually real cost more than downloading them |
| ETL: SCMS, SAP demo, procurement sets | 3.0 | The freight-parsing defect alone cost half a day and a regression test |
| Synthetic suppliers, offers, capacity | 2.5 | Capacity scale was wrong twice before it bound |
| Requirements and approved supplier list | 1.0 | |
| Point-in-time feature build | 1.5 | `shift(1)` plus expanding windows; the only way to avoid leakage |
| Three risk models plus the sufficiency gate | 3.0 | Includes the calibration experiment we reverted |
| Allocation MILP | 3.5 | Four separate infeasibility causes, each fixed at source |
| Baselines and the comparison | 1.0 | |
| Scenario engine, four scenarios | 1.5 | Lead-time shock needed the horizon allowance tuned |
| Narrative explanations | 0.5 | |
| API, 14 endpoints | 1.5 | |
| Six screens | 3.0 | |
| **Subtotal** | **24.0** | |

### TrendWear Planner (P2)

| Module | Person-days | Notes |
|---|---|---|
| Retail ETL, weekly rates | 1.5 | The data is sparse, not daily; that discovery reshaped the module |
| Synthetic styles, BOM, capacity, lanes | 2.0 | |
| Demand forecast | 2.0 | |
| Cold start | 1.0 | |
| Safety stock and the backtest | 1.0 | |
| Production LP | 1.5 | |
| Fabric lot sizing | 1.0 | |
| Markdown: elasticity, recommendation | 2.0 | Including the fit we measured, rejected, and replaced with a stated assumption |
| S&OP reconciliation, cycle, financials, distribution | 3.0 | The core of the use case |
| API, 13 endpoints | 1.5 | |
| Seven screens | 3.5 | |
| **Subtotal** | **20.0** | |

### Shared and cross-cutting

| Item | Person-days |
|---|---|
| Repository setup, CI, dependency pinning | 1.5 |
| Shared Python package: metrics, time splits, logging | 1.0 |
| Shared front-end kit: tokens, layout, table, charts, formatters | 3.0 |
| Telemetry and the monitoring endpoints | 1.0 |
| Containers, Space staging, the deploy workflow | 1.5 |
| Demo pack, preloaded scenarios, the checklist | 1.0 |
| Documentation set (this one included) | 3.0 |
| Test suite: 350 Python, 32 JavaScript | folded into each module above |
| **Subtotal** | **12.0** |

### Total

| | Person-days |
|---|---|
| SupplyGuard | 24.0 |
| TrendWear Planner | 20.0 |
| Shared | 12.0 |
| **Prototype total** | **56.0** |

About **eleven weeks for one engineer**, or **under three weeks for a team of
four** — which is roughly the shape of what four people should expect to spend
reproducing this from the datasets.

---

## 2. What a production build additionally needs

Nothing in this section is built. Every item is something a real deployment cannot
skip, and the estimates assume a team already fluent in the company's stack.

| Capability | Person-days | Why it is not optional |
|---|---|---|
| **Authentication and roles** | 8 | A buyer may run a plan; only a planning manager may change the consensus. Right now anyone who can open the page can do either. |
| **A real database** (PostgreSQL) with migrations | 10 | Parquet files are a demo artefact. Concurrent planners, history and audit need a database. |
| **ERP / SAP connector, read path** | 20 | The nightly extract, its schema contract, and reconciliation against the source of record. Usually the longest-running item in the whole project. |
| **ERP write-back** (requisitions, planned orders) | 20 | Idempotent, reversible, reconciled. This is where a mistake costs money, so it needs the most care and the most testing. |
| **Data-quality gate** | 10 | Schema, referential integrity, freshness, duplicate and outlier quarantine, with a report a planner reads before trusting a plan. |
| **Retraining pipeline and model registry** | 12 | Scheduled retraining, the sufficiency gate run automatically, versioned artifacts, and the ability to roll back a model. |
| **Drift monitoring and alerting** | 8 | Input drift, prediction drift, and an alert when the delay model's live precision falls below what we published. |
| **Approval workflow and audit** | 10 | Who proposed, who approved, what changed, when. Non-negotiable in procurement. |
| **Scale and performance work** | 8 | Our MILP is nine seconds on eight plants. A real network is hundreds of plants and thousands of materials; that needs decomposition, warm starts, or OR-Tools. |
| **Hardening, logging, error handling, runbooks** | 8 | |
| **User testing with real planners** | 10 | The screens were designed for a demo. Real planners will want different defaults, bulk edits, and exports. |
| **Security review and penetration test** | 6 | |
| **Production total** | **130** | |

**Roughly 26 weeks for one engineer, or 7 to 9 weeks for a team of four** — and
that is on top of the prototype, not instead of it.

---

## 3. Roadmap

### Phase 1 — Pilot on real data (6 to 8 weeks)

The goal is one plant and one category, running beside the existing process, with
nobody's job depending on it yet.

- Replace both ETL layers with extracts from the real ERP (§2, read path only).
- Add the data-quality gate, because the first thing real data does is break an
  assumption.
- Re-run the sufficiency gate on real labels. With more than 71 quality events and
  136 disruptions, the two models we refused to ship may pass. If they do, nothing
  else changes.
- Add authentication and the approval workflow.
- Run in shadow mode: the plan is produced and compared to what buyers actually
  did, weekly, for six weeks.

**Exit test:** the plan beats what the buyers did on landed cost over six weeks of
shadow running, and the delay model's live precision is within a few points of the
0.41 we published.

### Phase 2 — Production for one business unit (8 to 12 weeks)

- PostgreSQL with migrations, history and audit.
- ERP write-back for requisitions, behind planner approval. No automatic orders.
- Retraining pipeline, model registry and rollback.
- Drift monitoring and alerting.
- Performance work to hold the solve under a minute at business-unit scale.
- User testing with the planners who will actually live in these screens.

**Exit test:** a monthly cycle runs end to end with the planning team using it as
their primary tool, and a plan can be reproduced exactly from its version record.

### Phase 3 — Scale and extend (two to three quarters)

- Roll out to the remaining business units, one at a time.
- Multi-tier supply risk: today we model our direct suppliers, not theirs.
- Supplier-facing portal for capacity confirmation, which removes the biggest
  single assumption in [assumptions.md](assumptions.md).
- Optimise inventory across the network rather than per style-store.
- Replace the assumed markdown elasticity with one fitted to real promotional
  data, once there is enough of it. This is the first thing we would fix.
- Revisit the optimiser: OR-Tools with decomposition if instance size demands it.

---

## 4. The three risks we would flag to a sponsor

1. **The ERP integration is the project.** Both connector items (40 person-days)
   are larger than either application we built. Any plan that treats them as
   plumbing will slip.
2. **Two of the three risk models need more labelled history than exists today.**
   The honest answer is to instrument quality events and disruptions properly and
   wait a year, not to fit a model harder.
3. **Supplier capacity is currently an assumption everywhere.** The optimiser is
   only as good as the capacity numbers, and today they are generated from
   observed shipment rates. Phase 3's supplier portal is not a nice-to-have; it is
   what makes the plan trustworthy.
