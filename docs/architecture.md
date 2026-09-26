# Architecture

Two applications, one repository, no shared runtime. This describes what we
built, and then the production path we did **not** build — clearly separated,
because conflating the two is the easiest way to mislead a panel.

---

## 1. Why two applications

The mentor's written ruling was two separate, non-overlapping solutions for the
two use cases. So SupplyGuard (PR1) and TrendWear Planner (P2) share no data, no
models, no database and no process. They live in one repository because the team
is four people and one CI pipeline, one test suite and one set of shared
front-end components are worth having.

The separation is enforced, not promised. `tests/test_separation.py` fails the
build if either application imports the other, and a container test fails if
either image mentions the other's code. What they do share is deliberately
generic: number formatting, a sortable table, a chart wrapper, time-series
splitting helpers, and request telemetry — none of which knows anything about
procurement or apparel.

```
vortex5-scm/
├── apps/
│   ├── pr1/                       SupplyGuard — procurement
│   │   ├── backend/supplyguard/   ETL -> risk -> optimiser -> scenarios -> API
│   │   ├── web/                   6 screens, plain HTML/CSS/JS
│   │   └── Dockerfile
│   └── p2/                        TrendWear Planner — S&OP
│       ├── backend/trendwear/     ETL -> forecast -> plan -> markdown -> API
│       ├── web/                   7 screens
│       └── Dockerfile
├── packages/
│   ├── pyshared/                  metrics, time splits, logging, telemetry
│   └── web/                       tokens.css, base.css, table.js, chart.js
├── data/raw/                      6 Kaggle datasets, 212 MB, gitignored
├── data/processed/                the planning cache, per app, gitignored
├── models/                        fitted models, per app
├── scripts/                       fetch_data, build_demo_pack, stage_space
├── docs/                          this set
└── tests/                         350 tests
```

---

## 2. What we built — SupplyGuard (PR1)

```
    data/raw  (Kaggle, 6 datasets)
      SCMS delivery history  ..... 10,324 real purchase orders
      Google Cloud SAP demo  ..... materials, plants, vendor master
      procurement KPI sets   ..... quality events, order lines
                 |
                 |  etl/     parse, clean, label the origin of every row
                 v
    520 suppliers (217 real, 303 generated)  ·  16 materials  ·  8 plants
    376 approvals  ·  376 priced offers
    every row carries origin: real | public-synthetic | generated
                 |
       +---------+------------------------+
       |                                  |
       |  features/build.py               |  etl/requirements.py
       |  point-in-time only:             |  demand by material,
       |  shift(1) + expanding windows    |  plant and week
       v                                  v
    risk/  three models                 384 requirement lines
      delay       random forest,        1.80 M units over 8 weeks
                  PR-AUC 0.347 vs
                  0.264 baseline  -> sufficient
      quality     not sufficient  -> supplier observed rate
      disruption  not sufficient  -> supplier observed rate
      each one states which, on the Models screen
       |
       |  delay and quality probabilities, per offer
       v
    optimizer/  MILP, PuLP + CBC
      minimise   material cost
               + P(late) x units x shortage penalty
               + P(quality event) x units x rework cost
      subject to demand met in full; approved suppliers only;
                 capacity per supplier, material and week;
                 lead time fits the horizon; MOQ (binary linked down);
                 at least 2 suppliers per material; max 40% concentration;
                 contract minimums
      relaxation ladder if infeasible, and it always reports what it relaxed
       |
       +----------------------+---------------------------+
       v                      v                           v
    baselines/            scenarios/                   narrative/
     cheapest-first        demand spike                 the plan in English,
     equal split           supplier outage              with the trade named
     historical mix        price shock
                           lead-time shock
       |                      |                           |
       +----------------------+---------------------------+
                 v
    api/   FastAPI, 14 endpoints, telemetry middleware
    web/   6 screens: cockpit, suppliers, allocate, risk check,
           scenarios, models
```

Measured, on the largest plant over two weeks: **25.0% lower total cost** than
the way this organisation actually bought, **12.4% fewer expected late units**,
and **1.3 points less volume** on high-risk suppliers than buying cheapest-first
— for 6.4% more on the invoice. That last number is the point: the plan is
dearer on paper and cheaper in reality.

---

## 3. What we built — TrendWear Planner (P2)

