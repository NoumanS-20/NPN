# NPN SCM — Team Vortex5

Two independent supply-chain planning applications, built for the Cognizant NPN
SCM Hackathon, use cases **PR1 + P2**.

| | **SupplyGuard** (PR1) | **TrendWear Planner** (P2) |
|---|---|---|
| The question | Given what eight plants need next month, which approved suppliers get how much — and will they deliver on time? | What do we make, when does it move, when do we discount it, and what number does the business commit to? |
| Core method | Delivery-risk prediction feeding a mixed-integer optimiser that prices risk in money | Demand forecasting feeding constrained production, fabric lot sizing and S&OP reconciliation |
| Lives in | `apps/pr1/` | `apps/p2/` |
| Screens | 6 | 7 |

---

## What they do, in numbers

Everything below is measured, not aspirational. The sources are
`data/processed/*/metrics.json` and live API responses; the full list is in
[docs/interview-prep.md](docs/interview-prep.md).

### SupplyGuard (PR1)

- **10,324 real purchase orders** (SCMS delivery history), 520 suppliers, 16
  materials, 8 plants, an 8-week horizon over 1.80 M units.
- The plan costs **25.0% less in total** than the way this organisation actually
  bought, with **12.4% fewer expected late units**.
- Against buying cheapest-first it is **6.4% dearer on the invoice** and carries
  **1.3 points less volume** with high-risk suppliers. That trade is the product.
- Delivery-delay model: random forest, **PR-AUC 0.347** against a 0.264 baseline,
  ROC-AUC 0.825, on 2,581 chronologically held-out orders.
- Quality and disruption models **failed their sufficiency gate** (71 and 136
  positive labels), so the application falls back to each supplier's observed
  rate and says so on screen.
- Solve time: about 0.3 s for one plant over two weeks, 7.9 s for all eight plants.
- Four scenarios — supplier outage, demand spike, lead-time shock, price shock —
  each re-solved, not scaled.

### TrendWear Planner (P2)

- 60 styles (20 from the data, 40 generated), 106 weeks of history, 3 plants,
  5 stores, 6 fabrics.
- Demand forecast: LightGBM, **WAPE 0.340** against 0.445 for seasonal naive.
  Cold start for styles with no history: **0.378** against 0.417 for a category
  average.
- Safety stock planned at a 95% service level, **96.8% achieved** in a
  2,722-week backtest.
- The reconciliation: merchandising wants 696k units, the forecast says 600k, the
  plants can make 652k — a gap of **99,686 units worth 5.56 M**. The consensus
  can be lowered by hand and never raised above supply.
- Revenue 32.9 M, gross margin 18.0 M (54.6%), 10 styles recommended for markdown
  worth 159 k in recovered margin.
- Production LP solves in 0.2 s at 100% peak capacity utilisation with zero
  shortfall.

### The repository

**350 Python tests · 32 JavaScript tests · ruff clean · 13 screens · 2 containers.**

---

## Where the data comes from

Six public Kaggle datasets, 212 MB, fetched by `scripts/fetch_data.py` and not
committed. Licences and provenance per dataset:
[docs/data-sources.md](docs/data-sources.md).

Three tiers, and **every row carries its tier**:

| Tier | What it means | Example |
|---|---|---|
| **real** | Genuine transaction data | The 10,324 SCMS purchase orders |
| **public-synthetic** | A public dataset that is itself synthetic | The retail demand history behind P2 |
| **generated** | Invented by us, method documented | Supplier capacity, prices, the merchandising plan |

Accuracy figures are computed on **real rows only**. What we generated and how is
in [docs/assumptions.md](docs/assumptions.md).

Four things we volunteer rather than wait to be asked:

1. P2's dataset is public **synthetic** data, not real sales.
2. The markdown **elasticity is assumed** (−1.8, a published apparel figure)
   because our own fit explained 0.0% of the variation.
