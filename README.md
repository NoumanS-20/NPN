# NPN SCM — Team Vortex5

Two independent supply-chain planning applications, built for the Cognizant NPN SCM Hackathon
(use cases **P2 + PR1**).

| | **SupplyGuard** (PR1) | **TrendWear Planner** (P2) |
|---|---|---|
| Question | Given a material requirement, which approved suppliers get how much, and will they deliver? | What do we make, when does it move, and when do we discount it? |
| Core method | Risk prediction feeding a mixed-integer optimiser | Demand forecasting feeding constrained planning |
| Lives in | `apps/pr1/` | `apps/p2/` |

## The separation rule

The two use cases are independent, and so are the two applications. They share **no data, no models and no
runtime calls**. `packages/` holds only plumbing — metrics, time splits, logging, and front-end modules —
never domain logic. `tests/test_separation.py` fails the build if that is ever violated.

- **SupplyGuard chooses between suppliers.** It does not forecast; its material requirements are a
  deterministic roll-up of history.
- **TrendWear Planner decides quantities and timing.** It buys fabric from a single source under minimum
  order quantities and lead times; it never allocates across suppliers.

## Layout

```
apps/pr1/backend/supplyguard/   PR1 application package
apps/p2/backend/trendwear/      P2 application package
apps/*/web/                     static HTML, CSS and JavaScript — no framework, no build step
packages/pyshared/              metrics, time splits, logging
packages/web/                   shared CSS tokens and browser modules
data/raw/                       source datasets (gitignored, fetched by scripts/fetch_data.py)
docs/                           design, plan, assumptions, module guides, runbook
tests/                          repository-wide tests
```

## Running the tests

```bash
.venv/Scripts/python -m pytest        # Windows
python -m pytest                      # Linux and macOS
ruff check .
```

## Documentation

- `docs/design/` — the design this build follows
- `docs/plans/` — the task-by-task implementation plan
- `docs/Vortex5-Project-Brief.pdf` — the plain-English brief for mentors and the team

## Team

Vortex5 — V V Sanjay · Arvind T · Nouman Shafique · Ajmal