```
    data/raw/retail  (public synthetic, Kaggle)
      2 years of store-level demand across 5 stores
      labelled synthetic on every screen that shows it
                 |
                 |  etl/   weekly rates, 106 weeks, observation counts kept
                 v
    60 styles (20 from the data, 40 generated)  ·  3 plants
    5 stores  ·  6 fabrics
                 |
       +---------+---------------------------+
       v                                     v
    forecast/model.py                     forecast/coldstart.py
     LightGBM, chronological split          nearest analogue by attributes
     WAPE 0.337 vs 0.445 seasonal naive     WAPE 0.378 vs 0.417 category avg
       |                                     |
       +-----------------+-------------------+
                         v
    13-week demand forecast  ·  608,296 units
                         |
       +-----------------+------------------+------------------+
       v                                    v                  v
    inventory/                          production/          markdown/
     safety stock z x sigma x sqrt(L)     LP over 3 plants     sell-through
     95% planned, 96.8% achieved          capacity and         against plan;
     in a 2,722-week backtest             changeover           revenue with
       |                                  660,350 units        salvage, because
       |                                  peak use 100%        the buy is sunk;
       |                                     |                 elasticity -1.8,
       |                                     v                 assumed, and the
       |                               fabric/                 screen says so
       |                                Wagner-Whitin lot        |
       |                                sizing, MOQ and          |
       |                                5-week lead time         |
       +-----------------+-------------------+------------------+
                         v
    sop/reconcile.py     three plans, one agreed number
      merchandising 696k   ·   forecast 600k   ·   supply 652k
      gap 102,318 units = ₹47.3 crore   ·   consensus 604,409 units
      the consensus may be lowered by hand, never raised above supply
    sop/cycle.py         rolling monthly cycle, 5 stages, versioned
    sop/financials.py    revenue, margin, inventory, distribution cost
    sop/distribution.py  DC to store lanes and lead times
                         v
    api/   FastAPI, 13 endpoints, telemetry middleware
    web/   7 screens: cockpit, reconcile, merchandising, production,
           logistics, inventory, markdown
```

---

## 4. The runtime, in one paragraph

Each application is a single FastAPI process. At startup it loads its processed
tables from parquet and its fitted models from joblib, then warms the headline
figures. Nothing is trained while it serves — a test fails the build if training
code appears in an API module. The front end is plain HTML, CSS and ES modules
served by the same process, so there is no build step and nothing to go wrong
between the code we wrote and the page a judge sees. Requests are timed by
middleware, and `/api/monitoring` reports counts, error rate and p50/p95 latency
per endpoint. A plan solves in about 0.3 seconds for a plant-week slice and
about eight seconds for all eight plants at once.

---

## 5. What we did **not** build: the production path

This is the honest part. The diagram below is the integration a real deployment
needs, and we built only the middle of it.

```
    SAP / ERP  (the system of record)
      materials, vendors, purchase orders, goods receipts,
      the approved supplier list, contracts, capacity
                 |
                 |  (1) scheduled nightly extract, or an OData/API pull
                 v
    Landing and validation                                    NOT BUILT
      schema checks, referential integrity, freshness,
      duplicate and outlier quarantine, an audit trail
                 |
                 |  (2) typed, dated, versioned tables
                 v
    Feature store and model registry                          NOT BUILT
      point-in-time features, training runs, lineage
      (we use parquet files and joblib, which is honest for a prototype)
                 |
                 |  (3)
                 v
  ============================================================
   THE PLANNING ENGINE  --  this is what we built
     risk models · MILP/LP optimiser · scenario engine ·
     S&OP reconciliation · FastAPI · the thirteen screens

     <-- the attachment point is the ETL boundary: replace the
         extract layer and everything above this line is unchanged
  ============================================================
                 |
                 |  (4) a proposed plan, never an automatic order
                 v
    Planner review                                         PARTLY BUILT
      a human accepts, edits or rejects each line, with the reason shown.
      We show the reason and allow the consensus override. We have no
      approval workflow, no roles, and no audit of who changed what.
                 |
                 |  (5) approved plan
                 v
    Write back to the ERP                                     NOT BUILT
      purchase requisitions, planned orders, consensus numbers --
      idempotent, reconciled, reversible
```

**The attachment point is our ETL boundary.** Every module downstream of it
reads typed dataframes with named columns, not files. Replacing `etl/` with an
SAP extract changes one layer; the risk models, the optimiser, the
reconciliation and all thirteen screens are untouched. That is the claim we can
defend, and it is why [reusability.md](reusability.md) is written about that
boundary.

**What we are not claiming.** No authentication, no roles, no database beyond
SQLite for a cache, no scheduled retraining, no alerting, no data-quality gate,
and no write path back into any system of record. A prototype that pretended
otherwise would fall apart under one question from anyone who has actually run
an S&OP cycle.

---

## 6. Deployment

```
    developer push
         |
         v
    GitHub Actions: CI
      ruff  ·  350 pytest  ·  32 node --test
      data/raw restored from cache, not re-downloaded
         |
         |  on success, main only
         v
    GitHub Actions: Deploy
      build the demo pack (every seed pinned)
      stage one Space directory per application
      push to Hugging Face with HF_TOKEN
         |
         +-------------------------+
         v                         v
    Space: supplyguard       Space: trendwear-planner
    Docker, port 7860        Docker, port 7860
    31 MB, Git LFS for the   2 MB
    29 MB delay model
```

The demo itself runs from a laptop. The Spaces are the link we leave behind, not
the thing we present from — see [runbook.md](runbook.md) §6 for why, and for what
to do when one is asleep.