3. Supplier **capacity, prices and the merchandising plan are generated** by us.
4. **Two of the three risk models are not good enough to use**, so they are not
   used.

Each of these is printed on the screen it affects.

---

## The separation rule

The mentor's written ruling was two separate, non-overlapping solutions. So the
two applications share **no data, no models, no database and no runtime calls**.

`packages/` holds only plumbing — number formatting, a sortable table, chart
helpers, chronological splitting, request telemetry — and never domain logic.
`tests/test_separation.py` fails the build if either application imports the
other, and `tests/test_dockerfiles.py` fails it if either image mentions the
other's code.

- **SupplyGuard chooses between suppliers.** It does not forecast; its material
  requirements are a deterministic roll-up of history.
- **TrendWear Planner decides quantities and timing.** It buys fabric from a
  single source under MOQs and lead times; it never allocates across suppliers.

---

## Running it

Python 3.12. Full detail, including containers and deployment, in
[docs/runbook.md](docs/runbook.md).

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
pip install pytest httpx ruff kaggle
```

```bash
python scripts/fetch_data.py          # 212 MB, needs a Kaggle token
python scripts/build_demo_pack.py     # ~4 min: processed tables + fitted models
```

```bash
python -m uvicorn supplyguard.main:app --port 8001 --reload
```
```bash
python -m uvicorn trendwear.main:app --port 8002 --reload
```

- SupplyGuard → <http://127.0.0.1:8001>
- TrendWear Planner → <http://127.0.0.1:8002>
- API docs → `/docs` on either; monitoring → `/api/monitoring`

Both applications **load** pre-built models and never train while serving — a test
fails the build if training code appears in an API module. Both run entirely
offline once the demo pack is built.

### Tests

```bash
python -m pytest -q
python -m ruff check .
```
```bash
cd packages/web && node --test
```

Tests that read raw data skip themselves when it is absent, so the suite is
meaningful on a fresh clone with no Kaggle token.

---

## Layout

```
apps/pr1/backend/supplyguard/   ETL -> risk -> optimiser -> scenarios -> API
apps/p2/backend/trendwear/      ETL -> forecast -> plan -> markdown -> S&OP -> API
apps/*/web/                     HTML, CSS and ES modules — no framework, no build step
apps/*/Dockerfile               one image per application, port 7860
packages/pyshared/              metrics, chronological splits, logging, telemetry
packages/web/                   design tokens, layout, sortable table, chart helpers
data/raw/                       source datasets (gitignored; scripts/fetch_data.py)
data/processed/                 the planning cache, per application (gitignored)
models/                         fitted models, per application
scripts/                        fetch_data · build_demo_pack · stage_space
docs/                           everything below
tests/                          350 repository-wide tests
```

---

## Documentation

| | |
|---|---|
| [architecture.md](docs/architecture.md) | What we built, and the production path we did not build |
| [interview-prep.md](docs/interview-prep.md) | Every measured number, module by module, plus the questions we expect |
| [demo-script.md](docs/demo-script.md) | Two four-minute demos, exact click paths, recovery steps |
| [demo-checklist.md](docs/demo-checklist.md) | The pre-demo run-through |
| [runbook.md](docs/runbook.md) | Run it, rebuild it, deploy it, fix it |
| [alternatives.md](docs/alternatives.md) | Every major choice, what we rejected, and why |
| [estimate-and-roadmap.md](docs/estimate-and-roadmap.md) | Effort spent, what production needs, three phases |
| [reusability.md](docs/reusability.md) | What another team can take, and what they must change |
| [data-sources.md](docs/data-sources.md) | Six datasets, licences, provenance |
| [assumptions.md](docs/assumptions.md) | Everything we generated, and how |
| [modules/](docs/modules/) | One guide per module |
| [design/](docs/design/) · [plans/](docs/plans/) | The design and the task-by-task plan this build followed |

---

## Team

**Vortex5** — V V Sanjay · Arvind T · Nouman Shafique · Ajmal
